# planara_plugin

Ruby thin shell that runs inside SketchUp. Talks to the Python
`planara_engine` sidecar over localhost HTTP.

See `../ARCHITECTURE.md` for the full system design.

---

## What lives in this folder

```
planara_plugin/
  loader.rb                # Top-level extension registrar
  planara/
    boot.rb                # Lifecycle wiring + menu items
    config.rb              # Plugin-side settings (engine URL, port, paths)
    engine_client.rb       # Net::HTTP client → planara_engine
    engine_supervisor.rb   # Spawn/healthcheck/stop the Python sidecar
    session.rb             # JWT + project metadata + last_report_id
    logger.rb              # Plugin-side logging helper
    geometry/
      extractor.rb         # Sketchup::* → JSON snapshot
      units.rb             # Inches ↔ meters conversion
    observers/
      live_validator.rb    # Debounced ModelObserver → /validate
    ui/
      login_dialog.rb      # HtmlDialog backed by assets/login.html
      results_dialog.rb    # Live-results panel backed by assets/results.html
      history_dialog.rb    # Recent runs list backed by assets/history.html
      browser_view.rb      # Open engine-rendered HTML in the default browser
test/
  test_extractor.rb        # Pure-data unit tests for extractor helpers
  test_units.rb            # Unit conversions
  test_engine_client.rb    # HTTP client stubbed at the transport seam
```

The legacy Ruby-only prototype lives under `../legacy/SV-Abid/`
and is preserved as a reference until the migration is fully
verified. New work should not extend it.

---

## Menu items

After activation (`Plugins → Planara — Compliance Check`), the
following submenu actions are also available:

- **Save current run** — extract the snapshot, post to `/history`,
  and stash the returned `report_id` on `Session` so the
  follow-on menu items can address it.
- **Recent runs…** — open the history HtmlDialog. Each row has
  "Open" (re-render the archive in your browser) and "vs prior"
  (auto-diff against the previous run with the same project
  context). Tick two rows to compare them pairwise.
- **Compare with last save** — save the current state, then
  fetch `/history/{id}/diff/html` and open it in the default
  browser. The marquee "did my last edit make things better or
  worse?" affordance.
- **Open last report in browser** — re-render the archive whose
  `report_id` is on `Session` and open it in the default
  browser.

---

## Install (development)

SketchUp loads extensions from its Plugins folder. Symlink (don't
copy) so edits in this repo are picked up after a SketchUp restart:

macOS:

```bash
ln -s "$PWD/planara_plugin/loader.rb"  \
      "$HOME/Library/Application Support/SketchUp 2024/SketchUp/Plugins/Planara.rb"
ln -s "$PWD/planara_plugin/planara"    \
      "$HOME/Library/Application Support/SketchUp 2024/SketchUp/Plugins/planara"
```

(Adjust `SketchUp 2024` for your version.)

Then in SketchUp: **Plugins → Planara** to boot the extension.

---

## Engine sidecar

The plugin expects to find a runnable `planara-engine` executable.
Two ways:

1. **Discoverable on PATH** (recommended for dev): activate the
   engine's virtualenv before launching SketchUp, or install the
   engine globally with `pipx install -e ./planara_engine`.
2. **Explicit path** via the `PLANARA_ENGINE_CMD` environment
   variable, e.g.
   `PLANARA_ENGINE_CMD="/abs/path/to/.venv/bin/planara-engine"`.

The supervisor will spawn the engine on plugin start and shut it
down when SketchUp exits.

---

## Conventions

- **Stdlib only.** SketchUp's Ruby is sandboxed and ships no gem
  manager. Use `net/http`, `json`, `uri`, `socket`, `fileutils`.
- **No top-level side effects.** `require`ing a file must not pop
  dialogs or hit the network. That bug is in the legacy code; we
  do not repeat it.
- **All public-ish state goes through `Planara::Session` or
  `Planara::Config`** — no module-level mutable globals.
- **Geometry is meters at the wire.** Unit conversion happens in
  the extractor (next sprint).
