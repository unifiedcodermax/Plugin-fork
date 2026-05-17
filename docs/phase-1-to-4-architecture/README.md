# Planara Plugin — Phase 1 to Phase 4

## Architecture & Migration Documentation

This folder captures the architectural thinking, reverse-engineering
analysis, domain analysis, system design, and migration strategy
that were completed **before** Sprint execution began on the Planara
plugin (SketchUp Ruby thin shell + Python FastAPI sidecar for
building-byelaw compliance validation).

The work was completed against a ROLE prompt that demanded:

> "You are NOT allowed to do shallow translation. You must behave
> like a senior engineer designing a real-world architecture/
> compliance platform."

Sprint 1 onwards (the execution) was driven from these decisions.
This documentation backfills the design record.

---

## Document set

| # | File | Phase | Scope |
|---|---|---|---|
| 0 | `README.md` (this file) | — | Index, conventions, how to read |
| 1 | [`01-reverse-engineering.md`](01-reverse-engineering.md) | Phase 1 | File-by-file analysis of `legacy/SV-Abid/`, bugs, coupling, observer wiring, execution flow |
| 2 | [`02-domain-analysis.md`](02-domain-analysis.md) | Phase 2 | FSI/FAR, setback, ground coverage, open space, parking, zoning — formulas, edge cases, evaluator decisions |
| 3 | [`03-python-architecture.md`](03-python-architecture.md) | Phase 3 | Option A/B/C, hybrid architecture, stack choice, module layout, rule engine, IPC, lifecycle, auth |
| 4 | [`04-migration-strategy.md`](04-migration-strategy.md) | Phase 4 | Risk register, what stays / changes / untranslatable, migration order, unit conversion, contract drift, git strategy |
| 5 | [`05-decisions-log.md`](05-decisions-log.md) | Cross-cutting | Verbatim locked decisions, rejected alternatives, key invariants, evolution per sprint |

A short summary version of this material — without the file-by-file
detail — lives at `docs/phase-1-to-4-architecture.md` (the earlier
single-file consolidation). Prefer this folder for any deep look.

---

## How to read this

- If you're **new to the project**, read `ARCHITECTURE.md` at the
  repo root first (target architecture), then jump into Phase 1
  here.
- If you're **proposing a change to the rule engine, evaluators, or
  rule packs**, read Phase 2 (domain) and Phase 3 §3.7 (rule
  schema).
- If you're **adding a new city or overlay**, read Phase 2 §2.8 and
  Phase 3 §3.7 — the contract for packs and overlays is laid out
  there.
- If you're **touching the Ruby ↔ Python contract**, read Phase 4
  §4.4 Risk 1 (contract drift) and Phase 3 §3.8 (DTO design).
- If you're **debugging a behavior difference vs the legacy
  prototype**, read Phase 1 — the legacy formulas and their bugs
  are catalogued by name.
- If you want **just the decisions**, read `05-decisions-log.md` —
  it's a flat list of "what was decided and why."

---

## Conventions used in these docs

- **File paths** are repo-relative.
  `legacy/SV-Abid/core/calculations.rb` refers to the preserved
  prototype; `planara_engine/src/planara_engine/...` and
  `planara_plugin/planara/...` refer to the active codebase.
- **Quoted prose** in *italics* or fenced blocks marked
  `> verbatim` is taken directly from the architecture discussion
  that produced Phase 1–4, preserved so future contributors can
  see the exact wording of the decision.
- **Commit SHAs** (e.g. `c81a278`, `02d3932`) refer to the engine
  + plugin Git history. Use `git show <sha>` to inspect.
- **Sprint numbers** S1–S13 are an internal sequencing. They do
  not map 1:1 to the 6-sprint outline in the original ROLE
  prompt (Phase 5) — execution extended through S13 because
  rule-pack work, plugin wiring, history/diff, and the `Project`
  entity each needed their own focused sprint. The mapping is
  documented in Phase 4 §4.5.

---

## Why this documentation exists

The original ROLE prompt set out an eight-phase deliverable
(reverse engineering → domain → architecture → migration → MVP
plan → implementation → testing → future scalability). Execution
prioritized Phase 5 onwards (working software, shipped on `main`,
with tests + CI), so Phases 1–4 were performed implicitly during
the foundational analysis turn but not written up as standalone
documents at the time.

This folder closes that gap. It does **not** rewrite history — it
records the reasoning that was already applied, with concrete
references to the legacy files that were analysed, the bugs that
were found, the alternatives that were rejected, and the
invariants that were locked.

If a future contributor asks "*why* is the FSI evaluator like
this?" or "*why* does the engine never see inches?" or "*why* did
we not just write the whole thing in Ruby?" — the answers live
here.

---

## Companion files outside this folder

- `ARCHITECTURE.md` — the **target** architecture (what got built).
- `CHANGELOG.md` — release-level record of what landed per sprint.
- `CLAUDE.md` — narrative of the legacy Ruby prototype as it
  exists on disk today (kept for in-IDE quick reference).
- `legacy/README.md` — context on why `SV-Abid/` is preserved.
