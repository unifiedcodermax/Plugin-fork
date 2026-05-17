# Sprint 5 — Overlays + Height evaluator + Bangalore v0.3.0

**Dates:** 2026-05-16 11:55–14:30 IST (~2.5 hours, includes UI work)
**Version:** 0.1.0-dev
**Commits:** 5
**Headline:** Overlay applicability dimension (`airport`, `heritage_influence`), `height_limit` evaluator, Bangalore v0.3.0 with airport (45 m cap) and heritage_influence (12 m cap) overlays, and Ruby `DataPoints[:overlays]` UI input.

---

## Goal

Add the **applicability dimension** that overlay zoning needs.
Rules can now declare `overlays_include` predicates; the matcher
honors them; the height evaluator demonstrates overlay-driven
constraints.

The key design choice in this sprint: **overlays are an
applicability dimension, not rule inheritance.** A rule fires if
the overlay is present; rules don't extend each other.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `591df03` | 11:55:00 | feat(engine/rules): overlays — additive applicability filter |
| `6c1afc8` | 12:01:32 | feat(engine/compliance): height_limit evaluator |
| `bec0159` | 13:33:07 | feat(engine/rules): Bangalore v0.3.0 — airport + heritage_influence overlays |
| `6197956` | 14:29:00 | test(integration): /validate overlay end-to-end coverage |
| `c06559a` | 14:30:16 | feat(plugin/ui): overlays input + DataPoints slot |

---

## Engine deliverables

### Overlay applicability

> verbatim from `591df03`:
> *"Overlays — additive applicability filter."*

Rule schema extension:

```json
{
  "applies_when": {
    "classification": "CBD",
    "zone": "Residential",
    "overlays_include": ["airport"]
  }
}
```

Matcher semantics:

- If `overlays_include` is absent or empty → rule matches any
  overlay set (including none).
- If `overlays_include` is non-empty → all listed overlays must be
  present in `snapshot.project.overlays` for the rule to fire.

The match is **additive**: a base rule and an overlay rule for
the same cell both fire. The stricter limit binds, but both
appear in the violations list (with their own `rule_id`).

### Height evaluator (`compliance/height.py`)

```python
height_m = sum(floor.height_m for floor in floors)
ok       = height_m <= params.max_height_m
```

Parameters:

```json
{ "max_height_m": 45 }
```

Per-floor sum (not `count × default`) because floor heights vary
in real designs.

### Bangalore v0.3.0 rule pack

Adds overlay rules on top of v0.2.0. Two new families:

```json
{
  "id": "blr.height.airport",
  "applies_when": { "overlays_include": ["airport"] },
  "category": "height",
  "evaluator": "height_limit",
  "params": { "max_height_m": 45 },
  "severity": "error"
}

{
  "id": "blr.height.heritage_influence",
  "applies_when": { "overlays_include": ["heritage_influence"] },
  "category": "height",
  "evaluator": "height_limit",
  "params": { "max_height_m": 12 },
  "severity": "error"
}
```

These are **city-wide** overlay rules (no classification/zone
constraint) — anywhere in Bangalore with the overlay present, the
cap applies.

---

## Plugin deliverables

### Overlays UI input

> verbatim from `c06559a`:
> *"Overlays input + DataPoints slot."*

The project setup dialog (`UI.inputbox`) gains a checkbox set for
overlays. `DataPoints[:overlays]` holds the selected set.
`Geometry::Extractor` reads from there and emits `overlays` on
the snapshot.

(Note: this is iterated further in S6 when `Session.project`
replaces the looser `DataPoints` slots.)

---

## Tests added

- `tests/unit/test_height.py` — height_limit evaluator,
  per-floor sum.
- `tests/integration/test_validate.py` (extended) — overlay
  cases: airport-only, heritage_influence-only, both, neither.
- Bangalore pack tests extended for v0.3.0.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/compliance/height.py
+ planara_engine/src/planara_engine/rules/packs/bangalore-0.3.0.json
~ planara_engine/src/planara_engine/rules/{schema,loader}.py   (overlays_include)
~ planara_engine/src/planara_engine/engine/rule_engine.py      (applicability)
~ planara_engine/src/planara_engine/domain/project.py          (overlays: set[str])
+ planara_engine/tests/unit/test_height.py
~ planara_engine/tests/integration/test_validate.py            (overlay cases)
~ planara_plugin/planara/ui/input_dialog.rb (or DataPoints)    (overlays input)
~ planara_plugin/planara/geometry/extractor.rb                 (overlays in snapshot)
```

---

## Invariants locked

### D14 — Overlays are an applicability dimension, not inheritance

> verbatim:
> *"Overlay membership (`airport`, `heritage_influence`, `crz`) is
> a key on `applies_when`. There is no rule-inheritance
> mechanism."*

A rule with `overlays_include: ["airport"]` fires *in addition to*
the base rules — not instead of them. The stricter cap surfaces in
the violations list; the looser one is `ok`.

### Multiple rules can fire per cell

A CBD/Residential design inside an airport overlay gets:

- `blr.fsi.cbd.residential` (FSI limit 2.5).
- `blr.setback.cbd.residential` (setback 2 m).
- … all base rules …
- `blr.height.airport` (height ≤ 45 m).

If two rules touch the same metric, both run. The user sees both
verdicts in the report.

---

## Risks mitigated

| Risk | How |
|---|---|
| (No new risks; this sprint sits inside the chassis built in S3.) | — |

---

## Concrete example pinned by test

15 floors × 3.2 m = 48 m, CBD/Residential, airport overlay:

```
fsi              : within limit          → ok
height.airport   : 48 m vs 45 m          → violation
```

Same design, no airport overlay, no heritage_influence:

```
fsi   : within limit                     → ok
height: no rule fires                    → ok
```

Same design, heritage_influence overlay:

```
height.heritage_influence : 48 m vs 12 m → violation
```

---

## Deferred from this sprint

- Overlay polygons (today: project-context strings; future: GIS
  spatial test).
- More overlays for Bangalore (transit corridor, lake buffer, …).
- Per-floor / per-zone height caps (today: building-wide sum).
- Mumbai pack (S7).

---

## Why this matters for "new city = data only"

The overlay machinery here is what later (S7) lets Mumbai ship
**without code changes**. Mumbai brings `crz` as a new overlay key
— but the applicability matcher doesn't need to know that. It just
filters on the set membership. The engine remains city-agnostic.

> verbatim from S7.1 audit:
> *"Audit — engine is already city-agnostic; zero code changes
> needed."*
