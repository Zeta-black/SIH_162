"""Class taxonomy and shared vocabularies.

Kept in one module so the training script, the inference service and the API
can never drift apart on what a class or a land-cover category means.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Thermal event classes.
#
# Only the first four are TRAINED classes. UNKNOWN is never a training label;
# it is an abstention applied at inference time when the model's top
# probability falls below the configured threshold. This keeps the classifier
# honest: it says "I don't know" instead of forcing a weak guess.
# ---------------------------------------------------------------------------
INDUSTRIAL_FIRE = "INDUSTRIAL_FIRE"
GAS_FLARE_OR_INDUSTRIAL_HEAT = "GAS_FLARE_OR_INDUSTRIAL_HEAT"
AGRICULTURAL_BURNING = "AGRICULTURAL_BURNING"
NATURAL_FIRE = "NATURAL_FIRE"
UNKNOWN = "UNKNOWN"

TRAINED_CLASSES: list[str] = [
    INDUSTRIAL_FIRE,
    GAS_FLARE_OR_INDUSTRIAL_HEAT,
    AGRICULTURAL_BURNING,
    NATURAL_FIRE,
]
ALL_CLASSES: list[str] = TRAINED_CLASSES + [UNKNOWN]

CLASS_LABELS: dict[str, str] = {
    # This is an evidence-based model class, not an independently confirmed
    # incident. The display name makes that boundary visible in the UI.
    INDUSTRIAL_FIRE: "Potential Industrial Fire",
    GAS_FLARE_OR_INDUSTRIAL_HEAT: "Gas Flare / Persistent Industrial Heat",
    AGRICULTURAL_BURNING: "Agricultural Burning",
    NATURAL_FIRE: "Natural / Vegetation Fire",
    UNKNOWN: "Unclassified",
}

CLASS_DESCRIPTIONS: dict[str, str] = {
    INDUSTRIAL_FIRE: (
        "Thermal anomaly on or immediately beside industrial infrastructure with "
        "an episodic signature — consistent with an accidental or abnormal fire."
    ),
    GAS_FLARE_OR_INDUSTRIAL_HEAT: (
        "Thermal anomaly on industrial infrastructure that repeats across many "
        "days — consistent with routine flaring or a continuous process heat source."
    ),
    AGRICULTURAL_BURNING: (
        "Thermal anomaly over cropland, typically low radiative power and "
        "clustered in seasonal windows — consistent with crop-residue burning."
    ),
    NATURAL_FIRE: (
        "Thermal anomaly over forest, scrub or grassland away from industrial "
        "infrastructure — consistent with a vegetation fire."
    ),
    UNKNOWN: (
        "Evidence was not strong enough for the model to commit to a class. "
        "Requires human verification."
    ),
}

# Colour tokens are defined once here and consumed by the frontend so the map,
# the legend and the tables can never disagree.
#
# This palette was chosen with a colour-blindness validator rather than by eye.
# The obvious instinct — make every fire class a shade of warm — fails badly:
# red/orange/amber measured a deuteranopia separation of 1.1 (indistinguishable)
# and 8.6 for normal vision. Moving the persistent-heat class to violet, which
# is also how the team's own proposal deck drew it, clears every check.
#
# The remaining warn is red vs green at deuteranopia 7.1, inside the 6-8 floor
# band that is permitted only alongside secondary encoding. That encoding is
# present everywhere: each class carries a three-letter code and a text label,
# and the event table repeats both.
CLASS_COLORS: dict[str, str] = {
    INDUSTRIAL_FIRE: "#a51d12",
    GAS_FLARE_OR_INDUSTRIAL_HEAT: "#8250df",
    AGRICULTURAL_BURNING: "#b8860b",
    NATURAL_FIRE: "#1a7f4b",
    # Deliberately neutral: UNKNOWN is the absence of a classification, not a
    # fifth category competing for attention.
    UNKNOWN: "#6b7280",
}

# Short code shown next to the colour so the map is readable without relying
# on colour alone (accessibility).
CLASS_CODES: dict[str, str] = {
    INDUSTRIAL_FIRE: "IND",
    GAS_FLARE_OR_INDUSTRIAL_HEAT: "FLR",
    AGRICULTURAL_BURNING: "AGR",
    NATURAL_FIRE: "NAT",
    UNKNOWN: "UNK",
}

# ---------------------------------------------------------------------------
# Land cover categories.
#
# Derived from OpenStreetMap landuse / natural polygons, not from a satellite
# land-cover raster. Named accordingly so nothing in the UI can imply this is
# a spectral classification.
# ---------------------------------------------------------------------------
LC_INDUSTRIAL = "industrial_builtup"
LC_CROPLAND = "cropland"
LC_FOREST = "forest_vegetation"
LC_GRASSLAND = "grassland_scrub"
LC_WATER = "water"
LC_BARE = "bare_open"
LC_URBAN = "urban_residential"
LC_UNKNOWN = "unknown"

LAND_COVER_CLASSES: list[str] = [
    LC_INDUSTRIAL,
    LC_CROPLAND,
    LC_FOREST,
    LC_GRASSLAND,
    LC_WATER,
    LC_BARE,
    LC_URBAN,
    LC_UNKNOWN,
]

LAND_COVER_LABELS: dict[str, str] = {
    LC_INDUSTRIAL: "Industrial / built-up",
    LC_CROPLAND: "Cropland / agriculture",
    LC_FOREST: "Forest / vegetation",
    LC_GRASSLAND: "Grassland / scrub",
    LC_WATER: "Water",
    LC_BARE: "Bare / open land",
    LC_URBAN: "Urban residential",
    LC_UNKNOWN: "Unknown",
}

# ---------------------------------------------------------------------------
# Industrial facility categories recognised from OSM tags.
# ---------------------------------------------------------------------------
FACILITY_CATEGORIES: list[str] = [
    "refinery",
    "power_plant",
    "steel_metal",
    "chemical",
    "cement",
    "mine_quarry",
    "gas_oil_infrastructure",
    "factory_works",
    "industrial_area",
    "none",
]

FACILITY_LABELS: dict[str, str] = {
    "refinery": "Oil / petrochemical refinery",
    "power_plant": "Power plant",
    "steel_metal": "Steel / metal works",
    "chemical": "Chemical plant",
    "cement": "Cement works",
    "mine_quarry": "Mine / quarry",
    "gas_oil_infrastructure": "Gas / oil infrastructure",
    "factory_works": "Factory / works",
    "industrial_area": "Industrial estate",
    "none": "No facility within search radius",
}

# Facilities whose normal operation involves high sustained heat. Used by the
# explanation layer, and as an input to the weak-supervision labeller.
HIGH_HEAT_FACILITIES = {
    "refinery",
    "power_plant",
    "steel_metal",
    "chemical",
    "gas_oil_infrastructure",
    "cement",
}

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"

PRIORITY_HIGH = "HIGH"
PRIORITY_MEDIUM = "MEDIUM"
PRIORITY_LOW = "LOW"
