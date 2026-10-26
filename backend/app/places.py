"""A small gazetteer of the areas FIRETRACE actually holds data for.

Why this exists: most OpenStreetMap industrial features in our archive have no
`name` tag — 14 of the first 400 do — and none carry `addr:district` or
`addr:state`. So a site with no named facility had no identity at all, and the
queue showed rows reading "Gas / oil infrastructure · 21.105°N, 72.642°E", three
in a row, which is unusable as a work list.

There is no reverse geocoder here (that would need a paid API or a large offline
dataset), so a point is named after the monitored area it falls inside. These
are the same areas the dataset and the demo archive were built from, with the
same human names, so nothing here is invented — if a point is not inside one of
them it gets no place name rather than a guessed one.

The coordinates duplicate `backend/ml/regions.py`. That is deliberate: the API
layer does not import the training package, and six bounding boxes are cheaper
to keep in step than a cross-package dependency. `test_places.py` asserts the two
lists agree, so a drift fails the suite rather than going unnoticed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Area:
    """One monitored area: a bounding box and the name a person would use."""

    region_id: str
    place: str
    state: str
    # west, south, east, north
    bbox: tuple[float, float, float, float]

    @property
    def label(self) -> str:
        return f"{self.place}, {self.state}"

    def contains(self, lat: float, lon: float) -> bool:
        west, south, east, north = self.bbox
        return south <= lat <= north and west <= lon <= east


# Ordered smallest-first so a point inside two overlapping boxes takes the more
# specific name.
AREAS: list[Area] = [
    Area("hazira", "Hazira", "Gujarat", (72.55, 21.02, 73.15, 21.45)),
    Area("jamnagar", "Jamnagar", "Gujarat", (69.15, 22.05, 70.35, 22.75)),
    Area("vadodara", "Ankleshwar", "Gujarat", (72.85, 21.55, 73.45, 22.45)),
    Area("taloja", "Taloja", "Maharashtra", (72.85, 18.85, 73.45, 19.35)),
    Area("singrauli", "Singrauli", "Madhya Pradesh", (82.25, 23.85, 82.95, 24.35)),
    Area("korba", "Korba", "Chhattisgarh", (82.45, 22.15, 83.05, 22.65)),
    Area("angul", "Angul", "Odisha", (84.75, 20.65, 85.45, 21.25)),
    Area("jamshedpur", "Jamshedpur", "Jharkhand", (85.95, 22.55, 86.55, 23.05)),
    Area("bhilai", "Bhilai", "Chhattisgarh", (81.05, 21.05, 81.65, 21.45)),
    Area("vizag", "Visakhapatnam", "Andhra Pradesh", (83.05, 17.55, 83.55, 17.95)),
    Area("manali_chennai", "Manali", "Tamil Nadu", (80.05, 13.05, 80.45, 13.35)),
    Area("paradip", "Paradip", "Odisha", (86.45, 20.15, 86.85, 20.45)),
    Area("barmer", "Barmer", "Rajasthan", (71.05, 25.55, 71.85, 26.15)),
    Area("mathura", "Mathura", "Uttar Pradesh", (77.55, 27.35, 78.05, 27.75)),
    Area("punjab_central", "Central Punjab", "Punjab", (75.05, 30.35, 76.05, 31.15)),
    Area("punjab_malwa", "Malwa", "Punjab", (74.35, 29.95, 75.35, 30.75)),
    Area("haryana", "Haryana cropland", "Haryana", (76.05, 29.25, 77.05, 30.05)),
    Area("up_west", "Western Uttar Pradesh", "Uttar Pradesh", (78.55, 26.85, 79.55, 27.65)),
    Area("similipal", "Similipal", "Odisha", (86.05, 21.35, 86.75, 22.05)),
    Area("kanha_pench", "Kanha / Pench", "Madhya Pradesh", (79.75, 21.85, 80.65, 22.65)),
    Area("bastar", "Bastar", "Chhattisgarh", (81.15, 18.85, 82.05, 19.75)),
    Area("bandipur", "Bandipur", "Karnataka", (76.05, 11.65, 76.75, 12.15)),
    Area("uttarakhand", "Uttarakhand hills", "Uttarakhand", (78.65, 29.65, 79.55, 30.35)),
    Area("nallamala", "Nallamala", "Andhra Pradesh", (78.65, 15.65, 79.45, 16.35)),
]

AREAS_BY_ID = {a.region_id: a for a in AREAS}


def place_for(lat: float, lon: float) -> str | None:
    """'Hazira, Gujarat' for a point inside a monitored area, else None.

    Returns None rather than a nearest-guess: naming a detection after an area
    it is not in would be a fabricated location, and a coordinate is a worse
    label than a wrong one is a lie.
    """
    for area in AREAS:
        if area.contains(lat, lon):
            return area.label
    return None


def area_for(lat: float, lon: float) -> Area | None:
    for area in AREAS:
        if area.contains(lat, lon):
            return area
    return None
