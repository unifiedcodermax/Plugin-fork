# Phase 2 — Domain & Compliance Analysis

## 2.1 Problem framing

The product validates **architectural designs against municipal
building byelaws**. It is not a CAD tool, not a renderer, not a
project-management tool. Every feature exists to answer a single
question:

> *"Is this design legal under the rules of city X?"*

That framing matters because it forces every design decision back
to a comparison: **computed value vs permissible limit**, where
the limit is a function of city + zoning + overlays + use.

---

## 2.2 The domain entities (and what shape they take)

| Entity | Shape | Source | Notes |
|---|---|---|---|
| **Plot** | 2-D polygon + area + road widths | SketchUp `Plot` group | Outer ring CCW; meters on the wire |
| **Building** | Stack of floors | SketchUp `Floor N` groups | Each floor: footprint polygon + height |
| **Floor** | Polygon + level + height_m + use | Group naming convention | Use defaults to `residential` |
| **Project context** | classification + zone + city + overlays | UI input + future GIS | Drives which rule pack applies |
| **Overlays** | Set of strings | Project context | e.g. `airport`, `heritage_influence`, `crz` |
| **Snapshot** | Plot + Building + Project + schema_version | Composed in Ruby, sent over HTTP | The DTO crossing the boundary |

The domain was deliberately kept thin: a plot, a stack of floors,
a project context. Anything more (rooms, units, services, lifts,
shafts) was deferred until it was needed by a specific evaluator.

---

## 2.3 FSI / FAR validation

### What it is

Floor Space Index (FSI), known as Floor Area Ratio (FAR) elsewhere,
caps the ratio of built-up area to plot area.

### Formula

```
FSI = total_built_up_area / plot_area
ok  = FSI ≤ max_fsi(city, classification, zone)
```

### Legacy formula (rejected)

```
FSI_legacy = (bbox_height / 3m) * (bbox_width * bbox_depth) / plot_area
```

This treats the bounding box as a rectangular prism, counts floors
as `round(height / 3 m)`, and assumes every floor has the same
footprint as the projection of the bbox onto the ground. Useful as
a sketch, **wrong** as compliance evidence.

> verbatim:
> *"The FSI formula `floor_count × estimated_footprint / plot_area`
> is a toy. Real FSI = `total_built_up_area / plot_area` where
> built-up is per-floor and excludes specific areas."*

### Real formula (shipped in `compliance/fsi.py`)

```python
total_built_up = sum(floor_area(f) for f in floors if is_habitable(f, params))
fsi            = total_built_up / plot_area
```

Where `is_habitable` honours per-rule opt-ins:

- Basement → excluded by default; opt-in via `params.include_basement`.
- Stilt → excluded by default; opt-in via `params.include_stilt`.
- Mezzanine → counted unless explicitly excluded.
- Balconies → counted (conservative default).

### Inputs

- Plot polygon (for `plot_area = polygon_area(plot)`).
- Floor polygons (for per-floor area, Shapely-based).
- Project classification + zone + city (to select `max_fsi`).
- Optional overlays (some overlays cap FSI further).

### Evaluator parameters

```json
{
  "max_fsi": 2.5,
  "include_basement": false,
  "include_stilt": false,
  "warn_near_limit_pct": 95
}
```

`warn_near_limit_pct` triggers a soft warning if the computed FSI
exceeds that fraction of the limit — a UX affordance flagged in
Sprint 3.

### Edge cases handled

- **Bowtie polygons**: Shapely rejects, not silently repaired
  (verbatim invariant from Sprint 3, commit `9841abf`).
- **Polygons with holes**: outer ring CCW, holes CW (GeoJSON
  convention) — area is signed-sum.
- **Mixed-use floors**: per-floor `use` field; future evaluator
  variants can apply different rules per use.

### Edge cases deferred

- **Service-area exclusions**: lifts, shafts, common areas. Requires
  a sub-polygon model (footprint with internal voids tagged by
  use). Roadmapped, not shipped.
- **Parking exemptions**: parking floors often don't count toward
  FSI. Handled coarsely today (via `include_stilt`); deserves a
  dedicated `use=parking` exclusion in a future evaluator.
- **FAR road-width premiums**: legacy `config/rules.json` carries
  these. Deferred — `Project.road_widths_m` is on the wire so a
  future `fsi_with_road_premium` evaluator can read it.

### Concrete example pinned by test

CBD / Residential, Bangalore, single test snapshot:

- Plot 20 m × 20 m → 400 m²
- Three identical 18 m × 18 m floors → 324 m² each → 972 m² total
- `FSI = 972 / 400 = 2.43`. Limit 2.5. **ok.**
- Same plot, four floors: `FSI = 1296 / 400 = 3.24`. **violation**:
  > *"FSI 3.24 exceeds the CBD/Residential limit of 2.5"*

(Earlier internal smoke ran with three 15 m floors yielding
`FSI 3.375` — same outcome.)

---

## 2.4 Setback validation

### What it is

Minimum distance between any part of the building footprint and the
plot boundary, possibly directional (front / rear / sides) and
possibly tiered by building height.

### Inputs

- Plot polygon.
- Building footprint polygons (per floor, but typically the ground
  floor is the binding one).
- Road width on each side (for front setback rules that scale with
  road width).
- Building height (for high-rise setback tiers).
- Project classification + zone.

### Geometry strategy

Setback validation reduces to:

```
plot_inner = plot.buffer(-required_setback, join_style="mitre")
ok         = footprint.within(plot_inner)
```

Equivalently:

```
distance_to_boundary = min(footprint.distance(edge) for edge in plot.exterior)
ok                   = distance_to_boundary >= required_setback
```

Both forms are implemented in `compliance/setback.py`; the inner-
buffer form is preferred because it correctly handles concave
plots.

### Why Shapely, specifically

Phase 1 found the legacy axis-aligned check. Real setback math
needs:

- **Polygon offsets** (inward buffer) — `Polygon.buffer(-d)`.
- **Distance to boundary** — `Polygon.distance(LineString)`.
- **Within-with-tolerance** — `prepared.contains(other)`.

These are exactly Shapely's wheelhouse. The decision to take
Shapely as a hard dependency was made in Phase 3 §3.6 on this
basis.

### Evaluator parameters

```json
{
  "min_setback_m": 2.0,
  "direction": "all",
  "height_tier_caps": [
    { "height_max_m": 15, "min_setback_m": 2.0 },
    { "height_max_m": 30, "min_setback_m": 4.5 }
  ]
}
```

The `height_tier_caps` form is roadmapped (legacy `rules.json` has
height-banded setbacks for high-rise) but the MVP ships with the
simpler `min_setback_m` form.

### Edge cases handled

- **Concave plots**: inner-buffer form handles them correctly.
- **Footprint touching boundary**: `within` is strict; touching =
  fail by default (matches bylaw intent — setback must be
  measurable).

### Edge cases deferred

- **Front-only setback** linked to road width: requires road
  identification (which edge of the plot is the front?). Plot
  ordering convention or explicit `Project.road_widths_m`
  per-edge is needed.
- **High-rise tiered setbacks**: see `height_tier_caps` above.
- **Setback exceptions for projections** (balconies, canopies,
  sunshades): treated as part of footprint today; future
  evaluator could subtract tagged projections.

### Concrete example pinned by test

CBD / Residential, plot 20 m × 20 m, footprint 18 m × 18 m
centered on plot:

- Required setback 2 m.
- Plot inset by 2 m → inner polygon 16 m × 16 m.
- Footprint 18 m × 18 m **does not fit** in 16 m × 16 m.
- Min distance from footprint to plot boundary: 1 m.
- **violation**: *"setback 1 m vs 2 m required."*

(Earlier internal example used an 18 m × 18 m footprint at the
plot edge — yielding `0 m vs 2 m`. Both shapes appear in tests.)

---

## 2.5 Ground coverage validation

### What it is

Maximum percentage of the plot that the building footprint may
occupy.

### Formula

```
coverage_pct = (footprint_area / plot_area) * 100
ok           = coverage_pct ≤ max_coverage_pct
```

### Inputs

- Plot polygon → `plot_area`.
- Ground-floor footprint polygon → `footprint_area`.
- Project classification + zone → `max_coverage_pct`.

### Evaluator parameters

```json
{ "max_coverage_pct": 60 }
```

### Edge cases handled

- **Multiple disconnected footprints**: union them via Shapely
  before computing area (`unary_union` then `.area`).
- **Footprint partially outside plot**: clipped to plot before
  area computation (`footprint.intersection(plot).area`). The
  excluded slice surfaces as a separate setback violation, not as
  coverage credit.

### Edge cases deferred

- **Cantilevered upper floors** (footprint of floor 2+ extends past
  ground floor): handled as setback issues today; future
  evaluator could enforce `max_coverage_pct` per floor band.

### Concrete example pinned by test

20 m × 20 m plot, 18 m × 18 m footprint:

- `coverage_pct = 324 / 400 = 81 %`.
- Limit 60 %. **violation**: *"coverage 81 % vs 60 % limit."*

---

## 2.6 Open space / landscape validation

### What it is

Minimum percentage of the plot that must remain unbuilt / available
for landscape.

### Formula

```
open_space_pct = ((plot_area - footprint_area) / plot_area) * 100
ok             = open_space_pct ≥ min_open_space_pct
```

Note: this is the **complement** of coverage. They're separate
evaluators because some bylaws distinguish "open space" (any
unbuilt area) from "landscape" (specifically planted area). The
MVP collapses both.

### Inputs

- Plot polygon.
- Ground-floor footprint.
- Project classification + zone.

### Evaluator parameters

```json
{ "min_open_space_pct": 25 }
```

### Edge cases handled

- Same as coverage (union of disconnected footprints, clip to
  plot).

### Edge cases deferred

- **Landscape vs paved open space**: distinguishing planted area
  from paved courtyards requires a separate ground-cover polygon
  layer. Out of MVP scope.
- **Shared open space across adjacent plots**: requires multi-
  plot snapshots. Out of MVP scope.
- **Stepped buildings**: every floor that recedes adds to open
  space at that level. Today only ground-floor footprint matters.

### Concrete example pinned by test

20 m × 20 m plot, 18 m × 18 m footprint:

- Open space = `(400 - 324) / 400 = 19 %`.
- Minimum 25 %. **violation**: *"open space 19 % vs 25 % required."*

---

## 2.7 Parking validation

### What it is

Minimum number of parking slots required, computed from use and
built-up area.

### Formula (MVP — simple ratio)

```
required = ceil(built_up_area / m2_per_slot) + ceil(required * visitor_pct / 100)
provided = count(parking_slots_in_snapshot)
ok       = provided ≥ required
```

### Inputs

- Sum of habitable built-up area (excluding service / parking).
- Per-use ratio table (residential vs commercial vs hotel, …).
- Visitor parking percentage (typically 10–20 %).
- Number of parking slots present (today: count from a future
  `Snapshot.parking_slots` field; MVP smoke tests pass `0`).

### Evaluator parameters

```json
{
  "m2_per_slot": 100,
  "visitor_pct": 10
}
```

### Why this is rule-engine-driven, not hard-coded

Legacy `config/rules.json` carries per-use parking ratios that
differ across residential / commercial / hotel / hospital /
theatre / industry. Hard-coding is intractable; the rule pack
solves it.

> verbatim:
> *"Parking rules are often use-specific, area-dependent, mixed-
> use aware, dynamically changing. Therefore parking must be
> rule-engine driven."*

### Edge cases handled

- **Mixed-use buildings**: per-floor `use` lets the evaluator
  compute required slots per use, then sum.
- **Small builds exempt**: a `min_built_up_for_parking_m2`
  threshold (deferred parameter) lets builds under a size escape
  the rule.

### Edge cases deferred

- **ECS** (equivalent car spaces) — bikes, scooters, EVs each have
  a fractional ECS. Out of MVP scope.
- **Slot dimensions** — the evaluator counts slots, not their
  geometric validity. Validating slot polygons (5 m × 2.5 m,
  manoeuvring aisle width, …) is a future evaluator.
- **EV charging trigger** — legacy `rules.json` requires charging
  points above a threshold. Future evaluator.
- **Per-unit forms** (rooms in a hotel, beds in a hospital, seats
  in a theatre): the use-keyed ratio handles area-based rules;
  per-unit rules need a new evaluator family.

### Concrete example pinned by test

Built-up 972 m² (three floors × 324 m²), residential, ratio 1 slot
per 100 m², visitor 10 %:

- Base required = `ceil(972 / 100) = 10`.
- Visitor = `ceil(10 * 0.10) = 1`.
- Total required = **11**. Provided 0. **violation**: *"parking
  0 vs 11 required."*

(An earlier example with a smaller building yielded `0 vs 5
required` for the same evaluator — the formula scales.)

---

## 2.8 Zone classification & overlays

### What it is

The project context (`classification`, `zone`, `city`, `overlays`)
determines which rules apply. Compliance is meaningless without
this context.

### Classification taxonomy (legacy seed)

- `Heritage` — historic core, strictest controls.
- `CBD` — central business district, balanced.
- `HDZ` — high-density zone, permissive on FSI.

### Zone taxonomy

- `Residential`, `Commercial`, `Industry`. (Mumbai pack adds
  `Mixed` indirectly via different rule cells.)

### Overlay taxonomy (introduced in Sprint 5)

- `airport` — height caps (Bangalore: 45 m; Mumbai pack: city-
  specific caps near runways).
- `heritage_influence` — Bangalore: 12 m height cap + stricter
  setbacks in the buffer around a heritage site.
- `crz` — Mumbai-only, Coastal Regulation Zone restrictions.

Overlays are an **additional dimension** on `applies_when`
predicates — not a rule-inheritance mechanism. A rule can declare
`applies_when.overlays_include: ["airport"]` to fire only inside
the airport buffer.

> verbatim from Sprint 7:
> *"`airport` overlay reused across both packs; `crz` stays
> Mumbai-only — proving overlay keys can be either shared or
> city-scoped."*

### City-isolation contract

Adding a new city is **pure data**, no code changes.

> verbatim from Sprint 7.1:
> *"Audit — engine is already city-agnostic; zero code changes
> needed."*

Mumbai support shipped as `mumbai-0.1.0.json` + `mumbai-0.2.0.json`
with no touch to evaluator code.

### Future GIS integration

Overlays today are project-context strings. The Phase 2 design
anticipates GIS overlays:

- Airport buffer = polygon around runway.
- Heritage buffer = polygon around heritage site.
- CRZ line = polygon along coastline.

In the future, `overlays` becomes a derived field: given the plot's
centroid (or full polygon), spatial-test against each overlay
polygon and emit the matching set. The `applies_when` matcher
doesn't change — only the way `overlays` is populated.

### Why this is a Python win

Spatial overlay matching benefits massively from Shapely +
GeoPandas + Fiona. Doing it in Ruby inside SketchUp would mean
porting GEOS to Ruby — none of which exists.

---

## 2.9 Height validation

### What it is

Maximum building height, possibly tightened by overlays (airport,
heritage).

### Formula

```
height_m = sum(floor.height_m for floor in floors)
ok       = height_m ≤ max_height_m(rule)
```

### Inputs

- Per-floor height (from `Floor.height_m` in the snapshot).
- Overlays (airport: 45 m; heritage: 12 m).

### Evaluator parameters

```json
{ "max_height_m": 45 }
```

### Edge cases handled

- **Floor heights vary**: `sum`, not `count × default`.
- **Overlay overrides base**: overlay rules have a higher priority
  than base zone rules. The rule engine fires both; the stricter
  one binds.

### Concrete example

Building 4 floors × 12 m = 48 m, airport overlay (45 m cap):

- **violation**: *"height 48 m vs 45 m airport limit."*

Same building, no airport overlay, CBD/Residential (no height
rule in base pack):

- **ok.**

---

## 2.10 Login system

### What it is

Pre-MVP step: authenticate before any compliance work. Future
licensing hooks here.

### MVP design

- Local users in SQLite (`User` table).
- Passwords hashed with bcrypt.
- JWT issued by `/auth/login`, carried as `Authorization: Bearer`
  on subsequent requests.
- Auto-seeded admin on first engine boot.

### Why bcrypt + JWT specifically

bcrypt is the standard for password hashing — slow by design,
salt-included, well-understood. PyJWT is the smallest viable JWT
library. The plugin doesn't need to verify JWTs (the engine
does), so the Ruby side just stores the string.

### No-leak invariant

> verbatim from Sprint 2:
> *"No-leak auth: identical message + timing-balanced bcrypt for
> 'no such user' vs 'wrong password'. Test enforces this; a
> regression would be silent and bad."*

The login response cannot distinguish "user doesn't exist" from
"password wrong". Both return the same error message after the
same bcrypt-time delay. An integration test asserts this and the
absence of `password_hash` in any response.

### Deferred

- Organization accounts.
- License-based activation.
- SSO / OAuth.
- Cloud sync.
- Audit log of who-validated-what (listed as 1-sprint follow-up).

---

## 2.11 Future PDF & diagram validation

The MVP does **not** ingest PDFs or diagrams. The design however
explicitly justifies the Python choice on this future-need basis:

> *"OCR libraries, NLP tooling, AI integrations, document parsing
> ecosystem."*

Future inputs:

- Municipal bylaw PDFs → OCR (`pytesseract`) → rule-pack drafts.
- Compliance certificates → parse, cross-check signatures.
- Architectural diagrams (scanned plans) → image-to-polygon →
  validate as if extracted from SketchUp.

A slot for this work exists at `planara_engine/adapters/` — empty
today (`__init__.py` only), reserved for OCR / GIS / DWG / IFC
adapters.

---

## 2.12 What this phase produced

By the end of Phase 2, the following were settled and carried into
Phase 3:

1. The **domain model** — Plot, Building (Floor stack), Project
   context, Overlays, Snapshot.
2. The **set of MVP evaluators** — FSI, setback, coverage, open
   space, parking, height. Six concerns; each maps to a Python
   module in `compliance/`.
3. The **evaluator parameterization** — each evaluator takes a
   typed `params` dict from its rule, never reads global config.
4. The **city-pack contract** — rule pack per city per semver,
   selected by `Project.city`, with overlays orthogonal.
5. The **deferred backlog** — service exclusions, road-width
   premiums, tiered setbacks, per-use parking forms, slot
   dimensions, EV charging, audit log, PDF ingestion, GIS, multi-
   plot, cantilever-aware coverage.

These were the inputs to Phase 3, which designed the runtime that
hosts them.
