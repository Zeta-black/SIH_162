"""Weak-supervision labelling policy for the prototype training set.

READ THIS BEFORE QUOTING ANY ACCURACY NUMBER.

FIRETRACE has no access to verified incident reports. There is no public,
per-detection ground-truth dataset that says "this NASA FIRMS pixel was a
refinery fire". So the training labels here are NOT ground truth. They are
produced by the explicit, auditable rule set below — a *labelling policy* —
applied to real FIRMS detections enriched with real OSM and land-use context.

What that means, stated plainly:

* The observations are real. Coordinates, brightness, FRP, timestamps and the
  surrounding geography all come from NASA FIRMS and OpenStreetMap.
* The labels are inferred, not verified.
* Therefore a test-set score measures how well the Random Forest reproduces
  this policy on held-out detections. It does NOT measure real-world fire-type
  accuracy, and the README, the model metadata and the dashboard all say so.

Two things make the exercise more than circular:

1. The policy only labels detections where the evidence is unambiguous, and
   refuses to label the rest. Roughly two-thirds of real detections fall through
   to `None` and are excluded from training rather than forced into a class.
2. The policy makes hard threshold cuts on a handful of signals, while the
   model sees ~60 features including thermal channel separation, pixel
   footprint and seasonality. The forest generalises across the smooth space
   between the policy's step functions rather than memorising a lookup table.

Every labelled row carries the rule id that produced it, so any reviewer can
audit the dataset's composition.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.schemas import HotspotEvent, LandCoverResult, NearestFacility, RecurrenceResult
from app.taxonomy import (
    AGRICULTURAL_BURNING,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    HIGH_HEAT_FACILITIES,
    INDUSTRIAL_FIRE,
    LC_CROPLAND,
    LC_FOREST,
    LC_GRASSLAND,
    LC_INDUSTRIAL,
    NATURAL_FIRE,
)

LABEL_POLICY_VERSION = "1.0.0"

# --- thresholds used by the policy -----------------------------------------
# These are calibrated against the FRP distribution VIIRS actually reports over
# India, measured while building this dataset rather than guessed: the median
# detection is around 4 MW, the 75th percentile around 6 MW and the 95th around
# 16 MW. An earlier draft used a 15 MW bar for "strong", which sat above the
# 90th percentile and meant the industrial-fire rules essentially never fired.
ONSITE_KM = 0.6             # within the facility footprint
ADJACENT_KM = 1.5           # immediately beside it
CLEAR_OF_INDUSTRY_KM = 4.0  # far enough that industry is not a plausible cause

# Clearance required before a vegetation/cropland label is allowed.
#
# This is deliberately much smaller than CLEAR_OF_INDUSTRY_KM, and it is paired
# with a "nearest facility is not a high-heat process" test instead. Reason:
# OSM tags a great many small workshops in Indian towns as `industrial`, so in
# a well-mapped district like central Punjab almost every crop fire sits within
# 4 km of *something* tagged industrial. Using raw distance to any tagged
# feature vetoed essentially every genuine agricultural detection there — 1
# label out of 1254 detections. What actually matters is whether the detection
# is on an industrial footprint and whether the nearby plant is the kind that
# runs hot, not whether a workshop is mapped down the road.
VEGETATION_MIN_CLEARANCE_KM = 1.5
PERSISTENT_DISTINCT_DAYS = 5
VERY_PERSISTENT_DISTINCT_DAYS = 8
EPISODIC_MAX_DISTINCT_DAYS = 2
HIGH_FRP_MW = 8.0           # ~p80 of observed detections
STRONG_FRP_MW = 15.0        # ~p95 of observed detections

# Minimum radiative power for R2's industrial-fire label, set at the median
# detection over India (~4 MW).
#
# The discriminator between INDUSTRIAL_FIRE and GAS_FLARE_OR_INDUSTRIAL_HEAT is
# PERSISTENCE, not power: both sit on the same plant, and what separates an
# incident from routine flaring is whether the pixel burns on most days or just
# this once. FRP's job in R2 is only to exclude trivial sub-noise anomalies, so
# an p80 bar was doing the wrong work -- it discarded every remaining on-site
# episodic detection in the dataset (their FRP maxes out at 7.9 MW) and left
# the class with too few examples to learn.
INDUSTRIAL_MIN_FRP_MW = 4.0
AGRI_MAX_FRP_MW = 40.0
# Co-detections on the same satellite pass required by R7. Set at roughly the
# 90th percentile of what is observed in Punjab during the burning season.
AGRI_MIN_CODETECTIONS = 3

# Crop-residue burning in northern India concentrates in two windows: the
# post-monsoon paddy harvest (Oct-Nov) and the wheat harvest (Apr-May). Used
# only to *strengthen* a cropland label, never to create one on its own.
AGRI_SEASON_MONTHS = {4, 5, 10, 11}


@dataclass
class LabelDecision:
    label: str | None
    rule: str
    rationale: str


def assign_label(
    event: HotspotEvent,
    nearest_facility: NearestFacility | None,
    land_cover: LandCoverResult,
    recurrence: RecurrenceResult,
) -> LabelDecision:
    """Apply the labelling policy to one enriched detection.

    Returns `label=None` when the evidence is ambiguous. Those rows are
    excluded from training on purpose — a classifier taught on coin flips is
    worse than one that has never seen the case.
    """
    distance = nearest_facility.distance_km if nearest_facility else None
    category = nearest_facility.category if nearest_facility else None
    high_heat = category in HIGH_HEAT_FACILITIES if category else False
    lc = land_cover.category
    frp = event.frp_mw
    month = event.acquisition_date.month
    distinct_days = recurrence.distinct_days
    has_history = recurrence.history_available

    # ---------------------------------------------------------------- R1
    # On a high-heat plant and burning on most days in the window: routine
    # flaring or continuous process heat, not an incident.
    if (
        distance is not None
        and distance <= ADJACENT_KM
        and high_heat
        and has_history
        and distinct_days >= PERSISTENT_DISTINCT_DAYS
    ):
        return LabelDecision(
            GAS_FLARE_OR_INDUSTRIAL_HEAT,
            "R1_persistent_high_heat_facility",
            f"{distance:.2f} km from a {category} and detected on {distinct_days} distinct days.",
        )

    # ---------------------------------------------------------------- R1b
    # Sitting on any mapped industrial facility and repeating on most days.
    # The facility need not be a classic high-heat process: a works that lights
    # up this consistently is a process source, not an incident.
    if (
        distance is not None
        and distance <= ONSITE_KM
        and has_history
        and distinct_days >= VERY_PERSISTENT_DISTINCT_DAYS
    ):
        return LabelDecision(
            GAS_FLARE_OR_INDUSTRIAL_HEAT,
            "R1b_very_persistent_on_facility",
            f"On a mapped {category}, detected on {distinct_days} distinct days.",
        )

    # ---------------------------------------------------------------- R2
    # On industrial ground, elevated signal, and NOT a routine repeat: the
    # signature of an abnormal industrial event.
    #
    # Land cover is not required when the facility itself is a high-heat
    # process. OSM land-use polygons cover only a minority of rural India, so
    # demanding an industrial polygon here would discard most true positives
    # for a reason that has nothing to do with the fire.
    if (
        distance is not None
        and distance <= ONSITE_KM
        and (lc == LC_INDUSTRIAL or high_heat)
        and has_history
        and distinct_days <= EPISODIC_MAX_DISTINCT_DAYS
        and frp is not None
        and frp >= INDUSTRIAL_MIN_FRP_MW
    ):
        return LabelDecision(
            INDUSTRIAL_FIRE,
            "R2_episodic_onsite_strong_signal",
            f"{distance:.2f} km from industry, {frp:.1f} MW, only {distinct_days} prior day(s).",
        )

    # ---------------------------------------------------------------- R2b
    # Just off a high-heat plant rather than on its mapped footprint. OSM
    # facility geometry is often a single node at the gate, so an on-site fire
    # can measure a kilometre away. The radiative-power bar is raised to keep
    # this from sweeping in ordinary vegetation fires nearby.
    if (
        distance is not None
        and distance <= ADJACENT_KM
        and high_heat
        and has_history
        and distinct_days <= EPISODIC_MAX_DISTINCT_DAYS
        and frp is not None
        and frp >= STRONG_FRP_MW
    ):
        return LabelDecision(
            INDUSTRIAL_FIRE,
            "R2b_episodic_adjacent_high_heat",
            f"{distance:.2f} km from a {category}, {frp:.1f} MW, {distinct_days} prior day(s).",
        )

    # ---------------------------------------------------------------- R3
    # Industrial land cover plus a strong episodic signal, facility tagging
    # in OSM being incomplete in many Indian industrial estates.
    if (
        lc == LC_INDUSTRIAL
        and distance is not None
        and distance <= ADJACENT_KM
        and frp is not None
        and frp >= STRONG_FRP_MW
        and has_history
        and distinct_days <= EPISODIC_MAX_DISTINCT_DAYS
    ):
        return LabelDecision(
            INDUSTRIAL_FIRE,
            "R3_industrial_landcover_strong_episodic",
            f"Industrial land cover, {frp:.1f} MW, {distinct_days} prior day(s).",
        )

    # A detection is treated as clear of industry when it is off any mapped
    # industrial footprint AND the nearest mapped facility is not a high-heat
    # process. See the note on VEGETATION_MIN_CLEARANCE_KM above.
    clear_of_industry = (
        distance is None or distance >= VEGETATION_MIN_CLEARANCE_KM
    ) and not high_heat

    # ---------------------------------------------------------------- R4
    # Cropland, clear of industry, modest radiative power, in a harvest window.
    if (
        lc == LC_CROPLAND
        and clear_of_industry
        and (frp is None or frp <= AGRI_MAX_FRP_MW)
        and month in AGRI_SEASON_MONTHS
    ):
        return LabelDecision(
            AGRICULTURAL_BURNING,
            "R4_cropland_in_harvest_window",
            f"Cropland land cover, {_dist_text(distance)} from industry, harvest month {month}.",
        )

    # ---------------------------------------------------------------- R5
    # Cropland, clear of industry, low power, not repeating. Outside the
    # harvest window this is weaker evidence, so the power bar is lower.
    if (
        lc == LC_CROPLAND
        and clear_of_industry
        and frp is not None
        and frp <= AGRI_MAX_FRP_MW / 2
        and has_history
        and distinct_days <= EPISODIC_MAX_DISTINCT_DAYS
    ):
        return LabelDecision(
            AGRICULTURAL_BURNING,
            "R5_cropland_low_power_episodic",
            f"Cropland land cover, {frp:.1f} MW, {distinct_days} prior day(s).",
        )

    # ---------------------------------------------------------------- R6
    # Forest or scrub, clear of industry: a vegetation fire.
    if lc in {LC_FOREST, LC_GRASSLAND} and clear_of_industry:
        return LabelDecision(
            NATURAL_FIRE,
            "R6_vegetation_clear_of_industry",
            f"{land_cover.label} land cover, {_dist_text(distance)} from industry.",
        )

    # ---------------------------------------------------------------- R7
    # Crop-residue burning without a cropland polygon to prove it.
    #
    # OpenStreetMap maps very little of India's farmland: in central Punjab,
    # 98% of detections fall in no land-use polygon at all, so R4 and R5 --
    # which both require a cropland polygon -- almost never fire in exactly the
    # region where stubble burning dominates. This rule uses the physical
    # signature instead: many fires burning simultaneously across a district,
    # each weak and short-lived, in a harvest month, away from industry.
    #
    # Land cover must not be forest, scrub or industrial. Unknown is allowed,
    # since unknown is the normal state over Indian farmland.
    #
    # Caveat carried into the dataset: co-detection density is measured over
    # the sampled detections, so it understates the true simultaneity of a
    # burning front and this rule is correspondingly conservative.
    if (
        month in AGRI_SEASON_MONTHS
        and clear_of_industry
        and lc not in {LC_FOREST, LC_GRASSLAND, LC_INDUSTRIAL}
        and recurrence.nearby_density >= AGRI_MIN_CODETECTIONS
        and frp is not None
        and frp <= AGRI_MAX_FRP_MW
        and has_history
        and distinct_days <= EPISODIC_MAX_DISTINCT_DAYS
    ):
        return LabelDecision(
            AGRICULTURAL_BURNING,
            "R7_harvest_season_burst",
            f"Harvest month {month}, {recurrence.nearby_density} fires co-detected nearby "
            f"on the same pass, {frp:.1f} MW, {_dist_text(distance)} from industry.",
        )

    # ---------------------------------------------------------------- none
    return LabelDecision(
        None,
        "R0_ambiguous",
        "Evidence did not meet any labelling rule; excluded from the training set.",
    )


def _dist_text(distance: float | None) -> str:
    if distance is None:
        return "no facility within the search radius"
    return f"{distance:.2f} km"


def policy_summary() -> dict[str, object]:
    """Machine-readable description of the policy, exposed by /api/model/info."""
    return {
        "version": LABEL_POLICY_VERSION,
        "label_source": "weak_supervision_rules",
        "ground_truth": False,
        "note": (
            "Labels are produced by a documented rule policy over real FIRMS and OSM "
            "evidence. They are not verified incident reports. Model metrics measure "
            "agreement with this policy on held-out data, not real-world accuracy."
        ),
        "thresholds": {
            "onsite_km": ONSITE_KM,
            "adjacent_km": ADJACENT_KM,
            "clear_of_industry_km": CLEAR_OF_INDUSTRY_KM,
            "vegetation_min_clearance_km": VEGETATION_MIN_CLEARANCE_KM,
            "persistent_distinct_days": PERSISTENT_DISTINCT_DAYS,
            "very_persistent_distinct_days": VERY_PERSISTENT_DISTINCT_DAYS,
            "episodic_max_distinct_days": EPISODIC_MAX_DISTINCT_DAYS,
            "high_frp_mw": HIGH_FRP_MW,
            "industrial_min_frp_mw": INDUSTRIAL_MIN_FRP_MW,
            "strong_frp_mw": STRONG_FRP_MW,
            "agri_max_frp_mw": AGRI_MAX_FRP_MW,
            "agri_min_codetections": AGRI_MIN_CODETECTIONS,
            "agri_season_months": sorted(AGRI_SEASON_MONTHS),
        },
        "rules": [
            "R1_persistent_high_heat_facility -> GAS_FLARE_OR_INDUSTRIAL_HEAT",
            "R1b_very_persistent_on_facility -> GAS_FLARE_OR_INDUSTRIAL_HEAT",
            "R2_episodic_onsite_strong_signal -> INDUSTRIAL_FIRE",
            "R2b_episodic_adjacent_high_heat -> INDUSTRIAL_FIRE",
            "R3_industrial_landcover_strong_episodic -> INDUSTRIAL_FIRE",
            "R4_cropland_in_harvest_window -> AGRICULTURAL_BURNING",
            "R5_cropland_low_power_episodic -> AGRICULTURAL_BURNING",
            "R6_vegetation_clear_of_industry -> NATURAL_FIRE",
            "R7_harvest_season_burst -> AGRICULTURAL_BURNING",
            "R0_ambiguous -> excluded from training",
        ],
    }
