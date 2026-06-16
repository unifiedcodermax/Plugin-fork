# Changelog

All notable changes to Planara are recorded here. Versions follow
semver applied to the engine + plugin together — when a sprint
lands across both, the same version covers both.
## [0.6.1] — 2026-06-16

Feature release improving real-time live check behavior and adding FSI warnings.

### Added — plugin
- Added live, mid-gesture FSI approximation check to the `InDesignObserver`. Architects are now warned instantly if their Push/Pull action causes the building to exceed the maximum FSI.

### Fixed — plugin
- **Multiple outputs**: Grouped individual `room_height` warnings into a single, concise summary line in the live warning banner.
- **Vanishing banner**: Fixed a bug where `check_building_height` would short-circuit when height stopped changing, causing the amber warning banner to clear prematurely when pausing mid-gesture.

## [0.6.0] — 2026-06-16

Feature release introducing green building initiative suggestions for FSI violations.

### Added — engine
- Added `hint` field to `Violation` model and `hint_template` to `Rule` schema. The engine evaluates these templates when a rule is violated.
- Configured all non-industrial Bangalore FSI rules to suggest participation in the Green Building Initiative program (solar panels or wet waste composting) when FSI limits are exceeded.

### Added — plugin
- Conditionally render actionable hints below violation messages in a green block with a lightbulb icon.

## [0.4.0] — 2026-06-16

Feature release introducing real-time, mid-gesture compliance feedback.

### Added — plugin
- Added `InDesignObserver` to capture mid-gesture entity modifications.
- Introduced `LimitsCache` to store authoritative rule limits on the Ruby side.
- Wired up real-time feedback with an amber status banner showing in-design warnings during active modeling.

## [0.3.2] — 2026-06-14

Fixes version syncing issue across pyproject.toml and __init__.py causing releases to generate assets with an outdated version tag.

## [0.3.1] — 2026-06-13

Bug fix release to resolve strict type checking errors in the compliance engine.

### Fixed
- Fixed mypy `no-redef` error on variable `computed` in `room_height.py`.


## [0.2.5] — 2026-06-12

Bug fix release for the live compliance dialog.

### Fixed
- **UI Race Condition:** The results dialog now correctly hooks into the native `HtmlDialog` close event via `set_on_closed` and uses `reset_dialog_ref` to clean up internal references, preventing the application from hanging on "Waiting for first validation..." when reopened.
- **Session State:** Closing the live compliance dialog now stops the background live validation loop and clears `Session.project` metadata. This forces the plugin to re-prompt for project details (City, Classification, Zone) on the next run, ensuring a fresh session.

## [0.2.4] — 2026-06-11

Feature release eliminating manual setup and surfacing live validation errors.

### Added
- Auto-discovery for Plot and Floor groups. When opening an existing SketchUp model with unnamed groups, the plugin uses heuristics (largest ground-level face, distinct Z-levels) to identify the plot and floors automatically, and renames them to lock in the fast path for subsequent runs.
- Live error surfacing: Extraction and engine errors now display as a persistent, actionable banner at the top of the Results panel, giving the architect immediate feedback during live editing without blocking popups.
- Auto-validation on file open: Pre-built `.skp` files are evaluated immediately upon opening if the user is authenticated.

## [0.2.3] — 2026-06-10

Windows compatibility patch — resolves all known issues preventing
the plugin + engine from running on Windows.

### Fixed — engine
- SQLite database connection URL now uses POSIX-style forward slashes on Windows, preventing path misinterpretation by SQLAlchemy's SQLite driver.

### Fixed — plugin
- Engine supervisor process spawning: use `new_pgroup` instead of POSIX-only `pgroup` on Windows; send `KILL` signal directly since `TERM` is unsupported; replace `Process.getpgid` with `Process.kill(0, pid)` for process liveness checks.
- `BrowserView` file:// URL builder: normalize backslashes to forward slashes, prepend leading `/` for Windows drive paths, and encode spaces as `%20` instead of `+`.

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
