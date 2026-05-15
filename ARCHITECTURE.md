# Planara — Architecture

Planara is a building-bylaw / development-control compliance plugin
for SketchUp. It validates a design against municipal regulations
(FSI/FAR, setbacks, ground coverage, open space, parking, zoning
overlays) live, while the user models.

This document describes the **target** architecture being built in
this repository. The original Ruby-only prototype lives under
`SV-Abid/` and is preserved as a reference; new code lives under
`planara_plugin/` (Ruby) and `planara_engine/` (Python).

---

## 1. Constraints that shaped the design

1. **SketchUp plugins are Ruby-only.** SketchUp embeds a Ruby
   interpreter and exposes its API (`Sketchup::*`) exclusively to
   Ruby. There is no Python SDK. Any geometry the engine needs has
   to be extracted by Ruby code running inside SketchUp.
2. **Compliance logic must be testable, evolvable, and city-pluggable.**
   Bangalore bylaws today, Mumbai tomorrow, plus heritage/airport
   overlays. Ruby inside SketchUp is a poor environment for that:
   no package manager, sandboxed stdlib, awkward testing.
3. **Geometry math wants real libraries.** Setbacks are polygon
   offsets. Coverage is polygon union / intersection. Shapely (and
   eventually GEOS) is the right tool.
4. **The engine must be deployable beyond the desktop.** Cloud
   validation APIs, batch checks against many designs, and CI-style
   "does this DWG comply?" pipelines are foreseeable.

The hybrid split below addresses all four.

---

## 2. High-level topology

```
┌─────────────────────────── SketchUp Process ──────────────────────────┐
│                                                                       │
│  planara_plugin/  (Ruby — thin shell)                                 │
│                                                                       │
│   ├─ boot.rb               Extension registrar, lifecycle hooks       │
│   ├─ observers/            App / Model / Entities / Tools observers   │
│   ├─ geometry/extractor.rb Sketchup::* → JSON snapshot (in meters)    │
│   ├─ engine_client.rb      Net::HTTP client to localhost:<port>       │
│   ├─ engine_supervisor.rb  Spawn/healthcheck/stop the Python sidecar  │
│   ├─ ui/                   HtmlDialog screens (login, results, …)     │
│   └─ session.rb            Holds JWT after login                      │
│                                                                       │
└──────────────────────────────────┬────────────────────────────────────┘
                                   │ HTTP/JSON  (localhost only by default)
┌──────────────────────────────────▼────────────────────────────────────┐
│                                                                       │
│  planara_engine/  (Python 3.11+ — FastAPI service)                    │
│                                                                       │
│   api/          FastAPI routers (auth, projects, validate, …)        │
│   auth/         Local user store, bcrypt, JWT sessions               │
│   domain/       Typed models: Plot, Building, Floor, Zone, Snapshot  │
│   rules/        Rule schema, loader, rule packs per city             │
│   engine/       RuleEngine — selects + evaluates rules               │
│   compliance/   FSI / setback / coverage / open_space / parking      │
│   geometry/     Shapely-backed polygon ops (offset, union, area)     │
│   reporting/    Violation lists → structured reports                 │
│   persistence/  SQLite (users, sessions, projects, history)          │
│   adapters/     Future: PDF/OCR ingest, GIS, CAD interop             │
│   core/         Settings, logging, errors, request-id middleware     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### Why "sidecar" and not "cloud-only"

The Python service runs as a **local process** that the Ruby plugin
spawns at startup and stops at shutdown. This keeps the plugin
offline-capable and avoids per-keystroke latency. The same service
is deployable to a remote host without code changes — only the
`PLANARA_ENGINE_URL` setting changes.

---

## 3. The Ruby ↔ Python contract

All communication is JSON over HTTP. Geometry is always exchanged in
**meters** (Ruby converts once using SketchUp's `UnitsOptions`).
Polygons follow GeoJSON-like ordering: outer ring CCW, holes CW.

### Snapshot payload (Ruby → Python)

```json
{
  "snapshot_id": "uuid",
  "project": {
    "classification": "CBD",
    "zone": "Residential",
    "city": "Bangalore"
  },
  "plot": {
    "polygon": [[x,y], [x,y], ...],
    "area_m2": 450.0,
    "road_widths_m": {"front": 12.0}
  },
  "building": {
    "floors": [
      {"level": 0, "polygon": [[x,y],...], "height_m": 3.2},
      {"level": 1, "polygon": [[x,y],...], "height_m": 3.0}
    ],
    "total_height_m": 9.6
  }
}
```

### Validation response (Python → Ruby)

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
      "computed": {"fsi": 3.1, "limit": 2.5}
    }
  ],
  "metrics": {
    "fsi": 3.1, "coverage_pct": 62.0, "min_setback_m": 1.4
  }
}
```

The contract is defined by Pydantic models in `domain/` and
mirrored in Ruby as plain hashes; the schema is the source of
truth.

---

## 4. Rule engine

Rules are **declarative JSON documents**, not Python code. One rule:

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

- **`evaluator`** maps to a registered Python function in
  `compliance/`. New evaluators = new code; new rule values = JSON
  edit only.
- **Rule packs** are versioned per city:
  `rules/packs/bangalore-v1.0.json`.
- The legacy `config/rules.json`, `fsi-config.json`, and
  `setback-config.json` will be migrated into the rule-pack format
  in Sprint 3+.

---

## 5. Lifecycle

```
SketchUp starts
   │
   ▼
planara_plugin/boot.rb → register extension, menu item
   │
User clicks "Planara" menu
   │
   ▼
EngineSupervisor.start   ── spawns Python uvicorn process
   │                        and polls /health until ready
   ▼
UI.show_login_dialog     ── POST /auth/login → JWT stored
   │
   ▼
Observers attach          ── ModelObserver, EntitiesObserver, …
   │
User models geometry
   │
   ▼
GeometryExtractor.snapshot(model)
   │
   ▼
EngineClient.validate(snapshot)   ── POST /validate
   │
   ▼
UI.show_results(violations)
   │
SketchUp exits
   │
   ▼
EngineSupervisor.stop    ── SIGTERM uvicorn, wait, SIGKILL on timeout
```

---

## 6. Module responsibilities

| Module | Owns |
|---|---|
| `planara_plugin/boot.rb` | Extension registration, menu, lifecycle |
| `planara_plugin/engine_supervisor.rb` | Sidecar process management |
| `planara_plugin/engine_client.rb` | HTTP I/O, retries, JWT header |
| `planara_plugin/geometry/extractor.rb` | `Sketchup::*` → snapshot JSON |
| `planara_plugin/observers/*` | Translate SketchUp events to debounced validate calls |
| `planara_plugin/ui/*` | HtmlDialog screens + JS bridge |
| `planara_engine/api/*` | HTTP routers; no business logic |
| `planara_engine/auth/*` | Login, JWT mint/verify, user store |
| `planara_engine/domain/*` | Pydantic schemas (the contract) |
| `planara_engine/rules/*` | Rule loading, indexing, applicability |
| `planara_engine/engine/*` | Selects applicable rules, dispatches to evaluators, aggregates violations |
| `planara_engine/compliance/*` | One evaluator per concern (fsi, setback, …) |
| `planara_engine/geometry/*` | Polygon ops on Shapely |
| `planara_engine/reporting/*` | Render violations as HTML/PDF/JSON |
| `planara_engine/persistence/*` | SQLite via SQLModel |
| `planara_engine/core/*` | Settings, logging, errors, middleware |

---

## 7. Non-goals (for the MVP)

- Replacing the SketchUp Ruby plugin shell with anything else.
- Multi-user concurrent editing.
- Cloud deployment (architecture supports it, sprint scope does not).
- DWG / IFC import (slot exists under `adapters/`, not built yet).

---

## 8. Where to look next

- `CLAUDE.md` — what the legacy `SV-Abid/` Ruby code does today.
- `planara_engine/README.md` — engine quickstart (added in Sprint 1).
- `planara_plugin/README.md` — plugin install/dev guide (added in Sprint 1).
