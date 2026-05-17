# Sprint 3 — Domain + Rules + FSI: the end-to-end vertical slice

**Dates:** 2026-05-16 07:36–08:56 IST (~80 min)
**Version:** 0.1.0-dev
**Commits:** 8
**Headline:** Plot + Building + Snapshot Pydantic models; Shapely geometry; rule schema + JSON pack loader; RuleEngine + evaluator registry; real FSI evaluator; Bangalore v0.1.0 pack; `/validate` endpoint; SketchUp geometry extractor in Ruby.

---

## Goal

The first **complete vertical slice**. By the end of S3, a Ruby
plugin can extract a snapshot from a SketchUp model, POST it to
`/validate`, and the engine returns a FSI violation if the design
exceeds the limit.

This is the sprint that makes the architecture from `ARCHITECTURE.md`
*real*.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `40dbf2b` | 07:36:11 | feat(engine/domain): Pydantic wire schemas (Plot, Building, Snapshot, …) |
| `9841abf` | 07:38:27 | feat(engine/geometry): Shapely-backed polygon ops |
| `404993f` | 07:44:10 | feat(engine/rules): rule schema, pack loader, applicability filter |
| `5d01b1e` | 07:47:56 | feat(engine/engine): RuleEngine + evaluator registry |
| `c81a278` | 08:00:05 | feat(engine/compliance): real FSI evaluator (replaces bbox legacy math) |
| `02d3932` | 08:17:31 | feat(engine/rules): Bangalore v0.1.0 rule pack (FSI limits) |
| `b612631` | 08:20:50 | feat(engine/api): POST /validate end-to-end |
| `42ad156` | 08:56:18 | feat(plugin/geometry): extractor turns SketchUp model into Snapshot JSON |

---

## Engine deliverables

### Domain models (`domain/`)

```
domain/
  geometry.py                # Polygon, Point, ring orientation
  plot.py                    # Plot(polygon, area_m2, road_widths_m)
  building.py                # Building(floors: list[Floor]), Floor
  project.py                 # Project(city, classification, zone, overlays)
  snapshot.py                # Snapshot(snapshot_id, schema_version, project, plot, building)
  violation.py               # Violation(rule_id, severity, category, message, computed)
```

All Pydantic v2 models. These are the **wire contract** — see
[D9 in the decisions log](../phase-1-to-4-architecture/05-decisions-log.md#d9--pydantic-is-the-source-of-truth-for-the-wire).

### Geometry operations (`geometry/`)

```
geometry/
  normalize.py               # Bowtie detection, ring orientation, snapshot entry gate
  operations.py              # area, union, inset (mitered), within, distance_to_boundary
```

> verbatim from `9841abf`:
> *"Shapely-backed geometry — area, union, inset (mitered),
> within, distance-to-boundary; bowtie polygon correctly
> rejected, not silently repaired."*

### Rule schema + loader (`rules/`)

```
rules/
  schema.py                  # Pydantic Rule, RulePack
  loader.py                  # load_pack, latest_version, applicability matcher
  packs/
    bangalore-0.1.0.json     # FSI cells: Heritage|CBD|HDZ × Residential|Commercial|Industry
```

> verbatim from `404993f`:
> *"Rule schema + JSON pack loader with versioning, applicability
> matcher, duplicate-id and bad-JSON guards."*

Loader guarantees:

- Duplicate `id` across rules → load error.
- Malformed JSON → load error with line number.
- Per-pack semver in filename.

### Rule engine (`engine/`)

```
engine/
  registry.py                # @register("op_name") decorator
  rule_engine.py             # evaluate(snapshot) → ValidationResponse
```

> verbatim from `5d01b1e`:
> *"RuleEngine + evaluator registry with `_SafeDict` template
> fallback so a typo'd `{wrong_key}` doesn't 500 the whole
> evaluate call."*

`_SafeDict` renders missing keys as `{missing_key}` literally — so
a rule with a typo doesn't crash the whole evaluate.

### FSI evaluator (`compliance/fsi.py`)

> verbatim from `c81a278`:
> *"Real FSI evaluator: per-floor areas, habitable filter,
> basement/stilt opt-ins, optional warn-near-limit band."*

Formula:

```
total_built_up = sum(floor_area(f) for f in floors if is_habitable(f, params))
fsi            = total_built_up / plot_area
violation if fsi > params.max_fsi
warning   if fsi > params.max_fsi * params.warn_near_limit_pct / 100
```

Parameters:

```json
{
  "max_fsi": 2.5,
  "include_basement": false,
  "include_stilt": false,
  "warn_near_limit_pct": 95
}
```

Explicitly replaces the legacy `floor_count × bbox_footprint /
plot_area` toy.

### Bangalore v0.1.0 rule pack

> verbatim from `02d3932`:
> *"All 9 classification×zone cells, values pinned to legacy file
> by test."*

9 rules, one per `(classification, zone)` cell of the legacy
`fsi-config.json`:

- Heritage / Residential, Heritage / Commercial, Heritage / Industry.
- CBD / Residential (max_fsi 2.5), CBD / Commercial, CBD / Industry.
- HDZ / Residential, HDZ / Commercial, HDZ / Industry.

Test pins each cell against the legacy file — so a future edit
that drifts is caught.

### `/validate` endpoint

```
POST /validate
Authorization: Bearer <jwt>
Content-Type: application/json

{ Snapshot }

→ ValidationResponse {
    snapshot_id, ok, violations[], metrics{}
  }
```

---

## Plugin deliverables

### Geometry extractor (`geometry/extractor.rb`)

```ruby
class Planara::Geometry::Extractor
  def self.snapshot(model:, project:)
    plot     = discover_plot(model)
    floors   = discover_floors(model)
    {
      snapshot_id: SecureRandom.uuid,
      schema_version: "1.0",
      project: project_to_hash(project),
      plot: plot_to_hash(plot),
      building: building_to_hash(floors)
    }
  end
end
```

Discovery convention:

- `Plot` — a group named exactly `Plot` (case-sensitive). Its
  bottom face becomes the plot polygon.
- `Floor N` — groups named `Floor 0`, `Floor 1`, …. Each group's
  bottom face is the floor polygon; group height is `Floor.height_m`.

### Unit conversion (`geometry/units.rb`)

```ruby
module Planara::Geometry::Units
  def self.length_m(value, model_options)
    # Single conversion point. Handles inches, mm, cm, m, ft.
  end

  def self.area_m2(value, model_options)
    length_m(Math.sqrt(value), model_options) ** 2
  end
end
```

> See [D10 in the decisions log](../phase-1-to-4-architecture/05-decisions-log.md#d10--meters-on-the-wire) — meters on the wire.

---

## Tests added

### Engine

- `tests/unit/test_domain_models.py` — Pydantic invariants (no
  negative area, polygon ring conventions, schema version).
- `tests/unit/test_geometry.py` — Shapely wrappers; bowtie
  rejection.
- `tests/unit/test_rules.py` — pack loader, duplicate-id guard,
  bad-JSON guard.
- `tests/unit/test_engine.py` — RuleEngine evaluate path,
  `_SafeDict` fallback.
- `tests/unit/test_fsi.py` — FSI formula, habitable filter,
  basement/stilt opt-ins, warn-near-limit band.
- `tests/unit/test_bangalore_pack.py` — all 9 cells, values pinned
  to `legacy/SV-Abid/config/fsi-config.json`.
- `tests/integration/test_validate.py` — POST /validate end-to-end
  for Bangalore CBD/Residential.

### Plugin

- `test/test_extractor.rb` — mocked `Sketchup::*` objects, snapshot
  shape pinned.
- `test/test_units.rb` — every unit conversion factor.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/domain/{geometry,plot,building,project,snapshot,violation}.py
+ planara_engine/src/planara_engine/geometry/{normalize,operations}.py
+ planara_engine/src/planara_engine/rules/{schema,loader}.py
+ planara_engine/src/planara_engine/rules/packs/bangalore-0.1.0.json
+ planara_engine/src/planara_engine/engine/{registry,rule_engine}.py
+ planara_engine/src/planara_engine/compliance/{__init__,fsi,params}.py
+ planara_engine/src/planara_engine/api/routes_validate.py
+ planara_engine/tests/unit/{test_domain_models,test_geometry,test_rules,test_engine,test_fsi,test_bangalore_pack}.py
+ planara_engine/tests/integration/test_validate.py
+ planara_plugin/planara/geometry/{units,extractor}.rb
+ planara_plugin/test/{test_extractor,test_units}.rb
```

---

## Invariants locked

### D9 — Pydantic is source of truth
### D10 — Meters on the wire
### D11 — `_SafeDict` for message-template substitution
### D12 — Shapely rejects bowties; no auto-repair
### D13 — Bangalore v0.1.0 preserved for version-pinning evidence

See [`05-decisions-log.md`](../phase-1-to-4-architecture/05-decisions-log.md).

---

## Risks mitigated

| Risk | How |
|---|---|
| R1 — wrong business logic (legacy FSI) | Rebuilt from scratch in `compliance/fsi.py`; legacy values pinned by test. |
| R3 — geometry extraction needs Ruby API | Thin Ruby extractor; JSON over wire. |
| R6 — unit conversion bugs | Single converter at the Ruby boundary. |

---

## Concrete example pinned by test

20 m × 20 m plot (= 400 m²), three 18 m × 18 m floors (= 324 m²
each, 972 m² total). CBD/Residential FSI limit 2.5.

```
fsi = 972 / 400 = 2.43 → ok
```

Add a fourth identical floor (1296 m² total):

```
fsi = 1296 / 400 = 3.24 → violation
  → "FSI 3.24 exceeds limit 2.5 for CBD/Residential"
```

Earlier internal smoke ran three 15 m floors yielding `FSI 3.375`
— same outcome.

---

## Deferred from this sprint

- Setback evaluator (S4).
- Coverage / open space / parking / height evaluators (S4–S5).
- Overlays (S5).
- Multiple floors with varying use (`use` field is on the wire but
  not differentiated).
- Service-area exclusions (lifts, shafts) — deferred indefinitely.
- FAR road-width premium evaluator (`road_widths_m` is on the
  wire; evaluator deferred).

---

## Why S3 is the densest sprint

S3 is where the architecture becomes a system. Every later sprint
plugs into the same chassis: register an evaluator, add a rule to
a pack, ship. The chassis itself only had to be built once — here.
