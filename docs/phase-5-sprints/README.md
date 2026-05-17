# Phase 5 — Sprint Execution Log

This folder documents the **execution** of Phase 5 from the ROLE
prompt — the sprint-by-sprint MVP delivery, grounded in the actual
Git history.

Phases 1–4 (the design phase) are documented separately under
[`../phase-1-to-4-architecture/`](../phase-1-to-4-architecture/).
Phase 5 here is what happened **after** the architecture was
locked: every commit, every evaluator added, every endpoint
shipped, every test pinned.

---

## Sprint matrix

| # | Sprint | Dates (IST) | Version | Headline | Commits | Doc |
|---|---|---|---|---|---|---|
| S0 | Pre-sprint | 2026-05-15 19:28–19:51 | — | Legacy import + architecture lock | 9 | [sprint-00-pre-sprint.md](sprint-00-pre-sprint.md) |
| S1 | Foundation | 2026-05-15 19:52–20:20 | 0.1.0-dev | Engine skeleton + Ruby thin shell | 5 | [sprint-01-foundation.md](sprint-01-foundation.md) |
| S2 | Auth | 2026-05-16 05:10–06:15 | 0.1.0-dev | SQLite + bcrypt + JWT + login dialog | 6 | [sprint-02-auth.md](sprint-02-auth.md) |
| S3 | Domain + Rules + FSI | 2026-05-16 07:36–08:56 | 0.1.0-dev | Pydantic + Shapely + RuleEngine + FSI + Bangalore v0.1.0 + extractor | 8 | [sprint-03-domain-rules-fsi.md](sprint-03-domain-rules-fsi.md) |
| S4 | More evaluators | 2026-05-16 11:06–11:32 | 0.1.0-dev | Setback + coverage + open space + parking + Bangalore v0.2.0 | 5 | [sprint-04-setback-coverage-parking.md](sprint-04-setback-coverage-parking.md) |
| S5 | Overlays + Height | 2026-05-16 11:55–14:30 | 0.1.0-dev | Overlay applicability + height_limit + Bangalore v0.3.0 (airport, heritage_influence) | 5 | [sprint-05-overlays-height.md](sprint-05-overlays-height.md) |
| S6 | Live validation | 2026-05-16 16:48–18:44 | 0.1.0-dev | schema_version + Session.project + LiveValidator (500 ms) + Results dialog + contract tests | 6 | [sprint-06-live-validation.md](sprint-06-live-validation.md) |
| S7 | Mumbai pack | 2026-05-16 18:52–19:22 | 0.1.0-dev | Mumbai v0.1.0 + v0.2.0 (CRZ + airport) + pack-agnostic tests | 4 | [sprint-07-mumbai-pack.md](sprint-07-mumbai-pack.md) |
| S8 | Reporting | 2026-05-16 19:58–20:01 | 0.1.0 | HTML + ArchivalReport JSON, POST /reports, Accept-based content negotiation | 2 | [sprint-08-reporting.md](sprint-08-reporting.md) |
| S9 | Persistence | 2026-05-17 03:41–04:51 | 0.2.0-dev | ValidationReport table + reports repository + /history routes | 3 | [sprint-09-persistence.md](sprint-09-persistence.md) |
| S10 | Diff (regression tracking) | 2026-05-17 04:57–05:32 | 0.2.0-dev | diff_reports + /history/diff + diff HTML renderer | 3 | [sprint-10-diff.md](sprint-10-diff.md) |
| S11 | Plugin history wiring | 2026-05-17 05:55 | 0.2.0-dev | /history client + Recent runs UI + diff in browser | 1 | [sprint-11-plugin-history.md](sprint-11-plugin-history.md) |
| S12 | Cleanup + CI + 0.2.0 | 2026-05-17 09:50 | **0.2.0** | Legacy move + ruff/mypy green + GitHub Actions + CHANGELOG | 3 | [sprint-12-cleanup-ci-020.md](sprint-12-cleanup-ci-020.md) |
| S13 | Project entity | 2026-05-17 13:59–14:00 | 0.3.0-dev | Project entity + /projects + project picker + FK from ValidationReport | 6 | [sprint-13-projects-entity.md](sprint-13-projects-entity.md) |

**Totals at the time of writing:**

- 14 sprints (S0–S13), 66 commits on `main`.
- ~362 engine tests, plus minitest cases on the plugin side.
- 5 rule packs across 2 cities.
- 2 tagged releases (0.1.0, 0.2.0); 0.3.0 in flight.

---

## How to read

Each sprint doc has the same structure so you can scan them
quickly:

```
Goal               One paragraph
Commits            Table of SHAs, dates, subjects
Engine deliverables
Plugin deliverables
Files added/changed
Tests added
Invariants locked
Risks mitigated     (links to decisions log)
Deferred from this sprint
```

The numbers (commit SHAs, test counts, dates) come from the
actual repo — `git log` will confirm them.

---

## Conventions

- **Sprints are not fixed-length.** S8 was ~3 hours of work; S3
  was the densest end-to-end sprint. The lines were drawn by
  "did this complete a coherent capability?" — not by clock.
- **No release-train.** Versions bump when a meaningful surface
  ships (0.1.0 after S6 made the live-validation loop real;
  0.2.0 after S12 made history + CI real). Numbered as semver
  but applied to the engine + plugin together.
- **The user explicitly chose push-to-main per commit** for the
  whole MVP (see [decisions log §D5](../phase-1-to-4-architecture/05-decisions-log.md#d5--push-to-main-per-commit-small-descriptive-commits)).

---

## Mapping to the ROLE prompt's six-sprint plan

The ROLE prompt outlined six sprints. Execution extended to 13
sprints because: (a) auth deserved its own sprint, (b) plugin-side
wiring of history needed its own sprint, (c) cleanup/CI is its
own concern, (d) the Project entity (S13) emerged as necessary
once we had multi-design history.

| ROLE prompt sprint | Actual sprint(s) |
|---|---|
| S1 — Repo restructure + plugin boot + auth | S0 + S1 + S2 |
| S2 — Geometry extraction | S3 (partial — extractor) |
| S3 — FSI/FAR + setback | S3 (FSI) + S4 (setback) |
| S4 — Open space + parking | S4 |
| S5 — Zoning + overlays | S5 + S7 |
| S6 — Testing + reporting + PDFs | S6 + S8 + S9 + S10 + S11 + S12 (PDFs deferred) |
| — | S13 (projects, post-MVP) |

The ROLE prompt's "Sprint 6 — testing with compliance PDFs" was
deliberately deferred: PDF ingestion is in the `adapters/`
reserved slot and was scoped out of MVP. See
[Phase 4 §4.7](../phase-1-to-4-architecture/04-migration-strategy.md#47-what-was-deferred-and-why)
for the full deferred backlog.
