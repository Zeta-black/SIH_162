# Decisions log

One line each: decision · reason · how to reverse.
Newest at the bottom.

## Phase 0 — recon

- **Kept the backend, rebuilt the frontend shell** · backend is sound and
  unusually honest (provenance, abstention, "unavailable" already first-class);
  the UI is what the mentor flagged · reverse by `git checkout pre-sih-final -- frontend/`.
- **Moved the leaked FIRMS key from `.env.example` into gitignored `.env`** ·
  the real key was pasted into the committed template; verified absent from git
  history, so no rewrite needed · reverse: none wanted. Key should still be rotated by a human.
- **Tagged `pre-sih-final` at `ec79406` and branched `sih-final`** · known-good
  checkpoint before any change · reverse by `git checkout pre-sih-final`.
- **Added Playwright as a root devDependency** · Phase 4 requires a real browser
  test and screenshots; dev-only, no runtime dependency · reverse by
  `npm uninstall playwright`.
- **Did not treat `docs/ROADMAP_v2.md` as input** · the file does not exist in
  this repo; proceeding from the brief's summary of it · reverse: add the file.

## Phase 1 — the clean map

- **Map is now `/`; the seven analyst pages moved to `/analytics/*`** · the
  landing screen was a KPI wall with no map at all · reverse by swapping the
  routes in `frontend/src/Root.jsx`.
- **Rejected the brief's CARTO Voyager basemap; kept OpenStreetMap tiles with a
  CSS filter** · verified 2026-10-25 that CARTO's keyless raster tiles return
  HTTP 200 with a 2049-byte "API KEY REQUIRED" PNG, which no health check can
  detect · reverse by changing `TILE_URL` in `CalmMap.jsx`.
- **New `/api/map` serves the whole screen in one request** · the summary, the
  markers and the provenance chip cannot then describe different snapshots;
  also drops the per-event duplication of `model`+`disclaimer` (1.46 MB → 583 KB)
  · reverse: the frontend can fall back to `/api/hotspots` + `/api/events`.
- **Four-word display vocabulary in `taxonomy.py`, mapped down from the internal
  states** · a safety officer should not need a glossary; the finer-grained
  fields stay on the event for the drawer · reverse by deleting the
  `STATUS_*` block and the `verdict` service.
- **Abstention outranks priority when choosing a display status** · if the model
  declined to name a class, FIRETRACE must not then assert the event needs
  attention · reverse in `verdict.display_status`.
- **No "N times the facility's normal range" claims yet** · that needs a
  validated per-facility baseline and `priority.abnormality` is not one (see
  BASELINE D1). Claims are made only from measured persistence until Phase 3
  fixes it · reverse once the baseline is trustworthy.
- **Site search covers OSM facility names only, not place names** · there is no
  geocoder, and a city search that knew six cities would look broken; the
  placeholder and the empty state both say so · reverse by adding a gazetteer.
- **Unnamed sites are titled by coordinates** · naming them after their class
  produced 150 identical "Unclassified" rows · reverse in `routes._coord_title`.
- **The map frames the detections, not the query bbox** · fitting the FIRMS box
  (6.5N-36N) is correctly zoom 4 at 1366x768, which puts Arabia and Indonesia
  on screen; it also stops the map implying coverage we do not have · reverse in
  `CalmMap` `fitRef`.
