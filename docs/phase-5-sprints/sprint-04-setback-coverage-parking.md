# Sprint 4 — Setback + Coverage + Open space + Parking

**Dates:** 2026-05-16 11:06–11:32 IST (~25 min)
**Version:** 0.1.0-dev
**Commits:** 5
**Headline:** Four more evaluators on the S3 chassis, plus Bangalore v0.2.0 with 27 rules across 5 categories.

---

## Goal

Add the next four MVP evaluators by registering them into the
existing rule engine. No engine changes — just new files in
`compliance/` and new rules in a new pack version.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `4120516` | 11:06:42 | feat(engine/compliance): setback evaluator (Shapely distance, not bbox) |
| `2325590` | 11:10:21 | feat(engine/compliance): ground coverage + open space evaluators |
| `6cf5c8e` | 11:22:14 | feat(domain): Building.parking_slots_provided + extractor plumbing |
| `a6095b2` | 11:24:39 | feat(engine/compliance): parking evaluator (slots-per-m^2 form) |
| `84fbcb2` | 11:32:19 | feat(engine/rules): Bangalore v0.2.0 — setback, coverage, open space, parking |

---

## Engine deliverables

### Setback evaluator (`compliance/setback.py`)

Replaces the legacy axis-aligned check. Two equivalent forms,
both shipped:

```python
# Form 1: inward buffer
plot_inner = plot.buffer(-params.min_setback_m, join_style="mitre")
ok         = footprint.within(plot_inner)

# Form 2: explicit distance
distance_to_boundary = footprint.distance(plot.exterior)
ok                   = distance_to_boundary >= params.min_setback_m
```

Form 1 is the canonical evaluator; Form 2 is used in
`metrics["min_setback_m"]` for the report.

Parameters:

```json
{ "min_setback_m": 2.0 }
```

Legacy bug fixed: the axis-aligned check (`pt.x.abs < setback ||
pt.y.abs < setback`) assumed the plot was centered at the origin
and was a rectangle. The Shapely form handles arbitrary plots.

### Coverage + open space evaluators (`compliance/coverage.py`)

Two evaluators in one module because they share computation:

```python
footprint_area = unary_union(floor.polygon for floor in floors if floor.level == 0).area
coverage_pct   = footprint_area / plot_area * 100
open_space_pct = (plot_area - footprint_area) / plot_area * 100
```

Parameters:

```json
// ground_coverage rule
{ "max_coverage_pct": 60 }

// open_space rule
{ "min_open_space_pct": 25 }
```

These are kept as separate rule categories in the pack so
violations surface as distinct items in the report.

### Parking evaluator (`compliance/parking.py`)

> verbatim from `a6095b2`:
> *"`ceil(built-up / m²/slot) + visitor pct`."*

```python
base_required    = ceil(built_up_area / params.m2_per_slot)
visitor_required = ceil(base_required * params.visitor_pct / 100)
required         = base_required + visitor_required
provided         = building.parking_slots_provided or 0
ok               = provided >= required
```

Parameters:

```json
{
  "m2_per_slot": 100,
  "visitor_pct": 10
}
```

### Domain: `Building.parking_slots_provided`

> verbatim from `6cf5c8e`:
> *"`Building.parking_slots_provided` + extractor plumbing."*

New optional `int` field on `Building`. The Ruby extractor sets
it from a `parking_slots` integer attribute on the SketchUp model
(or 0 if absent).

### Bangalore v0.2.0 rule pack

> verbatim from `84fbcb2`:
> *"27 rules across 5 categories."*

Five categories now: `fsi`, `setback`, `ground_coverage`,
`open_space`, `parking`. Three classifications × three zones × ~3
categories with rules per cell = 27 rules.

Sample cell — CBD/Residential:

```json
{ "id": "blr.fsi.cbd.residential",       "evaluator": "fsi_limit",      "params": { "max_fsi": 2.5 } }
{ "id": "blr.setback.cbd.residential",   "evaluator": "setback_min",    "params": { "min_setback_m": 2.0 } }
{ "id": "blr.coverage.cbd.residential",  "evaluator": "coverage_max",   "params": { "max_coverage_pct": 60 } }
{ "id": "blr.openspace.cbd.residential", "evaluator": "open_space_min", "params": { "min_open_space_pct": 25 } }
{ "id": "blr.parking.cbd.residential",   "evaluator": "parking_slots",  "params": { "m2_per_slot": 100, "visitor_pct": 10 } }
```

---

## Tests added

- `tests/unit/test_setback.py` — Shapely-based distances,
  concave plot cases.
- `tests/unit/test_coverage.py` — disconnected footprints,
  partial-outside clipping.
- `tests/unit/test_parking.py` — base + visitor ceil math, zero
  built-up edge case.
- `tests/unit/test_bangalore_pack.py` extended — all 27 rules
  loaded and dispatched.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/compliance/{setback,coverage,parking}.py
+ planara_engine/src/planara_engine/rules/packs/bangalore-0.2.0.json
~ planara_engine/src/planara_engine/domain/building.py  (parking_slots_provided)
~ planara_plugin/planara/geometry/extractor.rb          (parking_slots plumbing)
+ planara_engine/tests/unit/{test_setback,test_coverage,test_parking}.py
~ planara_engine/tests/unit/test_bangalore_pack.py      (all 27 rules)
```

---

## Concrete example pinned by test

20 m × 20 m plot, 18 m × 18 m footprint centered on plot, three
floors:

```
setback        : 1 m vs 2 m required        → violation
coverage       : 81% vs 60% limit           → violation
open space     : 19% vs 25% required        → violation
parking        : 0 vs 11 required           → violation (3 × 18×18 = 972 m²,
                                              10 base + 1 visitor)
fsi            : 2.43 vs 2.5 limit          → ok
```

Earlier internal example used an 18×18 footprint at the boundary
yielding `setback 0 m vs 2 m`, `parking 0 vs 5 required`.

---

## Invariants locked

- Footprint area uses `unary_union` of ground-floor polygons.
- Partial-outside footprints are clipped to plot before area
  computation; the excluded slice surfaces as a setback violation.
- Parking required is `ceil`, not `round` — always round *up*.
- Touching the boundary fails setback (strict `within`).

---

## Risks mitigated

| Risk | How |
|---|---|
| R1 — wrong legacy logic (axis-aligned setback) | Replaced with Shapely-correct inward buffer + distance form. |

---

## Deferred from this sprint

- Height evaluator (S5 — bundled with overlays).
- Tiered setbacks (high-rise growing setbacks per `rules.json`).
- Front-vs-rear setback discrimination.
- Per-use parking ratios (hotel / hospital / theatre).
- EV charging triggers.
- Slot-dimension validation (counts slots only).
- Service-area exclusions in FSI.

These appear in the full deferred backlog in
[Phase 4 §4.7](../phase-1-to-4-architecture/04-migration-strategy.md#47-what-was-deferred-and-why).
