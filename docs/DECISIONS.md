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
