# planara_plugin

Ruby thin shell that runs inside SketchUp. Talks to the Python
`planara_engine` sidecar over localhost HTTP.

See `../ARCHITECTURE.md` for the full system design.

---

## What lives in this folder

```
planara_plugin/
  loader.rb              # Top-level extension registrar (sibling of legacy SV-Abid.rb)
  planara/
    boot.rb              # Lifecycle wiring
    config.rb            # Plugin-side settings (engine URL, port, paths)
    engine_client.rb     # Net::HTTP client → planara_engine
    engine_supervisor.rb # Spawn/healthcheck/stop the Python sidecar
    session.rb           # Holds the JWT after login
    logger.rb            # Plugin-side logging helper
```

Observers, geometry extraction, and UI screens will land in
later sprints. This folder coexists with the legacy `SV-Abid/`
tree — that tree stays untouched as a working reference until the
migration is fully verified.

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
