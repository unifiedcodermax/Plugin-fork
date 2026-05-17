# Legacy — SV-Abid (Ruby-only prototype)

This folder holds the original SketchUp Ruby extension that lived at
the repo root until S12. It is kept here as a reference while the
new hybrid (Ruby plugin + Python engine) stabilizes — not as code
that ships.

## What's here

- `SV-Abid.rb` — the SketchupExtension registrar that points at
  `SV-Abid/main.rb`.
- `SV-Abid/` — the original module tree (`core/`, `helpers/`,
  `observers/`, `ui/`, `config/`). All FSI / setback / height logic
  that the new engine has since superseded.

The behaviour and gotchas of this tree are documented in
`../CLAUDE.md` (section "What this is" + the gotchas list).

## Status

- **Not loaded by the new plugin.** `planara_plugin/loader.rb` is
  the production entry point; `legacy/SV-Abid.rb` is no longer
  symlinked into SketchUp's Plugins folder.
- **No tests, no CI coverage.** New CI runs only against
  `planara_engine/` and `planara_plugin/`.
- **Will be deleted** once the new hybrid has been exercised on
  real models for one full sprint cycle without regressions
  attributable to missing legacy behaviour. Git history retains
  this code regardless (`git log -- legacy/`).

If you reach for this folder to crib bylaw-config values or a
calculation shape that hasn't been ported yet, file an issue
naming the gap — it usually means the new rule packs need a row,
not that we should ship a hybrid that calls back into here.
