# Post-college / Grand Finale backlog

This list is intentionally deferred to protect college-round stability. None of
these items should be implemented from the current weak-policy labels alone.

## Scientific validation

- Collect independently verified industrial-fire, flare, agricultural-burn and
  vegetation-fire labels.
- Define a versioned, evidence-driven operational/source taxonomy after label review.
- Add temporal, geographic, facility/event-level, and prospective evaluation.
- Calibrate model scores and report calibration/abstention behavior.
- Add hard-negative evaluation for vegetation near industry and persistent non-flare heat.

## Data and geospatial coverage

- Add a validated satellite land-cover layer behind the current provider interface.
- Improve OSM facility geometry/context and document coverage gaps by region.
- Expand geographic and seasonal coverage; reduce product imbalance.
- Add corroborating datasets only after provenance and licensing review.

## Platform hardening

- Perform realistic independent 10k+ event benchmarking and load testing.
- Add scheduled ingestion, deployment monitoring, backups, and production-grade database work.
- Consider PostGIS deployment and alert integrations after threat-model and operations review.
- Evaluate advanced models only after independently labelled baselines exist.
