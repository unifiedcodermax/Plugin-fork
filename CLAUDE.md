# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A SketchUp Ruby extension ("Abid Building by laws (Bangalore)") that performs live compliance checks — FSI/FAR, setbacks, height — against Bangalore building bylaws as the user models in SketchUp. Requires SketchUp 2020+ (`Sketchup.version.to_i >= 20`).

## Build / run / install

There is no build system, package manager, lint, or test suite. To run the extension:

- Copy `SV-Abid.rb` and the `SV-Abid/` folder into SketchUp's `Plugins` directory (e.g. `~/Library/Application Support/SketchUp 2024/SketchUp/Plugins/` on macOS), then restart SketchUp.
- The plugin appears under `Plugins → Abid Building by laws (Bangalore)`. Selecting it calls `SV_Abid.init_plugin`.
- Iterating: use SketchUp's Ruby Console (`Window → Ruby Console`) to `load` files and inspect `puts` output. The codebase uses `puts` extensively for tracing — keep an eye on that console.

## Architecture

### Entry points (two parallel flows exist)

There are **two distinct module entry trees** that both define `module SV_Abid`. They are not currently both wired in from `SV-Abid.rb`, but file requires reference both. Be aware which one a change affects:

1. **Active flow** — `SV-Abid.rb` → `SV-Abid/main.rb` → `SV_Abid.init_plugin`. Registers observers and shows `UIInput.show_input_dialog`. This is what the menu item invokes.
2. **Legacy/alternate flow** — `SV-Abid/abid_start.rb` defines `SV_Abid::UIManager` with its own `setup` / `show_ui` / `update_panel` and its own `Plugins` menu item. It uses `ui/dialog.html` (via `HtmlDialog#set_file`) rather than the inline HTML in `ui/display_ui.rb`. It is not required from `main.rb` but registers its menu item if loaded.

When changing behavior, decide which flow you're modifying and don't accidentally fork them further.

### Data flow

`DataPoints` (`helpers/datapoints.rb`) is the **central in-memory state singleton** — a module-level `@data_store` hash holding `plot_area`, `fsi`, `fsi_limit`, `setback_limit`, `locationClassification`, `zone`, `height`, `floors`, `build`, etc. Everything reads from and writes to this one place via `DataPoints.get(:key)` / `DataPoints.set(:key, val)`.

Compliance limits are config-driven, keyed by `(locationClassification, zone)`:
- `config/fsi-config.json` — FSI limits for `Heritage|CBD|HDZ` × `Residential|Commercial|Industry`.
- `config/setback-config.json` — setback limits with the same key shape.
- `config/rules.json` — a richer ruleset (parking, EV charging, fire safety, lifts, heritage controls). **Not currently consumed by the Ruby code** — present for future use.
- `HashUtils.safe_dig` is the standard way to read nested config (`config/<classification>/<zone>`).

### Observer-driven recalculation

Modeling events drive recalculation, not timers (the timer in `main.rb#start_bounding_box_timer` exists but is not started):

- `AbidAppObserver` (`onNewModel` / `onOpenModel`) attaches the other observers and reopens the input dialog.
- `AbidModelObserver#onTransactionCommit` / `onTransactionUndo` / `onTransactionEnd` → `Calculations.update_calculations(model)`.
- `AbidEntityObserver` debounces add/modify/remove at 0.5s per `persistent_id`, then calls `Calculations.update_calculations`. Currently **not attached** in `main.rb` (the line is commented), so geometry-level events only flow through the model observer.
- `AbidToolsObserver` is a stub.

`Calculations.update_calculations` runs `calculate_model_height` (uses the active model's bounding box, estimates floor count from a 3 m default floor height, derives built-up area and FAR) and then `FSILogic.check_fsi_compliance`, which calls `UIDisplay.refresh_display` and pops a `UI.messagebox` on FSI violation.

### UI

Two HTML dialog implementations coexist:
- `ui/display_ui.rb` (`UIDisplay`) — inline HTML via `dialog.set_html`, populated by `execute_script` calls in `refresh_display`. This is what the active flow uses.
- `ui/dialog.html` + `ui/dialog.js` — external file loaded via `HtmlDialog#set_file` by `abid_start.rb`'s `UIManager`. Its element IDs (`locClassification`, `location`, `zone`, `plot_area`, `build_area`, `current_fsi`, `setbacks`) differ from the `UIDisplay` IDs (`lblClassification`, `lblZone`, …). When editing either dialog, update the matching `execute_script` JS or the rendering breaks silently.

`ui/input_ui.rb` (`UIInput.show_input_dialog`) is a plain `UI.inputbox` for classification, zone, and plot area — it also calls `DataPoints.getFSILimit` / `getSetbackLimit` to populate the limits before triggering the first `Calculations.update_calculations`.

## Gotchas worth knowing

- **`helpers/hash_utils.rb` executes `FARCalculator.calculate_far` at the bottom of the file (line 99).** That means *requiring* this file pops an `inputbox` and runs a calculation as a side effect of load — independent of the rest of the extension. Treat this as legacy/dead code; do not add new `require_relative` paths to it unless you also remove that trailing call.
- **Unit conversions are hand-coded.** SketchUp's internal length unit is inches; the code divides by `39.3701` to get meters. `DataPoints.convert_to_sq_meter` switches on `model.options["UnitsOptions"]["LengthUnit"]` for area conversions. Don't introduce a second convention.
- **Bug to watch for in `core/calculations.rb`**: `AbidModelObserver#onTransactionEnd` calls `Calculations.update_calculations` with no arguments, but the method signature requires `model`. Transactions that hit only `onTransactionEnd` (not `onTransactionCommit`) will raise.
- **`constants.rb` has a trailing comma after `FSI_CONFIG_FILE`** (line 13), which silently makes it an array constant. Code uses literal `'fsi-config.json'` / `'setback-config.json'` strings instead of the constants — preserve that or fix both sides.
- **Require-path casing matters.** `main.rb` requires `Observers/appObserver` etc. with a capital `O`, but the folder on disk is `observers/`. macOS's case-insensitive filesystem hides this; on case-sensitive filesystems (Linux CI, some Windows configs) it will fail to load.
- **No tests, no CI, no lint.** Verify changes by loading the extension in SketchUp and exercising the menu item with a real model.
