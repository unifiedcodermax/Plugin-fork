# Sprint 0 — Pre-sprint: Legacy import & architecture lock

**Dates:** 2026-05-15 19:28–19:51 IST
**Version:** —
**Commits:** 9
**Headline:** Import the legacy SV-Abid Ruby prototype, write CLAUDE.md mapping it, and lock the hybrid architecture in `ARCHITECTURE.md`.

---

## Goal

Before any new code, get the existing prototype into the repo,
document what's there, and lock the target architecture so the
subsequent sprints have a single source of truth to build against.

This is the sprint that turned the ROLE prompt's Phase 1–4 design
work into committed artifacts on `main`.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `32acd16` | 19:28:19 | chore: initial project structure and plugin loader |
| `c728d0c` | 19:28:21 | feat: add plugin configuration files |
| `852500c` | 19:28:24 | feat: implement core calculation logic for FSI and setbacks |
| `402cd5d` | 19:28:27 | feat: add helper utilities and data point management |
| `5c5e6e5` | 19:28:31 | feat: implement SketchUp observers for model and entities tracking |
| `5fd5408` | 19:28:34 | feat: implement web-based user interface and dialogs |
| `92282ba` | 19:47:48 | docs: add CLAUDE.md mapping the legacy Ruby plugin |
| `7f7781e` | 19:51:02 | docs: define hybrid Ruby+Python target architecture |
| `3e93fad` | 19:51:28 | chore: expand .gitignore for Python toolchain artifacts |

The first six commits are the legacy Ruby prototype landing
unchanged. The last three are the design-output: `CLAUDE.md`
maps the legacy code; `ARCHITECTURE.md` defines the target;
`.gitignore` prepares for Python tooling.

---

## Deliverables

### Engine

None yet — engine is scaffolded in S1.

### Plugin (legacy import)

- `SV-Abid.rb` — extension registrar.
- `SV-Abid/main.rb` — active boot tree.
- `SV-Abid/abid_start.rb` — parallel boot tree (see [Phase 1 §1.3](../phase-1-to-4-architecture/01-reverse-engineering.md#13-two-parallel-boot-trees)).
- `SV-Abid/core/` — calculations (FSI from bbox), abid_fsi, abid_setback.
- `SV-Abid/helpers/datapoints.rb` — singleton state.
- `SV-Abid/helpers/hash_utils.rb` — load-time `UI.inputbox` side effect.
- `SV-Abid/config/` — `fsi-config.json`, `setback-config.json`, `rules.json`, `constants.rb`.
- `SV-Abid/observers/` — appObserver, modelObserver, entitiesObserver (not attached), toolsObserver (stub).
- `SV-Abid/ui/` — `display_ui.rb` (inline HTML) + `dialog.html` + `dialog.js` (parallel UI tree).

This code is preserved **unchanged** — no bug fixes, no refactors.
It serves as the reference baseline for Phase 1 reverse-engineering.

### Documentation

- `CLAUDE.md` — narrative map of the legacy code, including the
  two parallel boot trees, the `DataPoints` singleton, the
  load-time side effect in `hash_utils.rb`, the case-mismatch in
  `require_relative 'Observers/...'`, the `onTransactionEnd`
  arity bug, the trailing-comma `FSI_CONFIG_FILE` constant.
- `ARCHITECTURE.md` — the **target** architecture: hybrid
  Ruby plugin + Python sidecar; HTTP/JSON over localhost; meters
  on the wire; rule packs as versioned JSON per city; module
  layout for both sides.

---

## Files added/changed

```
+ SV-Abid.rb                                   (legacy)
+ SV-Abid/*                                    (legacy tree)
+ CLAUDE.md                                    (legacy reference)
+ ARCHITECTURE.md                              (target architecture)
+ .gitignore                                   (Python artifacts)
```

The legacy tree lives at the repo root for this sprint; it is
moved to `legacy/SV-Abid/` later, in S12 (commit `fef5cd0`).

---

## Tests added

None. No test runner exists yet for the legacy Ruby.

---

## Invariants locked

This sprint's main output isn't code — it's invariants that the
next 13 sprints will honor. Locked here:

- Hybrid architecture (Option C of the A/B/C analysis).
- Localhost HTTP/JSON for IPC.
- Pydantic as source of truth for the wire.
- Meters as the wire unit.
- Ruby is stdlib-only (no gems).
- Python stack: FastAPI + Pydantic + Shapely + SQLite +
  SQLModel + bcrypt + PyJWT + uvicorn.
- Push-to-main per commit; small descriptive commits.
- Rule packs as JSON per `{city}-{semver}`.

For the full list of locked decisions and rationales, see
[`05-decisions-log.md`](../phase-1-to-4-architecture/05-decisions-log.md).

---

## Risks mitigated

| Risk | How |
|---|---|
| R8 — two parallel boot paths | Legacy preserved in place; new code will use a single new entry (S1). |
| R9 — no tests, no CI, no lint | Toolchain ignored in `.gitignore`; will be added once Python code exists. |
| R1 — wrong business logic in legacy | Reverse-engineered into `CLAUDE.md` so the migration knows what *not* to port. |
| R7 — `rules.json` undocumented | Documented in `CLAUDE.md` as the "real ruleset" that the legacy runtime ignores. |

---

## Deferred from this sprint

- Actually building anything in Python — that's S1.
- Moving the legacy tree to `legacy/SV-Abid/` — that's S12, kept at
  the root for now to make it easy to compare against in early
  sprints.

---

## Why this sprint mattered

Without S0, every later sprint would have to re-litigate the
architecture. With S0 done, S1 can start by typing
`mkdir planara_engine` and following the module map in
`ARCHITECTURE.md` without further discussion.
