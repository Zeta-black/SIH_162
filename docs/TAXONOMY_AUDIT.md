# FIRETRACE data-driven taxonomy audit

**Audit date:** 17 September 2026

## Decision

Do not expand the four current weak-policy labels into a larger source-cause taxonomy.
The available inputs establish thermal behaviour and mapped industrial context, but
cannot independently establish what is burning or prove that an episodic hotspot
near a plant is an industrial fire.

The smallest scientifically defensible operational taxonomy is:

| Operational category | Directly observable basis | Not asserted |
|---|---|---|
| `PERSISTENT_INDUSTRIAL_THERMAL_SOURCE` | Repeated detections plus mapped industrial context | Gas flare, legal routine operation, or exact process |
| `EPISODIC_INDUSTRIAL_CONTEXT_THERMAL_EVENT` | Short-lived/recent event plus mapped industrial context | Accidental industrial fire or cause |
| `NON_INDUSTRIAL_VEGETATION_CONTEXT_EVENT` | Mapped vegetation/cropland, away from mapped high-heat industry | Wildfire versus agricultural burn without verified labels |
| `NEEDS_REVIEW` | Missing, conflicting, or insufficient context | A source type |

Industrial context is evidence metadata (nearest facility, type, distance, on-site
flag), not proof of industrial fire. Priority remains a separate transparent triage
calculation, not classification.

The shipped four class IDs remain a backward-compatible weak-policy model output.
They must remain provisional likelihoods until independently labelled data supports a
versioned model/API migration.

## Current implementation

FIRMS detects thermal events. FIRETRACE enriches them with OSM facility and land-use
context, recurrence, and 48 features, then applies a 300-tree Random Forest. It combines
detection, context/source-type triage, and priority ranking. It is not a confirmed-cause
classifier or a validated incident system.

Current trained IDs: `INDUSTRIAL_FIRE`, `GAS_FLARE_OR_INDUSTRIAL_HEAT`,
`AGRICULTURAL_BURNING`, and `NATURAL_FIRE`. `UNKNOWN` is inference-time abstention,
never a training class.

## Dataset audit

| Item | Finding |
|---|---|
| Observations | Real NASA FIRMS detections; OSM context is real but incomplete |
| Label source | Deterministic weak-supervision rules R1-R7; no field or incident verification |
| Labelled rows | 3,514 |
| Unlabelled after deduplication | 7,290 (67.5%) |
| Duplicates | 18 overlapping-region labelled rows and 182 unlabelled rows removed |
| Geographic coverage | 11 represented Indian regions; 17 configured regions have no labelled rows |
| Temporal coverage | 25 Oct 2025-15 Sep 2026; concentrated in historical 5-day windows |
| Product mix | Mostly VIIRS NOAA-20/SNPP standard products; only 80 NRT and 4 MODIS rows |
| Missing context | `nearest_facility_km` is null in 524 labelled rows; OSM coverage is uneven |

| Weak-policy class | Rows | Share | Consequence |
|---|---:|---:|---|
| Gas flare / industrial heat | 2,534 | 72.1% | Majority class; combines distinct physical causes |
| Natural fire | 671 | 19.1% | Vegetation-context proxy, not verified wildfire |
| Agricultural burning | 237 | 6.7% | Crop/season proxy, not verified agricultural burn |
| Industrial fire | 72 | 2.0% | Only 8 held-out rows; no credible cause-class metric |

There are no verified labels in the shipped training or replay data.

## Distinguishability

| Candidate | Evidence available | Main confusions | Standalone ML class now? |
|---|---|---|---|
| Industrial fire | Episodic heat, proximity, FRP, recurrence | Plant heat, flare, nearby vegetation, OSM geometry error | No |
| Gas flare | Persistence and oil/gas/refinery proximity | Process heat, furnace, long-lived fire | No |
| Persistent industrial heat | Recurrence plus industrial context | Flare versus other process heat | Yes, as observable category only |
| Agricultural burn | Cropland/season, episodic heat, density | Grassland/wildfire and unknown land cover | No |
| Wildfire | Vegetation context and distance from industry | Crop/grass fire and unmapped industry | No |
| Mining source | Mine/quarry metadata only | Process heat and bare land | No |

## Ground truth and evaluation requirements

Industrial fire needs an authoritative incident report, operator/regulator confirmation, or
time/location-correlated imagery. Gas flare needs a known flare asset plus persistent signature.
Agricultural and wildland claims need authority records, validated perimeters, or independent
imagery. Mining needs independently verified assets. None are presently available in FIRETRACE.

A revised model requires event/facility-level splitting before row expansion, geographic and
chronological holdouts, hard negatives, per-class support and precision/recall/F1, abstention and
context-coverage rates, calibration analysis, and prospective validation. Real-world accuracy
must remain unreported until labels are independent.

## Changes made

- Corrected API, README, model-card, judge-QA, and priority wording: RF vote share is not a
  calibrated probability.
- Preserved live ingestion, historical fallback, API compatibility, and the existing model.
  No taxonomy/model rewrite was fabricated from the same weak labels.

## Limitation

The shipped flat model is transparent policy-assisted triage only. A taxonomy migration requires
verified labels, a versioned artefact, API/UI migration, and independent evaluation; it must not
be simulated from the present policy labels.
