"""FIRMS request windows.

The FIRMS area API rejects any `day_range` outside [1..5] — verified against
the live endpoint, which answers HTTP 400 with "Invalid day range. Expects
[1..5]." So a long observation period has to be assembled from consecutive
5-day requests rather than asked for in one.

That constraint is turned into an advantage here by making the windows
*contiguous*: five back-to-back 5-day requests give 25 unbroken days of
coverage, which is what the recurrence features need. A flare that appears on
20 of 25 consecutive days is visibly persistent; the same 25 days sampled at
random across a year would not show that at all.

Two blocks are collected:

  Block A  25 Oct - 19 Nov 2025   post-monsoon paddy residue burning
  Block B  01 Mar - 26 Mar 2026   spring forest fire season

They sit about four months apart, comfortably outside the 60-day recurrence
lookback, so neither block contaminates the other's history counts.

Two VIIRS satellites are requested per window. More passes per day means
better temporal resolution on exactly the persistence signal the model relies
on.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Window:
    id: str
    start: str  # ISO date; "" means "most recent", which FIRMS defaults to
    days: int
    note: str
    products: tuple[str, ...] = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP")


FIRMS_MAX_DAYS = 5

# --- Block A: post-monsoon crop residue burning ----------------------------
BLOCK_A = [
    Window("a1_2025-10-25", "2025-10-25", 5, "Paddy residue burning, onset"),
    Window("a2_2025-10-30", "2025-10-30", 5, "Paddy residue burning, rising"),
    Window("a3_2025-11-04", "2025-11-04", 5, "Paddy residue burning, peak"),
    Window("a4_2025-11-09", "2025-11-09", 5, "Paddy residue burning, peak"),
    Window("a5_2025-11-14", "2025-11-14", 5, "Paddy residue burning, tail"),
]

# --- Block B: spring forest fire season ------------------------------------
BLOCK_B = [
    Window("b1_2026-03-01", "2026-03-01", 5, "Forest fire season, onset"),
    Window("b2_2026-03-06", "2026-03-06", 5, "Forest fire season"),
    Window("b3_2026-03-11", "2026-03-11", 5, "Forest fire season"),
    Window("b4_2026-03-16", "2026-03-16", 5, "Forest fire season, peak"),
    Window("b5_2026-03-21", "2026-03-21", 5, "Forest fire season, peak"),
]

TRAINING_WINDOWS: list[Window] = BLOCK_A + BLOCK_B


def snapshot_windows(most_recent_start: str, second_start: str) -> list[Window]:
    """Two contiguous recent 5-day windows for the demo snapshot.

    NRT products are used because the snapshot should look like what an
    operator would actually be staring at, and NRT is what a live deployment
    consumes.
    """
    return [
        Window(
            "snap_recent",
            most_recent_start,
            5,
            "Most recent 5 days",
            products=("VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"),
        ),
        Window(
            "snap_prior",
            second_start,
            5,
            "Preceding 5 days",
            products=("VIIRS_NOAA21_NRT", "VIIRS_SNPP_NRT", "MODIS_NRT"),
        ),
    ]
