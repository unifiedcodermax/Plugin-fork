# Changelog

All notable changes to Planara are recorded here. Versions follow
semver applied to the engine + plugin together — when a sprint
lands across both, the same version covers both.

## [0.2.1] — 2026-06-10

Patch release addressing engine startup reliability and initial authentication setup.

### Added
- Automatic database seeding: on first launch, if no users exist in the local SQLite database, a default admin user is created (`admin` / `password123`).
- Login hint in user interface showing the default local admin credentials.

### Fixed
- Plugin engine supervisor path execution bug: resolve crashes/spawning failures when Planara is installed under directories containing spaces (such as `Application Support`).
- Environment variable sanitization when spawning python engine sidecar, preventing pollution from SketchUp's internal runtime.

## [0.2.0] — 2026-05-17

The persistence + regression-tracking release. `/validate` is now
joined by `/reports` and `/history`, and the SketchUp plugin
surfaces the whole archive flow through its Plugins menu.

### Added — engine
- `POST /reports` and `GET /reports/html` — render an
  `ArchivalReport` (snapshot + response + `generated_at` +
  `rule_pack_version`) without writing to the database.
- `POST /history`, `GET /history`, `GET /history/{id}` and the
  matching `/html` views — persist a validation run as a
  `ValidationReport` row and read it back paginated /
  user-scoped.
- `reporting.diff_reports` + `ReportDiff` model with
  added / removed / changed / unchanged buckets and signed metric
  deltas. Surfaced as `GET /history/{id}/diff`,
  `GET /history/diff?from=&to=`, and the corresponding `/html`
  routes.
- Mumbai rule packs (`v0.1.0` base, `v0.2.0` with CRZ + airport
  overlays).
- Bangalore `v0.3.0` adds airport and `heritage_influence`
  overlays.

### Added — plugin
- `engine_client.rb` history surface: `save_history`,
  `list_history`, `get_history`, `get_history_html`, `auto_diff`,
  `auto_diff_html`, `explicit_diff`, `explicit_diff_html`. New
  `request_raw` transport for the HTML endpoints.
- New menu items: *Save current run*, *Recent runs…*, *Compare
  with last save*, *Open last report in browser*.
- `UI::HistoryDialog` (HtmlDialog) — paginated list of saved
  runs with per-row open + auto-diff actions and a two-row
  picker for pairwise diff.
- `UI::BrowserView` — write engine-rendered HTML to a tempfile
  and open it with `UI.openURL`.
- `Session.last_report_id` — process-scoped id of the most recent
  save, powering "Open last report in browser".
- `test/test_engine_client.rb` — 13 minitest cases stubbing
  `open_http` to pin URL shape, headers, query encoding, raw HTML
  return, and JSON error-envelope translation.

### Changed
- Legacy `SV-Abid/` tree moved to `legacy/SV-Abid/` with a
  README note. Git history retains the prior path.
- Ruff config tightened to a passing subset (E, F, W, I, B, UP,
  SIM, C4); `line-length` raised to 120 to fit inline CSS / wide
  test signatures. Per-file ignores documented in `pyproject.toml`.
- `mypy --strict` now passes on the engine. Shapely is treated
  as untyped at the seam — the only direct importer is
  `geometry/normalize.py`.

### Infrastructure
- GitHub Actions CI: pytest + ruff check + mypy on the engine,
  minitest on the plugin. Python matrix 3.11 / 3.12.

## [0.1.0] — 2026-05-15

Initial hybrid architecture release. `planara_plugin/` (Ruby
inside SketchUp) talks to `planara_engine/` (Python FastAPI
sidecar) over localhost HTTP.

### Added
- Engine: `/health`, `/auth/login`, `/auth/me`, `/validate`.
- Rule packs: Bangalore `v0.1.0` and `v0.2.0` (FSI, setback,
  ground coverage, open space, parking).
- Evaluators for FSI, setback (Shapely distance), ground
  coverage, open space, parking, height.
- Plugin: extension registrar, engine supervisor (spawn +
  healthcheck + stop), login dialog, results dialog, geometry
  extractor (SketchUp → snapshot JSON in meters), ModelObserver
  -driven live validate loop.
- 290+ tests across engine and plugin.
