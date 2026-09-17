-- FIRETRACE — PostgreSQL + PostGIS schema (production deployment path)
--
-- The running prototype uses SQLite (see backend/app/store/db.py) because a
-- hackathon demo must start on any laptop with one command, and a required
-- database server is the most likely thing to break a live demonstration.
--
-- This file is the equivalent schema for a real deployment: real geometry
-- columns, GiST spatial indexes, and the spatial queries pushed down into the
-- database instead of being computed in Python. The application's repository
-- layer is the only thing that would need to change.
--
--   createdb firetrace
--   psql -d firetrace -f docs/postgis_schema.sql

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------------------
-- Thermal detections
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hotspot_events (
    event_id                TEXT PRIMARY KEY,
    geom                    geography(Point, 4326) NOT NULL,
    latitude                DOUBLE PRECISION NOT NULL,
    longitude               DOUBLE PRECISION NOT NULL,

    acquisition_date        DATE NOT NULL,
    acquisition_time        TIME NOT NULL,
    acquired_at             TIMESTAMPTZ NOT NULL,

    -- NULL means the FIRMS product did not report the value. It is never
    -- back-filled with a substitute; the distinction matters to the model.
    brightness_k            REAL,
    brightness_secondary_k  REAL,
    frp_mw                  REAL,

    firms_confidence_raw    TEXT,
    firms_confidence_level  TEXT CHECK (
        firms_confidence_level IN ('low', 'nominal', 'high')
    ),

    satellite               TEXT,
    instrument              TEXT,
    day_night               CHAR(1) CHECK (day_night IN ('D', 'N')),
    scan                    REAL,
    track                   REAL,
    version                 TEXT,

    source_product          TEXT NOT NULL,
    source_mode             TEXT NOT NULL CHECK (source_mode IN ('live', 'snapshot')),
    raw_source_reference    TEXT,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    unavailable_fields      JSONB NOT NULL DEFAULT '[]'::jsonb
);

-- Spatial index: this is what makes "nearest facility" and "detections within
-- 1 km on earlier days" fast at national scale.
CREATE INDEX IF NOT EXISTS idx_events_geom  ON hotspot_events USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_events_date  ON hotspot_events (acquisition_date DESC);
CREATE INDEX IF NOT EXISTS idx_events_time  ON hotspot_events (acquired_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_prod  ON hotspot_events (source_product);
-- Recurrence queries filter by space and time together.
CREATE INDEX IF NOT EXISTS idx_events_space_time
    ON hotspot_events USING GIST (geom, acquisition_date);

-- ---------------------------------------------------------------------------
-- Industrial facilities (OpenStreetMap)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS facilities (
    facility_id     TEXT PRIMARY KEY,
    geom            geography(Point, 4326) NOT NULL,
    name            TEXT,
    category        TEXT NOT NULL,
    category_label  TEXT NOT NULL,
    osm_type        TEXT,
    osm_id          BIGINT,
    tags            JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_facilities_geom ON facilities USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_facilities_cat  ON facilities (category);

-- ---------------------------------------------------------------------------
-- Land-use polygons (OpenStreetMap). Real polygons, so point-in-polygon runs
-- in the database instead of ray-casting in Python.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS land_use (
    id          BIGSERIAL PRIMARY KEY,
    geom        geometry(Polygon, 4326) NOT NULL,
    category    TEXT NOT NULL,
    osm_tag     TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_landuse_geom ON land_use USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_landuse_cat  ON land_use (category);

-- ---------------------------------------------------------------------------
-- Model outputs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS classifications (
    event_id            TEXT PRIMARY KEY REFERENCES hotspot_events(event_id) ON DELETE CASCADE,
    label               TEXT NOT NULL,
    confidence          REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    confidence_level    TEXT NOT NULL CHECK (confidence_level IN ('HIGH', 'MEDIUM', 'LOW')),
    abstained           BOOLEAN NOT NULL DEFAULT FALSE,
    probabilities       JSONB NOT NULL,
    factors             JSONB NOT NULL DEFAULT '[]'::jsonb,
    priority_score      REAL NOT NULL,
    priority_level      TEXT NOT NULL,
    priority_components JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_version       TEXT NOT NULL,
    feature_version     TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_class_label    ON classifications (label);
CREATE INDEX IF NOT EXISTS idx_class_priority ON classifications (priority_score DESC);

CREATE TABLE IF NOT EXISTS model_metadata (
    model_version         TEXT PRIMARY KEY,
    model_name            TEXT NOT NULL,
    algorithm             TEXT NOT NULL,
    feature_version       TEXT NOT NULL,
    training_data_version TEXT NOT NULL,
    label_policy_version  TEXT NOT NULL,
    trained_at            TIMESTAMPTZ NOT NULL,
    hyperparameters       JSONB NOT NULL,
    metrics               JSONB NOT NULL,
    -- Carried in the database too, so the caveat travels with the numbers.
    metrics_caveat        TEXT NOT NULL DEFAULT
        'Metrics measure agreement with the weak-supervision labelling policy on held-out data, not verified real-world accuracy.'
);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id              BIGSERIAL PRIMARY KEY,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    mode            TEXT NOT NULL,
    bbox            geometry(Polygon, 4326),
    products        TEXT[],
    events_ingested INTEGER NOT NULL DEFAULT 0,
    notes           TEXT
);

-- ---------------------------------------------------------------------------
-- Example queries — the Python equivalents these would replace
-- ---------------------------------------------------------------------------

-- Nearest industrial facility to a detection (replaces the SpatialGrid lookup):
--
--   SELECT f.facility_id, f.name, f.category,
--          ST_Distance(e.geom, f.geom) / 1000.0 AS distance_km
--   FROM hotspot_events e
--   CROSS JOIN LATERAL (
--       SELECT * FROM facilities f
--       WHERE ST_DWithin(e.geom, f.geom, 12000)
--       ORDER BY e.geom <-> f.geom
--       LIMIT 1
--   ) f
--   WHERE e.event_id = $1;

-- Recurrence at a source, respecting the no-future-data rule:
--
--   SELECT COUNT(*) AS detections,
--          COUNT(DISTINCT h.acquisition_date) AS distinct_days
--   FROM hotspot_events h, hotspot_events target
--   WHERE target.event_id = $1
--     AND ST_DWithin(h.geom, target.geom, 1000)
--     AND h.acquisition_date <  target.acquisition_date
--     AND h.acquisition_date >= target.acquisition_date - INTERVAL '60 days';

-- Land cover containing a detection:
--
--   SELECT l.category, l.osm_tag
--   FROM land_use l, hotspot_events e
--   WHERE e.event_id = $1
--     AND ST_Contains(l.geom, e.geom::geometry)
--   ORDER BY ST_Area(l.geom) ASC
--   LIMIT 1;

-- Highest-priority industrial candidates in a bounding box:
--
--   SELECT e.event_id, c.label, c.confidence, c.priority_score
--   FROM classifications c
--   JOIN hotspot_events e USING (event_id)
--   WHERE c.label IN ('INDUSTRIAL_FIRE', 'GAS_FLARE_OR_INDUSTRIAL_HEAT')
--     AND ST_Intersects(e.geom, ST_MakeEnvelope($1, $2, $3, $4, 4326)::geography)
--     AND e.acquisition_date >= CURRENT_DATE - INTERVAL '7 days'
--   ORDER BY c.priority_score DESC
--   LIMIT 100;
