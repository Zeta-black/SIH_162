"""Event store.

Why SQLite and not PostGIS
--------------------------
The proposal names PostgreSQL + PostGIS, and that is the right production
answer. For a hackathon prototype that has to start on any laptop with one
command, a required database server is the single most likely thing to break a
live demo. So the prototype ships on SQLite (stdlib, zero setup) behind a small
repository interface, and `docs/postgis_schema.sql` carries the equivalent
PostGIS schema — real geometry columns, GiST indexes and all — as the
documented deployment path.

Spatial work happens in Python against the grid index in `services/geo.py`.
For the tens of thousands of detections a prototype handles this is fast; past
that, the PostGIS schema is what you move to.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app.config import settings
from app.schemas import Facility, HotspotEvent

log = logging.getLogger("firetrace.store")

SCHEMA = """
CREATE TABLE IF NOT EXISTS hotspot_events (
    event_id            TEXT PRIMARY KEY,
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    acquisition_date    TEXT NOT NULL,
    acquisition_time    TEXT NOT NULL,
    acquired_at         TEXT NOT NULL,
    brightness_k        REAL,
    brightness_secondary_k REAL,
    frp_mw              REAL,
    firms_confidence_raw   TEXT,
    firms_confidence_level TEXT,
    satellite           TEXT,
    instrument          TEXT,
    day_night           TEXT,
    scan                REAL,
    track               REAL,
    version             TEXT,
    source_product      TEXT NOT NULL,
    source_mode         TEXT NOT NULL,
    raw_source_reference TEXT,
    ingested_at         TEXT NOT NULL,
    unavailable_fields  TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_date ON hotspot_events(acquisition_date);
CREATE INDEX IF NOT EXISTS idx_events_latlon ON hotspot_events(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_events_product ON hotspot_events(source_product);

CREATE TABLE IF NOT EXISTS facilities (
    facility_id     TEXT PRIMARY KEY,
    name            TEXT,
    category        TEXT NOT NULL,
    category_label  TEXT NOT NULL,
    latitude        REAL NOT NULL,
    longitude       REAL NOT NULL,
    osm_type        TEXT,
    osm_id          INTEGER,
    tags            TEXT,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_facilities_latlon ON facilities(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_facilities_category ON facilities(category);

CREATE TABLE IF NOT EXISTS classifications (
    event_id        TEXT PRIMARY KEY,
    label           TEXT NOT NULL,
    confidence      REAL NOT NULL,
    priority_score  REAL NOT NULL,
    model_version   TEXT,
    payload         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES hotspot_events(event_id)
);
CREATE INDEX IF NOT EXISTS idx_classifications_label ON classifications(label);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    mode            TEXT NOT NULL,
    bbox            TEXT,
    products        TEXT,
    events_ingested INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);
"""


class EventStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or settings.database_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ready = False
        self.error: str | None = None
        try:
            with self.connect() as conn:
                conn.executescript(SCHEMA)
            self.ready = True
        except sqlite3.Error as exc:
            self.error = str(exc)
            log.error("[STORE] could not initialise database: %s", exc)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ---------------------------------------------------------------- events
    def upsert_events(self, events: list[HotspotEvent]) -> int:
        """Insert detections, ignoring ones already stored.

        The event_id is a hash of position + time + product, so re-running an
        ingest over an overlapping window is idempotent.
        """
        if not events or not self.ready:
            return 0
        rows = [
            (
                e.event_id,
                e.latitude,
                e.longitude,
                e.acquisition_date.isoformat(),
                e.acquisition_time,
                e.acquired_at.isoformat(),
                e.brightness_k,
                e.brightness_secondary_k,
                e.frp_mw,
                e.firms_confidence_raw,
                e.firms_confidence_level,
                e.satellite,
                e.instrument,
                e.day_night,
                e.scan,
                e.track,
                e.version,
                e.source_product,
                e.source_mode,
                e.raw_source_reference,
                e.ingested_at.isoformat(),
                json.dumps(e.unavailable_fields),
            )
            for e in events
        ]
        try:
            with self.connect() as conn:
                before = conn.execute("SELECT COUNT(*) FROM hotspot_events").fetchone()[0]
                conn.executemany(
                    """INSERT OR IGNORE INTO hotspot_events VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    rows,
                )
                after = conn.execute("SELECT COUNT(*) FROM hotspot_events").fetchone()[0]
            inserted = after - before
            log.info("[STORE] ingested %d new events (%d submitted)", inserted, len(events))
            return inserted
        except sqlite3.Error as exc:
            log.error("[STORE] event insert failed: %s", exc)
            return 0

    def load_events(
        self,
        bbox: tuple[float, float, float, float] | None = None,
        since: date | None = None,
        until: date | None = None,
        limit: int | None = None,
    ) -> list[HotspotEvent]:
        if not self.ready:
            return []
        clauses: list[str] = []
        params: list[object] = []
        if bbox:
            west, south, east, north = bbox
            clauses.append("latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?")
            params += [south, north, west, east]
        if since:
            clauses.append("acquisition_date >= ?")
            params.append(since.isoformat())
        if until:
            clauses.append("acquisition_date <= ?")
            params.append(until.isoformat())
        sql = "SELECT * FROM hotspot_events"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY acquired_at DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        try:
            with self.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.error("[STORE] event query failed: %s", exc)
            return []
        return [_row_to_event(r) for r in rows]

    def event_count(self) -> int:
        if not self.ready:
            return 0
        try:
            with self.connect() as conn:
                return int(conn.execute("SELECT COUNT(*) FROM hotspot_events").fetchone()[0])
        except sqlite3.Error:
            return 0

    def date_span(self) -> tuple[str | None, str | None]:
        if not self.ready:
            return None, None
        try:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT MIN(acquisition_date), MAX(acquisition_date) FROM hotspot_events"
                ).fetchone()
            return row[0], row[1]
        except sqlite3.Error:
            return None, None

    # ------------------------------------------------------------ facilities
    def upsert_facilities(self, facilities: list[Facility]) -> int:
        if not facilities or not self.ready:
            return 0
        now = datetime.now(timezone.utc).isoformat()
        rows = [
            (
                f.facility_id,
                f.name,
                f.category,
                f.category_label,
                f.latitude,
                f.longitude,
                f.osm_type,
                f.osm_id,
                json.dumps(f.tags),
                now,
            )
            for f in facilities
        ]
        try:
            with self.connect() as conn:
                conn.executemany(
                    "INSERT OR REPLACE INTO facilities VALUES (?,?,?,?,?,?,?,?,?,?)", rows
                )
            return len(rows)
        except sqlite3.Error as exc:
            log.error("[STORE] facility insert failed: %s", exc)
            return 0

    def load_facilities(
        self, bbox: tuple[float, float, float, float] | None = None
    ) -> list[Facility]:
        if not self.ready:
            return []
        sql = "SELECT * FROM facilities"
        params: list[object] = []
        if bbox:
            west, south, east, north = bbox
            sql += " WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?"
            params += [south, north, west, east]
        try:
            with self.connect() as conn:
                rows = conn.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            log.error("[STORE] facility query failed: %s", exc)
            return []
        return [
            Facility(
                facility_id=r["facility_id"],
                name=r["name"],
                category=r["category"],
                category_label=r["category_label"],
                latitude=r["latitude"],
                longitude=r["longitude"],
                osm_type=r["osm_type"] or "node",
                osm_id=r["osm_id"] or 0,
                tags=json.loads(r["tags"] or "{}"),
            )
            for r in rows
        ]

    def facility_count(self) -> int:
        if not self.ready:
            return 0
        try:
            with self.connect() as conn:
                return int(conn.execute("SELECT COUNT(*) FROM facilities").fetchone()[0])
        except sqlite3.Error:
            return 0

    # --------------------------------------------------------------- ingests
    def record_ingest(
        self, mode: str, bbox: str | None, products: list[str], count: int, notes: str = ""
    ) -> None:
        if not self.ready:
            return
        try:
            with self.connect() as conn:
                conn.execute(
                    "INSERT INTO ingest_runs (started_at, mode, bbox, products, events_ingested, notes)"
                    " VALUES (?,?,?,?,?,?)",
                    (
                        datetime.now(timezone.utc).isoformat(),
                        mode,
                        bbox,
                        ",".join(products),
                        count,
                        notes[:500],
                    ),
                )
        except sqlite3.Error as exc:
            log.warning("[STORE] could not record ingest run: %s", exc)

    def last_ingest(self) -> dict[str, object] | None:
        if not self.ready:
            return None
        try:
            with self.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM ingest_runs ORDER BY id DESC LIMIT 1"
                ).fetchone()
            return dict(row) if row else None
        except sqlite3.Error:
            return None

    def prune_older_than(self, days: int) -> int:
        """Keep the prototype database from growing without bound."""
        if not self.ready:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
        try:
            with self.connect() as conn:
                cur = conn.execute("DELETE FROM hotspot_events WHERE acquisition_date < ?", (cutoff,))
                return cur.rowcount or 0
        except sqlite3.Error:
            return 0


def _row_to_event(r: sqlite3.Row) -> HotspotEvent:
    return HotspotEvent(
        event_id=r["event_id"],
        latitude=r["latitude"],
        longitude=r["longitude"],
        acquisition_date=date.fromisoformat(r["acquisition_date"]),
        acquisition_time=r["acquisition_time"],
        acquired_at=datetime.fromisoformat(r["acquired_at"]),
        brightness_k=r["brightness_k"],
        brightness_secondary_k=r["brightness_secondary_k"],
        frp_mw=r["frp_mw"],
        firms_confidence_raw=r["firms_confidence_raw"],
        firms_confidence_level=r["firms_confidence_level"],
        satellite=r["satellite"],
        instrument=r["instrument"],
        day_night=r["day_night"],
        scan=r["scan"],
        track=r["track"],
        version=r["version"],
        source_product=r["source_product"],
        source_mode=r["source_mode"],
        raw_source_reference=r["raw_source_reference"] or "",
        ingested_at=datetime.fromisoformat(r["ingested_at"]),
        unavailable_fields=json.loads(r["unavailable_fields"] or "[]"),
    )


_store: EventStore | None = None


def get_store() -> EventStore:
    global _store
    if _store is None:
        _store = EventStore()
    return _store


def reset_store() -> None:
    global _store
    _store = None
