# Phase 4 — Migration Strategy & Risk Analysis

## 4.1 Philosophy

The migration is not a translation. The legacy code has wrong
formulas (FSI from bbox, axis-aligned setbacks), a singleton state
hazard, load-time side effects, two parallel boot trees, and no
test coverage. Translating it line-by-line would carry the bugs
forward.

> verbatim from the foundational analysis:
> *"Current numbers are not trustworthy. MVP must rebuild
> correctly, not port."*

So Phase 4 is **architectural separation**, not syntactic
conversion:

- All compliance math leaves Ruby and is **rebuilt** in Python
  against the rule packs.
- Only what *cannot move* stays in Ruby (SketchUp API, observers,
  UI).
- The salvageable parts are the **config data values** (FSI
  limits, setback limits, `rules.json`) and the **observer-driven
  pattern**. Everything else is abandoned in `legacy/`.

---

## 4.2 What stays in Ruby

A short, explicit list. Anything not on it must move.

| Stays | Why |
|---|---|
| `SketchupExtension` registration | SketchUp boot contract — only Ruby. |
| Menu wiring (`UI.menu("Plugins")...`) | Only Ruby. |
| `Sketchup.add_observer`, `model.add_observer` | Only Ruby. |
| `Sketchup::Group` / `ComponentInstance` traversal | Only Ruby — these objects are wire-untranslatable. |
| `model.options["UnitsOptions"]` reads | Only Ruby. |
| `UI::HtmlDialog`, `dialog.execute_script` | Only Ruby — the only built-in UI affordance. |
| `UI.openURL` (open report in browser) | Only Ruby. |
| Net::HTTP, JSON | Stdlib, no gems needed. |
| Geometry extraction logic (groups → polygons) | Has to traverse `Sketchup::*` objects. |
| Unit conversion (inches/mm/feet → meters) | One conversion point at the wire boundary. |
| Engine lifecycle (spawn/health-check/stop) | The plugin is the only thing in the user's process — it has to manage the rest. |
| Session state (JWT, project context, last_report_id) | Lives next to the user. |

---

## 4.3 What moves to Python

Everything else. Specifically:

| Moves | New location |
|---|---|
| FSI calculation | `compliance/fsi.py` |
| Setback calculation | `compliance/setback.py` |
| Coverage calculation | `compliance/coverage.py` |
| Open space calculation | `compliance/coverage.py` (companion) |
| Parking calculation | `compliance/parking.py` |
| Height check | `compliance/height.py` |
| FSI/setback config tables | `rules/packs/bangalore-*.json` |
| `rules.json` semantics | Future evaluators (road-width premium, height-tiered setbacks, per-use parking forms) |
| Reporting / message rendering | `reporting/html_renderer.py` |
| User store, password hashing, JWT | `auth/` |
| Persistence | `persistence/` |
| Rule selection / dispatch | `engine/rule_engine.py` |
| Geometry math (polygon area, distance, offset) | `geometry/operations.py` (Shapely) |

---

## 4.4 What is fundamentally untranslatable

> verbatim:
> *"What's fundamentally untranslatable: `Sketchup::*` API calls.
> Must stay in Ruby. They run inside SketchUp's embedded Ruby VM
> and have no Python equivalent."*

This is the floor of what Ruby has to do. Everything in §4.2 is
above this floor.

---

## 4.5 Risk register

| # | Risk | Severity | Mitigation | Owner |
|---|---|---|---|---|
| R1 | Business logic is wrong (FSI from bbox, axis-aligned setback) | Critical | Rebuild from `rules.json` semantics, not port. Pin values via test. | Phase 2 + Sprint 3 |
| R2 | SketchUp is Ruby-only | Critical | Hybrid architecture (Option C). | Phase 3 §3.1 |
| R3 | Geometry extraction needs Ruby API | High | Thin Ruby `Geometry::Extractor`; JSON over wire. | Sprint 3 |
| R4 | Geometry contract drift (Ruby JSON ↔ Python Pydantic) | High | Pydantic = source of truth; contract tests both sides; 12 minitest cases pin wire format. | Sprint 6.6 |
| R5 | Singleton state race (`DataPoints`) | High | Replaced with immutable `Snapshot` per request. | Phase 3 §3.4 |
| R6 | Unit conversion bugs (hand-coded `/ 39.3701`) | High | Single converter at Ruby boundary: `geometry/units.rb`. All wire numbers in meters. | Sprint 3 |
| R7 | `rules.json` semantics undocumented (`InheritsFrom`, road-width premium, height bands) | Medium | Treat `rules.json` as authoritative spec in Phase 2. Roadmap evaluators per concern. | Phase 2 §2.3, §2.4 |
| R8 | Two parallel boot paths | Medium | Single new entry point (`planara_plugin/loader.rb`). Legacy preserved unchanged. | Sprint 1 |
| R9 | No tests, no CI, no lint | Medium | pytest + minitest + ruff + mypy + GitHub Actions added in 0.2.0. | Sprint 11 |
| R10 | Engine lifecycle instability (port conflicts, crash loops) | Medium | `engine_supervisor.rb`: spawn / health-check / restart-on-fail / SIGTERM-then-SIGKILL. | Sprint 1 |
| R11 | Schema evolution breaks older plugins | Medium | `schema_version` defaults to `"1.0"`; engine warns on mismatch rather than rejecting. | Sprint 6.1 |
| R12 | Auth leaks (timing, message) | Medium | Identical message + timing-balanced bcrypt for user-not-found vs wrong-password. Test enforces. | Sprint 2 |
| R13 | `password_hash` leaks via response | Medium | Explicit `MeResponse` Pydantic boundary; integration test asserts absence. | Sprint 2 |
| R14 | User A reads User B's history | Medium | `user_id` filter on every repo read; "not yours" → 404 (same as "not exists"). | Sprint 9 |
| R15 | `/history/diff` parsed as `/history/{id}` UUID | Low | Route ordering: `/history/diff` registered first. | Sprint 10 |
| R16 | Pack version sort lexicographic, breaks at v0.10 | Low | Documented; semver sort deferred. | Sprint 10 (open) |
| R17 | Sidecar zombie processes if SketchUp crashes | Low | Health-check on startup discovers orphans and adopts/replaces. | Sprint 1 |

---

## 4.5b Detailed mitigation for the top three risks

### R1 — Wrong business logic

The legacy formulas are not subtly wrong — they are categorically
wrong. FSI from bounding box is a hack; axis-aligned setback
assumes a centered, rectangular plot.

**Mitigation discipline:**

1. Phase 2 designs the **correct** formulas from `rules.json`
   semantics, not from legacy code.
2. Sprint 3 ships evaluators with **pinned tests** against
   manually-computed values (e.g. CBD/Residential 18×18 footprint
   on 20×20 plot → coverage 81 %).
3. Legacy `legacy/SV-Abid/core/calculations.rb` and
   `core/abid_setback.rb` are **not** referenced from the new
   code. Their output is not trusted as a baseline.

### R4 — Geometry contract drift

The wire is JSON, untyped. Without discipline, the Ruby extractor
and the Python Pydantic models will drift.

**Mitigation discipline:**

1. **Pydantic is the source of truth.** Every wire field is a
   Pydantic field. Tests on the engine pin the expected shape.
2. **Ruby tests pin the same shape.** Sprint 6.6 added 12
   minitest cases that snapshot known SketchUp models and assert
   exact JSON output.
3. **Schema versioning at the snapshot level**
   (`schema_version: "1.0"`). Forward-compatible by default
   (engine warns, doesn't reject, on minor mismatch).

### R6 — Unit conversion

Legacy code has `/ 39.3701` (inches→meters) sprinkled across
files. The same number, repeated, is a refactoring landmine.

**Mitigation discipline:**

1. **One conversion point**: `planara_plugin/planara/geometry/units.rb`.
2. **Conversion happens at the wire boundary** in `Extractor`.
3. **The engine never sees inches**. Pydantic refuses negative
   areas and out-of-bounds floats but it is not on the converter
   side of the line.
4. **Plugin tests pin the converter** (`test/test_units.rb`).

---

## 4.6 Migration order

The order is dictated by dependency: every later step depends on
the earlier ones not being changed underneath it.

### Original 6-sprint plan (ROLE prompt, Phase 5)

| Sprint | Scope |
|---|---|
| S1 | Repo restructure, plugin boot, engine skeleton |
| S2 | Auth + geometry extraction |
| S3 | FSI/FAR + setback engines |
| S4 | Open space + parking |
| S5 | Zoning engine + overlays |
| S6 | Reporting, tests, PDF fixtures |

### Actual execution (extended to S13)

| Sprint | Scope | Why split from the original plan |
|---|---|---|
| S1 | FastAPI skeleton + Ruby thin shell + `/health` | Foundation only — no business logic yet |
| S2 | SQLite/User + bcrypt + JWT + `/auth/login` + login HtmlDialog | Auth carved out as its own sprint (was bundled with geometry) |
| S3 | Pydantic domain + Shapely geometry + rule schema/loader + FSI + Bangalore v0.1.0 + `/validate` + Ruby `Geometry::Extractor` | The biggest sprint — everything end-to-end for one evaluator |
| S4 | Setback + coverage + open space + parking + Bangalore v0.2.0 (27 rules) | Four more evaluators on the same chassis |
| S5 | Overlays domain + height evaluator + Bangalore v0.3.0 (airport, heritage_influence) + Ruby `DataPoints[:overlays]` | Zoning + overlays as a single concept |
| S6 | `schema_version` + extractor refactor + `Session.project` + `LiveValidator` (500 ms debounce) + Results HtmlDialog (replaces messagebox) | The plugin gets its real live-validation loop |
| S7 | Mumbai pack (proves city-isolation contract) | Validates that "new city = data only" |
| S8 | Reporting: HTML + `ArchivalReport` JSON, `Accept`-based content negotiation | Reports surface |
| S9 | `ValidationReport` SQLModel + `/history` routes | Persistence layer |
| S10 | `diff_reports` + `/history/diff` + diff HTML renderer | Regression tracking |
| S11 | Plugin-side wiring of history/diff: menu items, `HistoryDialog`, `BrowserView` | Surface the persistence in the UI |
| S12 | Cleanup + CI + ruff/mypy green + CHANGELOG → 0.2.0 | Ship-readiness |
| S13 | `Project` entity, FK from `ValidationReport`, plugin project picker | The auto-diff context (`city, classification, zone`) breaks the moment a user has two designs with the same context. Real `Project` fixes it. |

> verbatim from the assistant during S13 planning:
> *"The auto-diff anchor `(city, classification, zone)` breaks the
> moment a user has two Bangalore/CBD/Residential designs. A real
> `Project` row solves it and unlocks better history navigation."*

S13 is currently in flight (uncommitted): `routes_projects.py`,
`persistence/projects.py`, `domain/project_context.py` (renamed
from `project.py`), `ui/project_picker.rb`, and the matching tests.

---

## 4.7 What was deferred (and why)

| Item | Effort | Reason for deferral |
|---|---|---|
| PDF report variant (WeasyPrint) | 1 sprint | Out of MVP. HTML covers the surface. |
| More cities (Delhi DCR, Chennai CMDA) | 1 sprint each | Mumbai already proves the contract — adding more is incremental. |
| Fire safety / accessibility evaluators | 1–2 sprints | Not in the MVP feature list. |
| Slot-dimension validation (parking) | 1 sprint | The MVP counts slots; validating slot polygons is a future evaluator. |
| Heritage facade preservation | 1 sprint | Out of MVP. |
| In-model violation visualization (highlight non-compliant edges back in SketchUp) | 2–3 sprints | Biggest UX win, biggest engineering. Deferred. |
| Cloud deployment | 2 sprints | Architecture supports it; needs ops (Docker, hosted DB, env config). |
| Audit log (who-validated-what-when) | 1 sprint | Regulatory traceability — useful but not gating MVP. |
| DWG / IFC import | 3+ sprints | Explicit non-goal in `ARCHITECTURE.md`. |
| Per-unit parking forms (hotels/hospitals/theatres) | 1 sprint | Listed in `rules.json` but use-keyed ratio covers MVP. |
| Height-tiered setbacks (high-rise growing setbacks) | 1 sprint | `rules.json` has this; future evaluator. |
| FAR road-width premiums | 1 sprint | `Project.road_widths_m` already on the wire — evaluator is the only missing piece. |
| OCR of municipal PDFs | 2+ sprints | Adapters slot reserved; out of MVP. |
| GIS integration | 2+ sprints | Overlays today are strings; spatial test against polygons is future work. |
| Service-area exclusions in FSI | 1 sprint | Requires sub-polygon (footprint with tagged voids). Out of MVP. |
| Cantilever-aware coverage per floor | 1 sprint | Ground-floor footprint is sufficient for MVP. |

---

## 4.8 Git & commit strategy

### Branch model

> verbatim from locked decisions:
> *"Hybrid architecture, push-to-main per commit, local auth with
> JWT."*

- `main` is always green.
- Small commits, descriptive subjects, push per commit.
- No long-lived feature branches for MVP work — the codebase is
  small enough and one developer is committing.
- For future multi-contributor work, short-lived feature branches
  (`feat/...`, `chore/...`) are fine.

### Commit conventions (observed in actual history)

```
feat(engine): add setback evaluator using Shapely
feat(plugin): /history client + Recent runs UI + diff in browser
chore(engine): ruff + mypy go green; tighten configs to passing subset
docs+ci: 0.2.0 — history surface, CHANGELOG, GitHub Actions
```

- Type prefix (`feat`, `chore`, `docs`, `fix`).
- Scope in parens (`engine`, `plugin`, `engine/reporting`, …).
- Imperative subject under ~70 chars.
- Body explains why; commits should compile/test independently.

### Versioning

Engine + plugin share a semver. Sprints that touch both land
under one version bump:

- `0.1.0` — initial hybrid architecture (S1–S6).
- `0.2.0` — history + diff (S7–S12).
- `0.3.0` (next) — projects entity (S13).

---

## 4.9 Auth MVP decision

> verbatim:
> *"Local session auth, SQLite-backed users, bcrypt password
> hashing, JWT issued by the engine, auto-seeded admin on first
> run."*

What this **is**:

- A single shared SQLite database under the engine's data dir.
- Bcrypt-hashed passwords with random salt.
- JWT signed HS256 with a per-install secret (generated on first
  boot, persisted).
- No-leak login: same message + same timing on `user_not_found`
  vs `wrong_password`.
- `MeResponse` boundary: `password_hash` never crosses the wire.

What this is **not**:

- Not OAuth.
- Not SSO.
- Not multi-tenant.
- Not LDAP.
- Not license-based.
- Not cloud sync.

These are explicit non-goals, deferred to a future "auth-v2"
sprint when the user count warrants it.

---

## 4.10 Testing strategy

Designed up-front so the migration has a safety net.

### Engine

- **Unit tests** per evaluator (`tests/unit/test_fsi.py`,
  `test_setback.py`, `test_coverage.py`, `test_parking.py`,
  `test_height.py`).
- **Pack tests** (`test_bangalore_pack.py`, `test_mumbai_pack.py`,
  `test_packs_smoke.py`) — load each pack, evaluate against a
  known snapshot, assert the violation set.
- **Engine tests** (`test_engine.py`) — rule selection +
  applicability + dispatch.
- **Rules / loader / schema tests** — duplicate id guards,
  bad-JSON guards.
- **Domain model tests** (`test_domain_models.py`) — Pydantic
  invariants.
- **Geometry tests** (`test_geometry.py`) — Shapely wrappers.
- **Auth tests** (`test_auth_service.py`, `test_passwords.py`,
  `test_tokens.py`) — including the no-leak invariant.
- **Persistence tests** (`test_persistence.py`,
  `test_persistence_reports.py`, `test_reports_repository.py`,
  `test_projects_repository.py`).
- **Reporting / diff tests** (`test_reporting.py`,
  `test_diff.py`).
- **Integration tests** (`tests/integration/`) using FastAPI
  TestClient — `test_auth_routes.py`, `test_validate.py`,
  `test_validate_mumbai.py`, `test_reports.py`, `test_history.py`,
  `test_projects.py`, `test_health.py`.

### Plugin

- **Geometry extraction** (`test/test_extractor.rb`) — feed mock
  `Sketchup::*` objects, assert snapshot shape.
- **Units** (`test/test_units.rb`) — every conversion factor.
- **Engine client** (`test/test_engine_client.rb`) — 13 cases
  stubbing `open_http`, pinning URL shape, headers, query
  encoding, raw HTML return, JSON error-envelope translation.

### CI

- GitHub Actions: pytest + ruff + `mypy --strict` on engine,
  minitest on plugin.
- Python matrix 3.11 / 3.12.

---

## 4.11 Documentation strategy

Designed (this Phase 4) but only partially executed during sprints:

| Doc | Status | Sprint |
|---|---|---|
| `ARCHITECTURE.md` (target) | Shipped | Sprint 1 |
| `CHANGELOG.md` | Shipped per release | Sprint 12 onwards |
| `CLAUDE.md` (legacy reference) | Shipped | Pre-S1 |
| `legacy/README.md` | Shipped | Sprint 3 (when SV-Abid was moved into legacy/) |
| `planara_engine/README.md` | Shipped | Sprint 1 |
| `planara_plugin/README.md` | Shipped | Sprint 1 |
| Phase 1–4 design docs (this folder) | Backfilled post-S13 | — |

The Phase 1–4 design write-ups were deferred during execution
because the architecture decisions were locked in conversation,
not yet on disk. This folder closes that gap.

---

## 4.12 What this phase produced

By the end of Phase 4, the following were locked and Sprint 1
could begin:

1. The **explicit cut** between Ruby and Python (§4.2 / §4.3),
   with the untranslatable surface named (§4.4).
2. The **risk register** (§4.5) with mitigation owners.
3. The **migration order** (§4.6) — 6 planned sprints, executed
   as 13.
4. The **deferred backlog** (§4.7) with rationale per item.
5. The **git / commit strategy** (§4.8).
6. The **auth MVP decision** (§4.9) with explicit non-goals.
7. The **testing strategy** (§4.10) on both sides.
8. The **documentation strategy** (§4.11), with this folder as
   the post-hoc backfill.

That made it safe to start writing code without re-litigating any
of the above.
