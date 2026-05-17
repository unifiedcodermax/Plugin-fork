# Planara Plugin — Phase 1 to Phase 4

## Architecture & Migration Documentation

---

## Overview

This document captures the architectural thinking, reverse-engineering
analysis, migration strategy, and system-design decisions that were
made **before** Sprint execution began.

The purpose of this document is to:

- Record the reasoning behind the chosen architecture.
- Preserve migration decisions.
- Define system boundaries.
- Define plugin responsibilities.
- Define Python engine responsibilities.
- Establish long-term scalability direction.
- Create a foundation for future contributors.

### Folder proposal

Recommended repository structure for the documentation set:

```
docs/
  phase-1-to-4-architecture.md   ← this file (consolidated)
  phase-1-reverse-engineering.md ← future split
  phase-2-domain-analysis.md     ← future split
  phase-3-python-architecture.md ← future split
  phase-4-migration-strategy.md  ← future split
  diagrams/                      ← rendered architecture diagrams
```

For now this consolidated document contains all Phase 1–4 work. It
can be split into the per-phase files above as the documentation
matures.

Companion documents already in the repo:

- `ARCHITECTURE.md` — the target architecture (what was built).
- `CHANGELOG.md` — release-level record of what landed per sprint.
- `CLAUDE.md` — narrative of the legacy Ruby prototype.
- `legacy/README.md` — context on the preserved prototype tree.

---

## PHASE 1 — REVERSE ENGINEERING & SYSTEM ANALYSIS

### 1.1 Existing system understanding

The starting codebase was a Ruby-based SketchUp plugin
(*"Abid Building by laws (Bangalore)"*) for building-byelaw
validation, now preserved under `legacy/SV-Abid/`.

Primary observed responsibilities:

- SketchUp plugin lifecycle.
- Building geometry extraction.
- Compliance calculations (FSI, setback, height).
- Rule / config loading.
- UI integration via `UI.inputbox` and `HtmlDialog`.
- Municipal validation logic for Bangalore zoning.

The existing codebase contained:

- Ruby plugin entry points (`legacy/SV-Abid.rb`, `main.rb`,
  `abid_start.rb`).
- Calculation modules (`core/calculations.rb`, `core/fsi_logic.rb`).
- Configuration files (`config/fsi-config.json`,
  `config/setback-config.json`, `config/rules.json`).
- SketchUp API integrations (observers, model/entity access).
- Compliance formulas (FAR, ground coverage, parking).
- Existing rule mappings keyed by `(classification, zone)`.

### 1.2 Existing architectural observations

#### Strong reusable assets

**Configuration files.** The JSON configs are highly reusable. They
become, in the new design:

- municipality rule packs (`planara_engine/rules/packs/*.json`),
- validation schemas (Pydantic models in `rules/schema.py`),
- configurable compliance rules selected by city + classification +
  zone.

Examples of reusable rule data:

- FSI / FAR limits.
- Setback tables.
- Parking ratios.
- Zoning mappings.
- Open-space rules.

**Existing business logic.** The legacy formulas are relatively
portable:

- FAR calculations.
- Ground coverage calculations.
- Parking requirement formulas.
- Setback validation logic.

These migrated cleanly to Python services under `compliance/`.

#### High-risk areas

**SketchUp runtime coupling.** The legacy plugin is tightly coupled
to SketchUp runtime APIs:

- Entity access (`Sketchup::Entities`).
- Model traversal (`Sketchup.active_model`).
- Observers (`AppObserver`, `ModelObserver`, `EntitiesObserver`).
- Geometry extraction.
- UI callbacks.

This logic **cannot** be fully migrated to Python because SketchUp
officially supports Ruby plugins only.

**Dynamic Ruby risks** observed in legacy code:

- Global state (`DataPoints` singleton with `@data_store` hash).
- Runtime mutation (`DataPoints.set(:key, val)` from anywhere).
- Dynamic loading (`require_relative` with path-casing hazards).
- Callback-heavy flows (observer fan-out without ordering guarantees).
- Hidden execution order (side effects at file load time —
  `helpers/hash_utils.rb` triggers an `inputbox` on require).

These must be stabilized during migration: replaced with typed
DTOs, immutable snapshots, and explicit data flow.

### 1.3 Existing execution flow (observed)

```
SketchUp menu click
  └─ SV_Abid.init_plugin
      ├─ UIInput.show_input_dialog          (classification, zone, area)
      ├─ DataPoints.getFSILimit             (reads fsi-config.json)
      ├─ DataPoints.getSetbackLimit         (reads setback-config.json)
      ├─ AppObserver / ModelObserver attached
      └─ Calculations.update_calculations
          ├─ calculate_model_height         (bounding box → floors)
          ├─ derive built-up area + FAR
          └─ FSILogic.check_fsi_compliance
              ├─ UIDisplay.refresh_display  (inline HtmlDialog)
              └─ UI.messagebox on violation

On model edit:
  ModelObserver#onTransactionCommit → update_calculations
  (onTransactionEnd path is broken — calls method without `model` arg)
```

### 1.4 Existing plugin responsibilities

Current Ruby responsibilities (all in one runtime):

- SketchUp integration.
- Geometry extraction.
- UI interactions.
- Validation triggering.
- Calculations.
- Reporting.

### 1.5 Architectural problem identified

The legacy architecture mixes, inside one Ruby runtime:

- UI logic.
- SketchUp APIs.
- Compliance logic.
- Geometry logic.
- Rule engine logic.

This creates:

- Difficult testing — no test runner, no fixtures.
- Hard scalability — single-process, single-city.
- Maintenance complexity — coupled state singleton.
- Poor extensibility — adding Mumbai means forking files.

### 1.6 Core architectural decision

The system is split into two layers:

**Ruby layer** — responsible only for:

- SketchUp integration.
- Geometry extraction.
- UI.
- Model observers.
- IPC communication with the engine.

**Python layer** — responsible for:

- Compliance engine.
- Calculations.
- Zoning.
- Reporting.
- Validation.
- Rule engine.
- Future AI / OCR / GIS systems.

---

## PHASE 2 — DOMAIN & COMPLIANCE ANALYSIS

### 2.1 Problem domain

The product is a **Building Compliance Validation Platform**.

Primary domain:

- Municipal building byelaws.
- Zoning validation.
- Urban-planning compliance.
- Architectural regulation validation.

### 2.2 MVP feature analysis

#### Login system

Purpose:

- User authentication.
- Future licensing.
- Organization access.
- Auditability of who ran what compliance check.

Recommended MVP:

- Local session auth.
- SQLite-backed users table.
- Hashed credentials (bcrypt).
- Auto-seeded admin on first run.

Future:

- License-based activation.
- Organization accounts.
- Cloud sync.

### 2.3 FAR / FSI validation

**Purpose** — validate whether total built-up area exceeds permissible
limits for the plot's classification and zone.

**Inputs:**

- Plot area.
- Floor areas (sum across levels).
- Zoning category.
- Municipal rule pack (selected by city + classification + zone).

**Formula:**

```
FSI = total_built_up_area / plot_area
ok  = FSI ≤ max_fsi(city, classification, zone)
```

**Risks / edge cases:**

- Exclusions handling (basements, mezzanines).
- Parking exemptions.
- Balcony rules (counted vs. excluded).
- Service area exclusions (lifts, shafts, common areas).

**Recommended architecture:** Python rule-engine service. Each rule
declares an `evaluator` (`fsi_limit`) and `params` (`max_fsi`).

### 2.4 Setback validation

**Purpose** — validate mandatory distances between the building and
plot boundaries.

**Inputs:**

- Plot polygon.
- Building footprint polygon.
- Road width (front).
- Building height.
- Zoning category.

**Geometry requirements:**

- Polygon offsets (inward buffer of plot polygon).
- Minimum distance calculations (footprint → plot edge).
- Directional validation (front / rear / sides).

**Recommended libraries:**

- Shapely (chosen — used in `geometry/operations.py`).
- GeoPandas (future, for multi-plot or GIS overlays).

### 2.5 Open space / landscape validation

**Purpose** — validate that minimum required open spaces are
preserved on the plot.

**Inputs:**

- Plot area.
- Building footprint.
- Landscaped area.

**Risks / edge cases:**

- Irregular plots (non-convex, holes).
- Multi-building plots.
- Shared open areas across adjacent plots.

### 2.6 Ground-coverage validation

**Purpose** — validate maximum permissible footprint occupancy.

**Formula:**

```
coverage_pct = (footprint_area / plot_area) × 100
ok           = coverage_pct ≤ max_coverage_pct
```

**Requirements:**

- Accurate footprint extraction from SketchUp geometry.
- Polygon area calculations on the 2-D projection.

### 2.7 Parking validation

**Purpose** — validate required parking slots given the building use
and area.

**Inputs:**

- Building use (residential, commercial, mixed).
- Built-up area.
- Zoning.
- Municipal rule tables.

**Complexity:** parking rules are typically:

- Use-specific (1 slot per N m² differs by use).
- Area-dependent (tiered: small builds < threshold are exempt).
- Mixed-use aware.
- Dynamically changing across municipalities.

Therefore parking is **rule-engine-driven**, not hard-coded.

### 2.8 Zone classification

**Purpose** — determine applicable compliance overlays for a plot.

**Future requirements:**

- GIS integration.
- Zoning overlays (heritage influence, airport, CRZ).
- Airport-influence zones (height caps near runways).
- Heritage buffers.
- Environmental overlays.

**Future scalability need:** this module strongly benefits from the
Python geospatial ecosystem (Shapely, GeoPandas, Fiona, Rasterio).

### 2.9 Future PDF & diagram validation

Future inputs:

- Compliance PDFs.
- Architectural diagrams.
- Scanned municipal rules.

This justifies Python adoption because of:

- OCR libraries (`pytesseract`, `pdfplumber`).
- NLP tooling (`spacy`, `transformers`).
- AI integrations (Anthropic / OpenAI SDKs).
- Document parsing ecosystem.

A slot for this work exists at `planara_engine/adapters/`.

---

## PHASE 3 — PYTHON ARCHITECTURE DESIGN

### 3.1 Chosen architecture

**Final decision: Hybrid Architecture.**

- Thin Ruby SketchUp plugin (`planara_plugin/`).
- Python FastAPI sidecar engine (`planara_engine/`).

### 3.2 Why hybrid architecture won

**Constraints:**

- SketchUp officially supports Ruby plugins only.
- No official Python plugin runtime exists for SketchUp.

Therefore:

- Ruby **must** remain inside the SketchUp process.
- Python **must** run as a separate external process.

The hybrid model satisfies both constraints while pushing
business logic into the better-tooled runtime.

### 3.3 Final system architecture

```
┌─────────────────────── SketchUp process ───────────────────────┐
│                                                                 │
│  planara_plugin/  (Ruby, thin shell)                            │
│    boot.rb · observers/ · geometry/extractor.rb · ui/           │
│    engine_supervisor.rb · engine_client.rb · session.rb         │
│                                                                 │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTP/JSON over localhost
┌──────────────────────────────▼──────────────────────────────────┐
│                                                                 │
│  planara_engine/  (Python 3.11+, FastAPI sidecar)               │
│    api/ · auth/ · domain/ · rules/ · engine/ ·                  │
│    compliance/ · geometry/ · reporting/ · persistence/ ·        │
│    adapters/ · core/                                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.4 Ruby layer responsibilities

The Ruby layer contains only:

- Toolbar / menu registration.
- SketchUp observers.
- Geometry extraction.
- Model access.
- UI dialogs.
- API communication with the engine.
- Local engine lifecycle (spawn / health-check / stop).

Business logic must **not** remain in Ruby.

### 3.5 Python layer responsibilities

The Python layer owns:

- FAR engine.
- Setback engine.
- Parking engine.
- Zoning engine.
- Reporting (HTML / JSON / diff).
- Rule engine.
- Future OCR.
- Future AI.
- Future GIS.

### 3.6 Recommended Python stack

**API layer:** FastAPI. Chosen because it is fast, typed, async-ready,
produces clean APIs, generates OpenAPI docs automatically, and is
friendly for both local IPC and future remote deployment.

**Validation:** Pydantic. Used for:

- Geometry DTOs.
- Validation request / response schemas.
- Rule schemas.

**Database:** SQLite for the MVP. Local-first, simple deployment,
lightweight, no daemon. Future migration target: PostgreSQL.

**Geometry:** Shapely. Used for:

- Polygon operations.
- Intersections / unions.
- Inward offsets (setbacks).
- Area calculations.
- Distance validation.

**Auth:** bcrypt + JWT (PyJWT).
**Testing:** pytest + httpx TestClient.
**Lint / types:** ruff + `mypy --strict`.

### 3.7 Rule engine design

Rules must be:

- JSON / config-driven.
- Municipality-specific.
- Extensible.
- Versioned (per-pack semver).
- Testable.

**Example rule** (matches the format actually shipped):

```json
{
  "id": "blr.fsi.cbd.residential",
  "city": "Bangalore",
  "applies_when": {
    "classification": "CBD",
    "zone": "Residential"
  },
  "category": "fsi",
  "evaluator": "fsi_limit",
  "params": { "max_fsi": 2.5 },
  "severity": "error",
  "message_template": "FSI {computed.fsi} exceeds limit {params.max_fsi} for {applies_when.classification}/{applies_when.zone}"
}
```

`evaluator` maps to a registered Python function in `compliance/`.
New evaluators = new code; new values = JSON edit only.

Rule packs are versioned per city under
`planara_engine/rules/packs/{city}-{version}.json`.

### 3.8 DTO architecture

Shared schemas are required between Ruby and Python. The Python
side is the source of truth (Pydantic); Ruby mirrors as plain
hashes.

**Snapshot (Ruby → Python):**

```json
{
  "snapshot_id": "uuid",
  "project": { "classification": "CBD", "zone": "Residential", "city": "Bangalore" },
  "plot": {
    "polygon": [[x, y], [x, y], ...],
    "area_m2": 450.0,
    "road_widths_m": { "front": 12.0 }
  },
  "building": {
    "floors": [
      { "level": 0, "polygon": [[x, y], ...], "height_m": 3.2 },
      { "level": 1, "polygon": [[x, y], ...], "height_m": 3.0 }
    ],
    "total_height_m": 9.6
  }
}
```

**Validation response (Python → Ruby):**

```json
{
  "snapshot_id": "uuid",
  "ok": false,
  "violations": [
    {
      "rule_id": "blr.fsi.cbd.residential",
      "severity": "error",
      "category": "fsi",
      "message": "FSI 3.1 exceeds limit 2.5 for CBD/Residential",
      "computed": { "fsi": 3.1, "limit": 2.5 }
    }
  ],
  "metrics": { "fsi": 3.1, "coverage_pct": 62.0, "min_setback_m": 1.4 }
}
```

These contracts are **critical** — a drift between Ruby's emitted
JSON and Python's Pydantic models silently breaks every downstream
evaluator.

### 3.9 IPC strategy

**Chosen: localhost HTTP** (FastAPI behind uvicorn, bound to
`127.0.0.1`).

Why HTTP over alternatives (stdin/stdout, named pipes, Unix
sockets):

- Simple to debug (`curl` works).
- Same transport works for future cloud deployment.
- Standard auth (Bearer JWT) plugs in cleanly.
- Tooling (OpenAPI, Postman) is free.

### 3.10 Engine lifecycle management

The Ruby plugin is responsible for:

- Detecting whether the Python engine is already running.
- Starting the engine on first menu click if needed.
- Monitoring its health via `GET /health`.
- Restarting on crash (with retry + backoff).
- Stopping the engine cleanly on SketchUp shutdown
  (SIGTERM → wait → SIGKILL on timeout).

This lives in `planara_plugin/planara/engine_supervisor.rb`.

---

## PHASE 4 — MIGRATION STRATEGY

### 4.1 Migration philosophy

This is **not**:

- Syntax translation.
- A direct Ruby → Python rewrite.

This **is**:

- Architectural separation of concerns.
- Compliance-engine extraction.
- Long-term platform redesign.

### 4.2 What stays in Ruby

Only:

- SketchUp APIs.
- Observers.
- Geometry extraction.
- UI.
- Engine lifecycle management.

### 4.3 What moves to Python

All business logic:

- Calculations.
- Compliance rules.
- Zoning.
- Validation.
- Reporting.

### 4.4 Migration risks

#### Risk 1 — Geometry contract drift

The biggest architectural risk. If geometry schemas drift between
Ruby (emitter) and Python (consumer):

- FAR breaks.
- Setbacks break.
- Parking breaks.
- Zoning breaks.

**Mitigation:**

- Define DTOs early as the source of truth.
- Freeze schema versions on each engine release.
- Add contract tests on both sides (`tests/integration/` on the
  engine, `test/test_engine_client.rb` on the plugin).

#### Risk 2 — Split business logic

The danger of logic accidentally living partly in Ruby and partly
in Python (legacy formulas left behind).

**Mitigation:** all validation logic must live in Python. Ruby is
allowed to extract geometry and call `/validate` — nothing else.

#### Risk 3 — Engine lifecycle instability

Potential issues:

- Engine fails to start.
- Port conflicts.
- Crash recovery loop.

**Mitigation:**

- Health checks (`/health` polled until ready).
- Retry logic with backoff.
- Logging on both sides.
- Watchdog handling in `engine_supervisor.rb`.

#### Risk 4 — Unit mismatch

Potential mismatch:

- Meters.
- Millimeters.
- Feet.
- Inches (SketchUp internal).

**Mitigation:** central unit-normalization layer in Ruby
(`planara_plugin/planara/geometry/units.rb`). All numbers on the
wire are in **meters**. The engine never sees other units.

### 4.5 Migration order

1. Stabilize plugin boot (`boot.rb`, menu registration).
2. Create FastAPI sidecar (`planara_engine/api/app.py`).
3. Define DTO schemas (`domain/*`).
4. Implement geometry export (`geometry/extractor.rb`).
5. Implement FAR validation (`compliance/fsi.py`).
6. Implement setback validation (`compliance/setback.py`).
7. Implement reporting (`reporting/*`).

This matches the Sprint 1–3 ordering that was actually executed.

### 4.6 Recommended Git strategy

**Branch strategy:**

- `main` is always green.
- Short-lived feature branches.

Example branches:

```
feat/engine-fsi
feat/plugin-history-dialog
chore/ruff-mypy-config
```

### 4.7 Recommended commit strategy

Commits should:

- Represent one logical change.
- Compile / pass tests independently.
- Avoid partial architecture breaks (don't merge engine changes
  without matching plugin contract updates).

Example commit subjects (matching the project's actual style):

```
feat(engine): add setback evaluator using Shapely
feat(plugin): /history client + Recent runs UI + diff in browser
chore(engine): ruff + mypy go green; tighten configs to passing subset
docs+ci: 0.2.0 — history surface, CHANGELOG, GitHub Actions
```

### 4.8 MVP auth decision

Chosen MVP approach:

- Local session auth.
- SQLite-backed user table.
- bcrypt password hashing.
- JWT issued by the engine, stored in `Session` on the plugin side
  and attached to subsequent requests as `Authorization: Bearer`.
- Auto-seeded admin user on first engine boot.

Deferred:

- Organization accounts.
- License-based activation.
- SSO / OAuth.
- Cloud sync.

---

## Long-term platform vision

The hybrid architecture established in Phases 1–4 is intended to
support, without re-architecture:

- **AI-assisted compliance** — Claude / GPT evaluators registered
  alongside deterministic ones in `compliance/`.
- **OCR of municipal PDFs** — adapters under `adapters/` feed
  extracted rules into the rule-pack format.
- **Auto-rule extraction** — NLP pipeline that proposes new rule
  JSON from bylaw PDFs for human review.
- **GIS integration** — zoning overlays as GeoJSON layers consumed
  by the rule engine's `applies_when` matcher.
- **CAD interoperability** — DWG / IFC importers as additional
  snapshot sources alongside the SketchUp extractor.
- **Multi-city rule packs** — already exercised (Bangalore +
  Mumbai); the pack-per-city layout scales without code changes.
- **Cloud validation APIs** — the engine binds to localhost today
  but is deployment-shape-agnostic; only `PLANARA_ENGINE_URL`
  changes.
- **Collaborative review workflows** — the `/history` surface plus
  per-user scoping is the seed for team-shared reports.

---

## Foundation established

By the end of Phase 4 the following were settled, allowing Sprint 1
to begin without re-litigating architecture:

- Two-process hybrid (Ruby plugin + Python sidecar).
- HTTP/JSON IPC with meters as the wire unit.
- Pydantic DTOs as the source of truth for the contract.
- Rule packs as versioned JSON per city.
- FastAPI + Shapely + SQLite + bcrypt + JWT stack.
- Engine lifecycle owned by the plugin (`engine_supervisor.rb`).
- Test discipline (pytest + minitest, ruff, `mypy --strict`).
- Legacy Ruby prototype preserved under `legacy/` for reference.
