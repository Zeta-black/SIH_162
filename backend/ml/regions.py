"""Areas and time windows used to build the training set and the demo snapshot.

Regions are deliberately small and purposeful rather than one big box over
India. Two reasons:

1. A tight box around a known industrial cluster produces detections where
   facility context actually exists in OpenStreetMap, which is what the
   distance-to-facility feature needs to be meaningful.
2. Overpass is a free shared service. Small boxes that snap to one or two
   cache tiles keep the total query count low and polite.

The `character` field records what the area is known for. It is documentation
for whoever reads the dataset later — it is NOT used as a label, because
labelling by region name would make the whole exercise circular.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Region:
    id: str
    name: str
    bbox: tuple[float, float, float, float]  # west, south, east, north
    character: str


REGIONS: list[Region] = [
    # ---------------------------------------------------- industrial clusters
    Region("jamnagar", "Jamnagar refinery belt, Gujarat", (69.15, 22.05, 70.35, 22.75), "industrial"),
    Region("hazira", "Hazira / Surat industrial, Gujarat", (72.55, 21.02, 73.15, 21.45), "industrial"),
    Region("vadodara", "Vadodara / Ankleshwar chemical belt", (72.85, 21.55, 73.45, 22.45), "industrial"),
    Region("taloja", "Mumbai / Taloja / Thane industrial", (72.85, 18.85, 73.45, 19.35), "industrial"),
    Region("singrauli", "Singrauli thermal power cluster", (82.25, 23.85, 82.95, 24.35), "industrial"),
    Region("korba", "Korba coal and power cluster", (82.45, 22.15, 83.05, 22.65), "industrial"),
    Region("angul", "Angul / Talcher coal and steel, Odisha", (84.75, 20.65, 85.45, 21.25), "industrial"),
    Region("jamshedpur", "Jamshedpur steel belt", (85.95, 22.55, 86.55, 23.05), "industrial"),
    Region("bhilai", "Bhilai / Durg steel belt", (81.05, 21.05, 81.65, 21.45), "industrial"),
    Region("vizag", "Visakhapatnam port and industry", (83.05, 17.55, 83.55, 17.95), "industrial"),
    Region("manali_chennai", "Manali petrochemical, Chennai", (80.05, 13.05, 80.45, 13.35), "industrial"),
    Region("paradip", "Paradip refinery and port, Odisha", (86.45, 20.15, 86.85, 20.45), "industrial"),
    Region("barmer", "Barmer refinery and oilfields, Rajasthan", (71.05, 25.55, 71.85, 26.15), "industrial"),
    Region("mathura", "Mathura refinery belt, UP", (77.55, 27.35, 78.05, 27.75), "industrial"),
    # ------------------------------------------------------ agricultural belts
    Region("punjab_central", "Central Punjab cropland", (75.05, 30.35, 76.05, 31.15), "agricultural"),
    Region("punjab_malwa", "Malwa Punjab cropland", (74.35, 29.95, 75.35, 30.75), "agricultural"),
    Region("haryana", "Haryana cropland", (76.05, 29.25, 77.05, 30.05), "agricultural"),
    Region("up_west", "Western Uttar Pradesh cropland", (78.55, 26.85, 79.55, 27.65), "agricultural"),
    # --------------------------------------------------------- forest / scrub
    Region("similipal", "Similipal forest, Odisha", (86.05, 21.35, 86.75, 22.05), "forest"),
    Region("kanha_pench", "Kanha / Pench forest, MP", (79.75, 21.85, 80.65, 22.65), "forest"),
    Region("bastar", "Bastar forest, Chhattisgarh", (81.15, 18.85, 82.05, 19.75), "forest"),
    Region("bandipur", "Bandipur / Nagarhole forest, Karnataka", (76.05, 11.65, 76.75, 12.15), "forest"),
    Region("uttarakhand", "Uttarakhand hill forest", (78.65, 29.65, 79.55, 30.35), "forest"),
    Region("nallamala", "Nallamala forest, Andhra Pradesh", (78.65, 15.65, 79.45, 16.35), "forest"),
]

REGIONS_BY_ID = {r.id: r for r in REGIONS}
