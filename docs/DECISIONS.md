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

## Phase 2 — demo reliability

- **FIRMS timeout cut from 45 s to 8 s** · the client tries each configured
  product in turn, so 45 s meant a worst case over two minutes before any
  fallback; NASA answers a national query in 2-4 s when it answers at all ·
  reverse via `FIRMS_TIMEOUT_SECONDS` in `.env`.
- **Retries only for timeouts and 5xx** · a rejected key, a 429 and a connection
  error do not improve by asking again, and retrying each across three products
  turned a dead network into a ~20 s wait · reverse in `firms._get`.
- **The product loop stops on a network-level failure** · a timeout tells you
  about the network, not the product; trying the next one buys the same answer
  for another full timeout · reverse in `firms.fetch_area`.
- **New on-disk cache of the last good live fetch** (`livecache.py`) · the
  in-memory analysis cache dies with the process, so a restart on a dead network
  had nothing live to show; this survives restarts, expires after 72 h, and is
  always labelled with its real age · reverse by deleting the module and its
  pipeline call.
- **Explicit Live mode now degrades instead of returning an empty map** · it
  used to answer HTTP 200 with zero events under a "Live NASA FIRMS" label when
  the key was rejected (BASELINE D2) · reverse in `pipeline._acquire_events`.
- **Added a third source state, `cached`, to `DataSourceStatus`** · real NASA
  data read back from disk is neither live nor the frozen archive, and
  collapsing it into either misrepresents the screen · reverse by narrowing the
  Literal back to live|snapshot.
- **Isolated the live disk cache in the `test_store_api` fixture** · adding the
  cache made "survives a total NASA outage" depend on whether a real cache file
  existed on the developer's machine · reverse: remove the monkeypatch.
- **`npm run demo` as the single entry point**, with `demo.sh`, `demo.ps1` and
  `demo.bat` as thin wrappers so the logic cannot drift · reverse by deleting
  `scripts/demo.mjs`.

## Phase 4 — quality gate

- **`npm run smoke` starts its own backend and dashboard on dedicated ports** ·
  the previous smoke test required a server already running and silently failed
  against the wrong one · reverse: `npm run smoke:pipeline` still runs the
  original Python test alone.
- **Vite's dev proxy target is configurable (`FIRETRACE_API_TARGET`)** · lets the
  gate run the whole stack isolated and same-origin, so no CORS allowlist and no
  API host baked into the bundle · reverse: hardcode 8000 again.
- **The basemap tile *count* warns rather than fails; the tile *host* is a hard
  assertion** · openstreetmap.org throttles after the earlier groups' traffic, so
  gating on it would make a green run mean "OSM felt generous today". The host
  check is what catches the CARTO key-required trap · reverse in
  `scripts/checks/browser.mjs`.
- **Accessibility is axe-core, performance is measured paint timings — not
  Lighthouse** · a real axe pass plus real FCP/DCL numbers is more honest than a
  half-configured Lighthouse score, and adds no heavy dependency. Reported as
  what they are, never as "Lighthouse 9x" · reverse by adding Lighthouse.
- **Fake keys in tests are recognised structurally, not allowlisted** · a 32-hex
  string made of one repeated block is a placeholder; this way a new fake in a
  new test needs no scanner update · reverse in `scripts/smoke.mjs`.

## Phase 3 — intelligence integrity

- **Abnormality returns "not assessed" instead of a number when a location has
  fewer than 2 prior detection days** · it was returning 1.0 ("maximally
  unusual") for any location with no history, which hit 70% of detections and
  was mostly archive sparsity, not genuine novelty · reverse by restoring the
  old two-line `abnormality()` in `priority.py`.
- **Unassessable priority components are dropped and the weights renormalised**
  · a component we cannot measure must neither contribute a fabricated value nor
  silently act as a zero · reverse in `compute_priority`.
- **`abnormality_score` (0-100) is a first-class field, separate from
  `model_score` and `operational_priority`** · what it is, how unusual it is and
  how urgently to look are three different questions · reverse by removing it
  from `PriorityResult` and the site payload.
- **Accepted that priority scores fell** (mean 0.4403 → 0.3868, needs-attention
  11 → 8) · the three sites that dropped out were ranked partly on an invented
  novelty claim; a shorter honest queue beats a longer inflated one · reverse by
  reverting the fix.
- **Updated two existing tests that asserted the old behaviour** ·
  `test_no_history_is_neutral` asserted `abnormality() == 0.5`, which encoded
  the defect · reverse: see `git show` for the prior assertions.
- **Did not retrain the model or touch the labels** · the defects were in the
  scoring and presentation layers; changing the label policy would invalidate
  the artefact and every metric with it.


## Pass 2 - Live/Past, notifications, UI

- **"Live" covers fresh, empty and delayed; the honesty moved to the age line** ·
  three different chip words taught a reader to parse vocabulary instead of
  reading a number, and the real risk is stale data looking fresh, not a
  reassuring label · reverse by rendering `provenance.state` as chip text again.
- **Internal provenance states renamed (offline -> delayed, label -> surface)** ·
  the names now say what they are, and an explicit surface means a replay cannot
  land under the Live segment by accident · reverse in `routes._provenance`.
- **Past-data periods are derived from contiguous runs of >= 3 days** · shorter
  runs are noise, and three days is the shortest span in which a persistent
  source can show a repeat · reverse via `timeline.MIN_RUN_DAYS`.
- **A literal `from:to` range must contain real detections or 404** · accepting
  any well-formed span let a link render an empty week as a real period ·
  reverse by dropping `_holds_detections`.
- **Replay safety enforced at notification creation, not per channel** · a
  channel added later cannot forget a check it never sees · reverse by moving
  the `suppress` test into each channel.
- **One notification per site per evaluation, most severe wins** · a detection on
  a facility footprint qualifies as two reasons, and two bells for one event is
  the fatigue the policy exists to prevent · reverse in `_reasons_for`.
- **Browser notifications are opt-in on an explicit click** · asking on page load
  is the fastest way to be permanently blocked · reverse in `NotificationBell`.
- **Esri World Imagery for the satellite layer, terms flagged not verified** ·
  PS R3 asks for imagery and Esri serves keyless and real; its terms for direct
  third-party tile use are not unambiguous, so it is fully attributed and one
  constant disables it · reverse by clearing `BASEMAPS.satellite.url`.
- **Kept OpenStreetMap tiles with CSS desaturation rather than a vector style** ·
  re-verified that CARTO still answers HTTP 200 with an "API KEY REQUIRED" PNG;
  no keyless vector style was verified in time · reverse in `CalmMap.BASEMAPS`.
- **The map fits India's bounds instead of a fixed zoom** · a fixed zoom 5 framed
  half of Asia and crowded the edges with foreign-script labels · reverse by
  restoring `center`/`zoom`.
- **The India outline loads after first paint** · imported statically it was
  69 KB of JSON parsed in the critical path and FCP measured 5.15 s; it is a
  fallback, so it does not belong there · reverse to a static import.
- **GeoPackage written with sqlite3, not GDAL** · a ~100 MB wheel chain would
  break "runs on a laptop with no internet", and GDAL wheels on Windows are the
  commonest install failure in Python GIS; correctness comes from reading the
  file back · reverse by adding fiona/GDAL and rewriting `gis.write_geopackage`.
- **The heat band draws no range where the baseline is unassessed** · an invented
  normal range would be the most misleading pixel on the screen · reverse by
  always drawing a band in `SiteCard.HeatBand`.
- **Inter bundled from node_modules rather than a CDN** · a font fetched over the
  network is missing at a venue with no Wi-Fi · reverse by using a CDN link.
- **Dark theme built but shipped without a toggle** · it follows the system
  setting and has had no design-QA pass, so light stays the default and the demo
  uses light · reverse by adding a toggle after a QA round.
- **Deleted the dead `frontend/src/map.css`** · Pass 1's stylesheet was orphaned
  when every class moved from `m-*` to `fc-*` · reverse with `git show`.
- **Did not build backfill_history, WorldCover or Sentinel-2** · all three are
  data-acquisition work with external dependencies, and the priority order put
  UI, notifications and the gate first; each is recorded honestly in
  `docs/PS_COMPLIANCE.md` rather than quietly skipped.
