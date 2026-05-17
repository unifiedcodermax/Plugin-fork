# Phase 1 — Reverse Engineering & System Analysis

## 1.1 Goal of this phase

Before designing a migration, understand the existing system
completely. The ROLE prompt was emphatic:

> *"For EVERY file: explain purpose, responsibilities, dependencies,
> execution flow, SketchUp API usage, geometry handling, business
> logic, calculation logic, hidden coupling, side effects."*

This document is the record of that analysis. The legacy code is
preserved under `legacy/SV-Abid/` so every claim here is auditable
against on-disk source.

---

## 1.2 Top-level layout of the legacy plugin

```
legacy/SV-Abid/
├── abid_start.rb              ← legacy/parallel boot tree (UIManager)
├── main.rb                    ← active boot tree (init_plugin)
├── config/
│   ├── constants.rb
│   ├── fsi-config.json        ← FSI limits matrix
│   ├── setback-config.json    ← setback limits matrix
│   └── rules.json             ← real ruleset (NOT consumed by runtime)
├── core/
│   ├── calculations.rb        ← bbox-based height/FAR estimation
│   ├── abid_fsi.rb            ← FSILogic.check_fsi_compliance
│   └── abid_setback.rb        ← two parallel setback impls
├── helpers/
│   ├── datapoints.rb          ← @data_store singleton (mutable state)
│   └── hash_utils.rb          ← FARCalculator + load-time side effect
├── observers/
│   ├── appObserver.rb         ← onNewModel / onOpenModel
│   ├── modelObserver.rb       ← onTransaction* → recalc
│   ├── entitiesObserver.rb    ← debounce 0.5s (NOT wired in)
│   └── toolsObserver.rb       ← stub
└── ui/
    ├── input_ui.rb            ← UI.inputbox (active path)
    ├── display_ui.rb          ← inline HTML HtmlDialog
    ├── dialog.html            ← external HTML (legacy path)
    └── dialog.js              ← external JS (legacy path)
```

The case mismatch between `require_relative 'Observers/...'` calls
in `main.rb` and the actual `observers/` folder on disk is hidden
on macOS (case-insensitive filesystem) but **fails to load on
Linux / CI**.

---

## 1.3 Two parallel boot trees

Two distinct module trees both define `module SV_Abid`. They cannot
be loaded together cleanly:

### Active flow

```
SketchUp menu click
  └─ SV-Abid.rb  (extension registrar)
      └─ SV-Abid/main.rb
          └─ SV_Abid.init_plugin
              ├─ UIInput.show_input_dialog        (inputbox)
              ├─ DataPoints.getFSILimit           (reads fsi-config.json)
              ├─ DataPoints.getSetbackLimit       (reads setback-config.json)
              ├─ AppObserver.attach
              ├─ ModelObserver.attach
              ├─ ToolsObserver.attach             (stub)
              └─ Calculations.update_calculations
```

### Legacy/parallel flow

```
SV-Abid/abid_start.rb        (loaded but not required from main.rb)
  ├─ defines SV_Abid::UIManager
  ├─ registers a SECOND "Plugins → Abid" menu item
  └─ calls DataPoints.reset_data at module body level (line 17)
        ← runs at require time, not click time
```

When `abid_start.rb` is required, two side effects happen:

1. A second top-level menu item appears in `Plugins`, with its own
   dialog logic (`ui/dialog.html` via `HtmlDialog#set_file`).
2. `DataPoints.reset_data` fires at load time, wiping whatever the
   active flow has set up.

This is a load-order trap. The decision in Phase 3 was to abandon
both trees and bootstrap a single new entry point from
`planara_plugin/loader.rb`.

---

## 1.4 File-by-file analysis

### `SV-Abid.rb` (extension registrar)

- Registers the SketchUp extension via
  `SketchupExtension.new(...)` and `Sketchup.register_extension(...)`.
- Adds the `Plugins → Abid Building by laws (Bangalore)` menu item.
- Loads `SV-Abid/main.rb` lazily.
- Lifecycle: ONE menu item → ONE `init_plugin` call → observers wire
  up on first click.

### `main.rb` (active boot)

- Defines `module SV_Abid; def self.init_plugin; ... end; end`.
- Wires `AppObserver`, `ModelObserver`, `ToolsObserver` (note:
  `EntitiesObserver` is **commented out** — entity-level events
  do not flow through to recalculation).
- Calls `UIInput.show_input_dialog`, then `Calculations.update_calculations`.
- Contains a `start_bounding_box_timer` method that is **defined but
  never called** — dead code.
- Requires use a capital `O` (`require_relative 'Observers/appObserver'`)
  while the folder on disk is `observers/`. Case-sensitive
  filesystems fail; case-insensitive ones (default macOS)
  silently pass.

### `abid_start.rb` (legacy/parallel boot)

- Defines `SV_Abid::UIManager` — its own `setup` / `show_ui` /
  `update_panel` flow.
- Loads `ui/dialog.html` via `HtmlDialog#set_file`, not the inline
  HTML used by `UIDisplay`.
- Registers an **additional** `Plugins` menu item.
- Calls `DataPoints.reset_data` at module body (line 17) — a
  **load-time** side effect.
- Element IDs in `ui/dialog.html` (`locClassification`, `location`,
  `zone`, `plot_area`, `build_area`, `current_fsi`, `setbacks`) do
  **not** match the IDs in `ui/display_ui.rb` (`lblClassification`,
  `lblZone`, …). Updating one dialog without updating the other
  breaks the rendering silently.

### `core/calculations.rb`

- `Calculations.update_calculations(model)`:
  - Reads `model.entities` bounding box.
  - `model_height = bbox.height / 39.3701` (inches → meters).
  - `floor_count = (model_height / 3).round` (hard-coded 3 m).
  - `estimated_footprint = bbox.width * bbox.depth / 39.3701²`.
  - `built_up_area = floor_count * estimated_footprint`.
  - `far = built_up_area / plot_area`.
  - Writes everything into `DataPoints`.
- **Correctness verdict** (from the analysis):
  > *"The FSI formula `floor_count × estimated_footprint /
  > plot_area` is a toy. Real FSI = `total_built_up_area /
  > plot_area` where built-up is per-floor and excludes specific
  > areas."*
- **Bug**: `ModelObserver#onTransactionEnd` calls
  `Calculations.update_calculations` with **no arguments**, but
  the signature requires `model`. Transactions that hit only
  `onTransactionEnd` (not `onTransactionCommit`) raise
  `ArgumentError`.

### `core/abid_fsi.rb`

- `FSILogic.check_fsi_compliance` reads `:fsi` and `:fsi_limit` from
  `DataPoints`.
- Calls `UIDisplay.refresh_display`.
- Pops `UI.messagebox` on violation — a blocking modal that
  interrupts modeling. (Replaced in Sprint 6 by the HtmlDialog
  results panel.)

### `core/abid_setback.rb`

Two parallel implementations co-exist:

- `check_setback_compliance` — iterates each `Sketchup::Group`,
  computes corner points, uses `Geom::Point3d.point_to_line_distance`
  against plot edges.
- `get_setback_compliance` — iterates face vertices, checks
  `pt.x.abs < setback || pt.y.abs < setback`.

The second implementation is **axis-aligned only**: it assumes the
plot is centered at the origin and ignores the actual plot polygon.

> verbatim from the Phase 1 analysis:
> *"The setback check is axis-aligned only (`pt.x.abs < setback ||
> pt.y.abs < setback`), assumes the plot is centered at the origin,
> and ignores the actual plot boundary geometry."*

### `helpers/datapoints.rb`

- Singleton module with `@data_store = {}` mutable hash.
- API: `DataPoints.get(:key)`, `DataPoints.set(:key, value)`,
  `DataPoints.reset_data`.
- Also bundles: `getFSILimit`, `getSetbackLimit`,
  `convert_to_sq_meter`, `calculate_far`, `ensure_material`.
- `convert_to_sq_meter` switches on
  `model.options["UnitsOptions"]["LengthUnit"]` — the one piece of
  proper unit handling, but it's specific to area, not length.
- **Hazard**: two observer callbacks firing in quick succession
  can interleave reads/writes on `@data_store` with no transaction
  semantics.

### `helpers/hash_utils.rb`

- Defines `HashUtils.safe_dig(hash, *keys)` — a defensive nested
  hash reader.
- Defines `FARCalculator.calculate_far`.
- **Critical side effect**: at the bottom of the file (line 99) it
  *calls* `FARCalculator.calculate_far` — meaning *requiring* this
  file pops a `UI.inputbox` and runs an entire FAR computation.

> verbatim:
> *"`hash_utils.rb` is dangerous: requiring this file pops a
> `UI.inputbox` and runs an entire FAR computation as a load-time
> side effect."*

Treated as legacy/dead — never add a new `require_relative` path
to it.

### `config/constants.rb`

- Defines `FSI_CONFIG_FILE` with a trailing comma:
  ```ruby
  FSI_CONFIG_FILE = 'fsi-config.json',  # ← trailing comma
  ```
  This silently makes the constant a single-element **array**.
  Other call sites use literal `'fsi-config.json'` strings, so the
  bug is latent — but any code that tries to use the constant
  receives `['fsi-config.json']`.

### `config/fsi-config.json`

- `{classification → {zone → limit}}`.
- Classifications: `Heritage`, `CBD`, `HDZ`.
- Zones: `Residential`, `Commercial`, `Industry`.
- 9 cells total. Limits are FSI ratios (e.g. CBD/Residential → 2.5).
- This file is the **seed** that became `bangalore-0.1.0.json` —
  values pinned by test in commit `02d3932`.

### `config/setback-config.json`

- Same `{classification → {zone → limit}}` shape.
- Limits are minimum setback distances (meters).
- Same 9-cell coverage.

### `config/rules.json`

The **real** ruleset — far richer than what the runtime ever uses:

- FAR base + max values per classification/zone.
- Road-width premium tiers (extra FAR if the abutting road is wider
  than a threshold).
- Height-banded setbacks for high-rise (setbacks grow with
  elevation).
- Parking ratios by use (residential / commercial / industrial /
  hotel / hospital / theatre).
- EV charging triggers.
- Fire safety thresholds.
- Lift requirements.
- Heritage / CBD inheritance (`InheritsFrom: Standard`).

> verbatim:
> *"`rules.json` is the only file that resembles real bylaws (FAR
> premiums by road width, height-banded high-rise setbacks, parking
> by use). The runtime ignores it."*

Status: **declarative, complete, unused**. The Phase 2 plan was to
treat it as the source of truth for evaluator design, then port the
values into typed rule packs.

### `observers/appObserver.rb`

- `AbidAppObserver` — `onNewModel`, `onOpenModel`.
- Re-attaches `AbidModelObserver` to the new model.
- References `AbidEntityObserver` (the entities observer) but
  `main.rb` never requires it, so the reference is dangling.
- Re-opens the input dialog on a new model.

### `observers/modelObserver.rb`

- `AbidModelObserver#onTransactionCommit(model, ...)` →
  `Calculations.update_calculations(model)`. **Works.**
- `AbidModelObserver#onTransactionUndo(model, ...)` → same. Works.
- `AbidModelObserver#onTransactionEnd(...)` →
  `Calculations.update_calculations`. **Bug**: passes no argument.

### `observers/entitiesObserver.rb`

- `AbidEntityObserver` — debounces add / modify / remove at 0.5 s
  per `persistent_id`, calls `Calculations.update_calculations`.
- **Currently not attached** in `main.rb` (the require line is
  commented out), so entity-level events do not drive
  recalculation. The model observer's transaction events are the
  only signal.

### `observers/toolsObserver.rb`

- `AbidToolsObserver` — stub. Logs to console only.

### `ui/input_ui.rb`

- `UIInput.show_input_dialog` — plain `UI.inputbox` with three
  fields: classification, zone, plot area.
- Calls `DataPoints.getFSILimit` / `getSetbackLimit` to populate
  limits.
- Triggers first `Calculations.update_calculations`.

### `ui/display_ui.rb`

- `UIDisplay.refresh_display`:
  - Builds inline HTML.
  - Calls `dialog.set_html(...)`.
  - Calls `dialog.execute_script("document.getElementById('lblZone')...")`
    to update values.
- Element IDs used: `lblClassification`, `lblZone`, `lblFSI`,
  `lblSetback`, `lblHeight`, `lblFloors`, `lblBuildArea`.

### `ui/dialog.html` + `ui/dialog.js`

- External HTML loaded via `HtmlDialog#set_file` from
  `abid_start.rb`'s `UIManager`.
- Element IDs: `locClassification`, `location`, `zone`, `plot_area`,
  `build_area`, `current_fsi`, `setbacks`.
- **Different from `display_ui.rb` IDs**. The two dialogs are not
  interchangeable.

---

## 1.5 Module dependency graph (legacy)

```
                     SV-Abid.rb
                         │
                         ▼
                       main.rb ─────────────────┐
                         │                       │
            ┌────────────┼────────────┐          │
            ▼            ▼            ▼          ▼
       UIInput      AppObserver  ModelObserver  ToolsObserver
            │            │            │
            │            │            ▼
            │            │       Calculations ──┐
            │            │            │          │
            │            ▼            ▼          ▼
            └────────  DataPoints  FSILogic   UIDisplay
                          │            │
                          ▼            ▼
                 fsi-config.json   UI.messagebox
                 setback-config.json

  ─────── parallel/unwired ───────
  abid_start.rb  →  UIManager  →  ui/dialog.html (HtmlDialog)
  entitiesObserver.rb  (defined, not attached)
  hash_utils.rb  →  FARCalculator  (load-time side effect)
  rules.json     (declarative, never read)
```

Cycles: none. But the graph hides three traps:

1. `helpers/hash_utils.rb` is a load-time bomb.
2. `abid_start.rb` adds a second entry point if loaded.
3. `entitiesObserver.rb` is dead unless somebody re-attaches it.

---

## 1.6 Execution flow (active path)

```
User → Plugins → Abid menu item
   │
   ▼
SV_Abid.init_plugin
   │
   ├─ UIInput.show_input_dialog
   │     │
   │     ├─ inputbox: [classification, zone, plot_area_sq_m]
   │     ├─ DataPoints.set(:locationClassification, ...)
   │     ├─ DataPoints.set(:zone, ...)
   │     ├─ DataPoints.set(:plot_area, ...)
   │     ├─ DataPoints.getFSILimit(...)      → :fsi_limit
   │     └─ DataPoints.getSetbackLimit(...)  → :setback_limit
   │
   ├─ AppObserver.attach
   ├─ ModelObserver.attach
   ├─ ToolsObserver.attach    (stub)
   │
   └─ Calculations.update_calculations(active_model)
         │
         ├─ calculate_model_height(model)
         │     ├─ bbox = model.entities.parent.bounds
         │     ├─ height_m   = bbox.height / 39.3701
         │     ├─ floor_count = (height_m / 3).round
         │     └─ footprint_m2 = bbox.width * bbox.depth / 39.3701²
         │
         ├─ DataPoints.set(:fsi, floor_count * footprint_m2 / plot_area)
         │
         └─ FSILogic.check_fsi_compliance
               ├─ UIDisplay.refresh_display    (HtmlDialog values)
               └─ if fsi > fsi_limit: UI.messagebox(...)

User modifies model
   │
   ▼
AbidModelObserver#onTransactionCommit(model)
   └─ Calculations.update_calculations(model)
         └─ (same flow as above)

User undoes
   │
   ▼
AbidModelObserver#onTransactionUndo(model)
   └─ Calculations.update_calculations(model)

Some transactions hit onTransactionEnd
   │
   ▼
AbidModelObserver#onTransactionEnd
   └─ Calculations.update_calculations  ← raises ArgumentError (no model)
```

---

## 1.7 SketchUp API surface used by legacy

| API | Where | Purpose |
|---|---|---|
| `SketchupExtension.new` | `SV-Abid.rb` | Register extension |
| `Sketchup.register_extension` | `SV-Abid.rb` | Activate extension |
| `Sketchup.add_observer` | `main.rb` | Attach `AppObserver` |
| `model.add_observer` | `main.rb` | Attach `ModelObserver` |
| `Sketchup.active_model` | everywhere | Read current model |
| `model.entities` | `calculations.rb` | Geometry iteration |
| `model.entities.parent.bounds` | `calculations.rb` | Bounding box for height/footprint |
| `Sketchup::Group` / `Sketchup::ComponentInstance` | `abid_setback.rb` | Building footprint extraction |
| `Sketchup::Face` / `Sketchup::Edge` | `abid_setback.rb` | Vertex iteration |
| `Geom::Point3d.point_to_line_distance` | `abid_setback.rb` | Setback distance |
| `model.options["UnitsOptions"]` | `datapoints.rb` | Area unit detection |
| `UI.inputbox` | `input_ui.rb`, `hash_utils.rb` | Field entry |
| `UI.messagebox` | `abid_fsi.rb` | Violation alert |
| `UI::HtmlDialog` | `display_ui.rb`, `abid_start.rb` | Results panel |
| `dialog.set_html` / `dialog.set_file` | UI files | Render dialog content |
| `dialog.execute_script` | `display_ui.rb` | DOM updates |
| `UI.menu("Plugins").add_item` | `SV-Abid.rb`, `abid_start.rb` | Menu items |

This surface is the **untranslatable** portion. Everything that
touches `Sketchup::*` or `UI::*` must stay in Ruby; the rest can
move.

---

## 1.8 Bugs and smells catalogued (by name)

The Phase 1 audit catalogued every issue worth carrying into the
migration plan. Each entry was retained so Phase 4 could mitigate
it deliberately.

| # | Issue | Location | Severity | Carried into |
|---|---|---|---|---|
| 1 | Singleton mutable `@data_store` with no transactions | `helpers/datapoints.rb` | High | P4 §4.4 Risk 2 |
| 2 | Two parallel boot trees both register `Plugins` menu items | `main.rb` + `abid_start.rb` | Medium | Replaced wholesale by `planara_plugin/loader.rb` |
| 3 | Two HTML dialogs with mutually incompatible element IDs | `display_ui.rb` vs `dialog.html` | Medium | Replaced by single `planara_plugin/planara/ui/` shell |
| 4 | Load-time `UI.inputbox` in `hash_utils.rb` | `helpers/hash_utils.rb` line 99 | Critical | File abandoned, not ported |
| 5 | Case mismatch in `require_relative 'Observers/...'` | `main.rb` | Medium (Linux-only) | New code uses lowercase consistently |
| 6 | `onTransactionEnd` arity bug | `observers/modelObserver.rb` | High | New `LiveValidator` observer designed correctly |
| 7 | Trailing comma making `FSI_CONFIG_FILE` an array | `config/constants.rb` line 13 | Low (latent) | Constants no longer used |
| 8 | Hand-coded `/ 39.3701` inches→m conversions sprinkled | `core/calculations.rb`, `helpers/datapoints.rb` | High | Single conversion point at `planara_plugin/planara/geometry/units.rb` |
| 9 | FSI formula uses bbox, not real built-up area | `core/calculations.rb` | Critical | Real FSI evaluator in `compliance/fsi.py` |
| 10 | Setback check is axis-aligned, ignores plot polygon | `core/abid_setback.rb` | Critical | Shapely-based setback in `compliance/setback.py` |
| 11 | `EntitiesObserver` defined but not attached | `main.rb` | Medium | Replaced by `LiveValidator` with explicit debounce |
| 12 | `start_bounding_box_timer` defined but never started | `main.rb` | Low | Dead code, not ported |
| 13 | `rules.json` is the real ruleset, runtime ignores it | `config/rules.json` | Critical | Treated as authoritative seed in P2 |
| 14 | `UI.messagebox` blocks the modeling workflow | `core/abid_fsi.rb` | UX | Replaced by HtmlDialog results panel in S6 |
| 15 | No tests, no CI, no lint | — | High | Added via pytest + minitest + ruff + mypy + GitHub Actions |

Issues #9, #10, and #13 are the load-bearing ones: they prove the
legacy formulas are not trustworthy and the only complete rule
data is in a file the runtime never opens. That trio is what made
"shallow translation" the wrong strategy and forced a clean
rebuild against `rules.json` semantics.

---

## 1.9 Hidden coupling and side effects

Beyond named bugs, several less-obvious coupling patterns informed
the migration:

- **`DataPoints` as implicit global state**: any new code that
  reads `:fsi_limit` or `:setback_limit` is implicitly coupled to
  the order in which `UIInput.show_input_dialog` ran first. The
  new design's `Snapshot` Pydantic model carries everything
  explicitly.

- **Observer fan-out without ordering guarantees**: SketchUp can
  fire `onTransactionCommit` and `onTransactionEnd` for the same
  edit; the legacy code recomputes twice. New `LiveValidator`
  debounces at 500 ms per the design in Sprint 6.

- **Inputbox blocking on geometry events**: if
  `UIInput.show_input_dialog` is open when the user undoes,
  `AbidModelObserver` still fires and tries to call
  `update_calculations`. This is a latent race that the new design
  prevents by gating on `Session.authenticated?` and
  `Session.project`.

- **Trailing-call side effects**: `hash_utils.rb` runs FAR
  computation at require time. The cure is "don't require it" —
  it's not on any active path. But it means any future *grep
  through legacy* for FAR logic will find this dead branch first.

---

## 1.10 What was salvageable

The audit identified the following as reusable, with the caveats
noted:

| Asset | How it was reused |
|---|---|
| `config/fsi-config.json` | Values pinned by test into `rules/packs/bangalore-0.1.0.json` (commit `02d3932`). |
| `config/setback-config.json` | Values inherited into `bangalore-0.2.0.json` as `setback ≥ X m` rules. |
| `config/rules.json` | Treated as **authoritative spec** for Phase 2 — FAR premiums, height-banded setbacks, per-use parking are roadmapped. |
| Idea of `DataPoints` as single source of truth | Reimplemented as `Snapshot` Pydantic model — typed, immutable per request. |
| Observer-driven recalculation pattern | Kept as the live-validation paradigm. New `LiveValidator` replaces legacy observer fan-out. |
| Unit conversion intent | Centralized into `planara_plugin/planara/geometry/units.rb` (one conversion at the Ruby boundary). |

Everything else — calculation files, FSI/setback logic, the dual
UI tree, the `helpers/` files, the constants module — was abandoned
in place under `legacy/` rather than ported.

---

## 1.11 Verdict at the end of Phase 1

> *"Current numbers are not trustworthy. MVP must rebuild
> correctly, not port."*

That sentence — verbatim from the locked-decisions log — is the
output of Phase 1. It justifies the choice in Phase 4 to do an
architectural rebuild, not a syntax translation.
