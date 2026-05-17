# Sprint 7 — Mumbai rule pack: proving the city-isolation contract

**Dates:** 2026-05-16 18:52–19:22 IST (~30 min)
**Version:** 0.1.0-dev
**Commits:** 4
**Headline:** Mumbai v0.1.0 (base pack) + v0.2.0 (CRZ + airport overlays) ship with **zero changes to the evaluator code or the engine**. The rule-pack design from S3 is validated.

---

## Goal

Demonstrate that "new city = data only." Mumbai brings new
classifications (Island / Suburbs), new overlay keys (CRZ), and
its own setback / parking / coverage values — but everything fits
into the existing rule-pack format, the existing evaluators, and
the existing applicability matcher.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `322eac8` | 18:52:39 | feat(engine/rules): Mumbai v0.1.0 base rule pack |
| `b09f48f` | 18:54:16 | feat(engine/rules): Mumbai v0.2.0 — CRZ + airport overlays |
| `f3eca4c` | 18:57:37 | test(engine/rules): pack-agnostic smoke tests |
| `eebb651` | 19:22:15 | test(integration): /validate end-to-end against Mumbai pack |

---

## Engine deliverables

### Mumbai v0.1.0 base pack

> verbatim from `322eac8`:
> *"Island / Suburbs × 3 zones, 21 rules."*

Mumbai's local divisions are not `Heritage / CBD / HDZ` but
`Island / Suburbs`. Two classifications × three zones × ~3.5
rules per cell = ~21 rules.

Sample cell — Island/Residential:

```json
{ "id": "mum.fsi.island.residential",       "evaluator": "fsi_limit",      "params": { "max_fsi": 1.33 } }
{ "id": "mum.setback.island.residential",   "evaluator": "setback_min",    "params": { "min_setback_m": 3.0 } }
{ "id": "mum.coverage.island.residential",  "evaluator": "coverage_max",   "params": { "max_coverage_pct": 40 } }
{ "id": "mum.openspace.island.residential", "evaluator": "open_space_min", "params": { "min_open_space_pct": 35 } }
{ "id": "mum.parking.island.residential",   "evaluator": "parking_slots",  "params": { "m2_per_slot": 80, "visitor_pct": 15 } }
```

ID convention: `mum.*` for Mumbai (vs `blr.*` for Bangalore).

### Mumbai v0.2.0 — CRZ + airport overlays

> verbatim from `b09f48f`:
> *"CRZ + airport overlays."*

Two new overlay rule families:

```json
{
  "id": "mum.crz.height",
  "applies_when": { "overlays_include": ["crz"] },
  "evaluator": "height_limit",
  "params": { "max_height_m": 9.0 }
}

{
  "id": "mum.crz.fsi",
  "applies_when": { "overlays_include": ["crz"] },
  "evaluator": "fsi_limit",
  "params": { "max_fsi": 0.5 }
}

{
  "id": "mum.height.airport",
  "applies_when": { "overlays_include": ["airport"] },
  "evaluator": "height_limit",
  "params": { "max_height_m": 24.0 }
}
```

Note: `crz` is Mumbai-only; `airport` is reused from Bangalore.
Overlays can be either city-scoped or shared — the matcher
doesn't care.

> verbatim invariant:
> *"`airport` overlay reused across both packs; `crz` stays
> Mumbai-only — proving overlay keys can be either shared or
> city-scoped."*

---

## Tests added

### Pack-agnostic smoke tests

> verbatim from `f3eca4c`:
> *"Pack-agnostic smoke tests."*

`tests/unit/test_packs_smoke.py` — loads every pack from
`rules/packs/`, validates JSON, asserts no duplicate ids, asserts
every evaluator referenced is registered.

This is the regression net for "add a new pack, break nothing."

### Mumbai integration

`tests/integration/test_validate_mumbai.py` — full /validate
round-trip against Mumbai snapshots:

- Island/Residential, no overlays → FSI 1.33 cap binds.
- Suburbs/Commercial, airport overlay → 24 m height cap binds.
- Island/Residential, CRZ overlay → 9 m height + 0.5 FSI cap.

> verbatim invariant from `eebb651`:
> *"Same snapshot routed by `project.city` produces `mum.*` vs
> `blr.*` rule IDs."*

The same geometry validates differently depending only on
`project.city`. That's the city-isolation contract.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/rules/packs/mumbai-0.1.0.json
+ planara_engine/src/planara_engine/rules/packs/mumbai-0.2.0.json
+ planara_engine/tests/unit/test_packs_smoke.py
+ planara_engine/tests/unit/test_mumbai_pack.py
+ planara_engine/tests/integration/test_validate_mumbai.py
```

**Zero changes to engine, compliance, geometry, or domain modules.**

---

## Invariants locked

### D18 — Adding a new city is data-only

> verbatim:
> *"Audit — engine is already city-agnostic; zero code changes
> needed."*

This sprint is the proof. If a future PR for a new city touches
anything outside `rules/packs/`, that PR is doing too much.

### Multi-city verdict routing

`Project.city` is the only key that maps to a pack. The engine
loads the appropriate pack and the rule IDs reflect the city
namespace. Two cities with identical geometry produce different
verdicts.

---

## Risks mitigated

| Risk | How |
|---|---|
| R7 — `rules.json` semantics undocumented (Bangalore-specific) | Mumbai's existence forces the schema to stay city-generic. |

---

## Concrete example pinned by test

20 m × 20 m plot, 18 m × 18 m footprint, four floors × 3 m = 12 m
total.

Routed as **Bangalore CBD/Residential**:

```
fsi: 3.24 vs 2.5         → violation (blr.fsi.cbd.residential)
setback: 1m vs 2m        → violation (blr.setback...)
coverage: 81% vs 60%     → violation (blr.coverage...)
open_space: 19% vs 25%   → violation (blr.openspace...)
```

Same snapshot routed as **Mumbai Island/Residential**:

```
fsi: 3.24 vs 1.33        → violation (mum.fsi.island.residential)
setback: 1m vs 3m        → violation (mum.setback...)
coverage: 81% vs 40%     → violation (mum.coverage...)
open_space: 19% vs 35%   → violation (mum.openspace...)
```

Same geometry. Different city. Different verdict. Same engine
code.

---

## Deferred from this sprint

- More Mumbai overlays (railway buffer, salt-pan land,
  reservation overlays).
- Delhi, Chennai, Hyderabad packs (1 sprint each per the deferred
  backlog).
- Spatial overlay determination (GIS) — overlays still set
  manually by the user in the project picker.

---

## Why this sprint vindicates Phase 2 and Phase 3

Phase 2 designed the city-pack contract. Phase 3 designed the
applicability matcher. S7 ships a second city in **30 minutes**
including tests. That's the proof that the design held up.
