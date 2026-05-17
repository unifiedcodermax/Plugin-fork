# Sprint 13 — Project entity: making design identity first-class

**Dates:** 2026-05-17 13:59–14:00 IST (one big batch)
**Version:** 0.3.0-dev (in flight, uncommitted on the working tree as of doc-write date — see status below)
**Commits:** 6
**Headline:** Introduce a `Project` SQLModel; `Project` (project-context) renamed to `ProjectContext` for clarity; FK from `ValidationReport` to `Project`; `/projects` CRUD routes; plugin `ProjectPicker` HtmlDialog.

---

## Goal

Solve the auto-diff context collision. After S10, auto-diff
matches on `(user_id, city, classification, zone)` — but the
user can have **two different designs** in Bangalore/CBD/
Residential. With S13, designs are first-class `Project` rows;
auto-diff anchors on `project_id` instead of context tuple.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `cb3303b` | 13:59:48 | chore: add formatted-history.json to gitignore |
| `16727ea` | 13:59:54 | refactor(domain): rename Project to ProjectContext for clarity |
| `792f1d2` | 14:00:01 | feat(persistence): add Project entity and repository |
| `8616fc9` | 14:00:08 | feat(api): add /projects API routes and update history endpoints |
| `db31873` | 14:00:14 | chore(rules): adapt rule schema and tests to ProjectContext rename |
| `340650f` | 14:00:21 | feat(plugin): integrate project picker and anchor validations |

> **Status note:** at the time this documentation was written,
> these commits are on `main` but the working tree shows additional
> uncommitted churn from this sprint — the rename is rippling
> through tests. `git status` shows ~20 modified files in this
> family. The sprint is **landing**, not "landed". This doc
> reflects the locked design; treat specific file references as
> targets, not necessarily final paths.

---

## Engine deliverables

### Domain rename: `Project` → `ProjectContext`

> verbatim from `16727ea`:
> *"Rename Project to ProjectContext for clarity."*

The old `Project` Pydantic model carried the project *context*
(city, classification, zone, overlays) — not a project identity.
It's renamed `ProjectContext` to free `Project` for the actual
identity entity.

```
Old:  domain/project.py            → Project (city, classification, zone, overlays)
New:  domain/project_context.py    → ProjectContext (same fields)
      persistence/models.py        → Project (id, user_id, name, context)
```

### `Project` SQLModel

```python
class Project(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    name: str
    city: str = Field(index=True)
    classification: str
    zone: str
    overlays: str  # JSON-encoded list
    created_at: datetime
    updated_at: datetime
```

### `ValidationReport.project_id` FK

```python
class ValidationReport(SQLModel, table=True):
    # ...existing fields...
    project_id: UUID | None = Field(foreign_key="project.id", index=True)
```

Nullable for backward compatibility — reports saved before S13
have no project. New saves require a project.

### `/projects` routes

| Method | Path | Returns |
|---|---|---|
| POST | `/projects` | New project |
| GET | `/projects` | List user's projects |
| GET | `/projects/{id}` | Fetch project |
| PATCH | `/projects/{id}` | Update name / context |
| DELETE | `/projects/{id}` | Soft-delete (TBD) |

User-scope isolation (D22) applies identically — 404 for
other-user.

### Updated `/history`

`POST /history` now requires `project_id` in the request. The
auto-diff lookup anchors on `project_id` instead of
`(city, classification, zone)`.

`GET /history?project_id=<id>` filters by project.

---

## Plugin deliverables

### `ProjectPicker` (`ui/project_picker.rb`)

> verbatim from `340650f`:
> *"Integrate project picker and anchor validations."*

HtmlDialog with two modes:

- **Pick an existing project** — list of user's projects with
  per-row "Use".
- **Create a new project** — name + city + classification + zone +
  overlays. POSTs `/projects`, then uses the new project.

The selected `project_id` is stored in `Session.project_id` and
attached to every subsequent `/validate` / `/history` call.

### Menu wiring

- Planara → **Project…** opens `ProjectPicker`.
- Closing the picker without selecting cancels the operation;
  validation requires a project.

---

## Tests added

- `tests/unit/test_projects_repository.py` — CRUD, user-scope
  isolation, name uniqueness per user (TBD).
- `tests/integration/test_projects.py` — full `/projects`
  round-trip, cross-user 404s.
- `tests/integration/test_history.py` extended — `project_id`
  required on POST; auto-diff anchored on `project_id`.

(Rename ripples through every existing test that imported
`domain.project` — that's the 20-file churn visible in
`git status`.)

---

## Files added/changed

```
Renamed:
~ planara_engine/src/planara_engine/domain/project.py  → project_context.py

Added:
+ planara_engine/src/planara_engine/persistence/projects.py
+ planara_engine/src/planara_engine/api/routes_projects.py
+ planara_engine/tests/integration/test_projects.py
+ planara_engine/tests/unit/test_projects_repository.py
+ planara_plugin/planara/ui/project_picker.rb

Modified (rename ripples):
~ planara_engine/src/planara_engine/domain/__init__.py
~ planara_engine/src/planara_engine/domain/snapshot.py
~ planara_engine/src/planara_engine/persistence/models.py
~ planara_engine/src/planara_engine/persistence/database.py
~ planara_engine/src/planara_engine/persistence/reports.py
~ planara_engine/src/planara_engine/api/app.py
~ planara_engine/src/planara_engine/api/routes_history.py
~ planara_engine/src/planara_engine/rules/schema.py
~ planara_engine/src/planara_engine/core/errors.py
~ planara_engine/tests/integration/test_history.py
~ planara_engine/tests/unit/test_*.py  (rename imports)
~ planara_plugin/planara/boot.rb
~ planara_plugin/planara/engine_client.rb
~ planara_plugin/planara/session.rb
~ planara_plugin/planara/ui/history_dialog.rb
~ planara_plugin/test/test_engine_client.rb
```

---

## Invariants locked

### D29 — Project entity introduced post-MVP

> verbatim from the S13 planning:
> *"The auto-diff anchor `(city, classification, zone)` breaks
> the moment a user has two Bangalore/CBD/Residential designs. A
> real `Project` row solves it and unlocks better history
> navigation."*

### Auto-diff anchor evolves

Old: `(user_id, city, classification, zone)` → auto-diff.
New: `(user_id, project_id)` → auto-diff.

The old context-based lookup remains as a fallback for reports
saved before S13.

### `ProjectContext` is the wire-side type; `Project` is the persistence-side type

The Pydantic `ProjectContext` describes a *configuration* (what
rules apply). The SQLModel `Project` describes a *thing* the user
is designing. Conflating them in S3–S10 was acceptable; with
multi-design history, it isn't.

---

## Risks mitigated

| Risk | How |
|---|---|
| Auto-diff collisions across distinct designs sharing context | `project_id` anchor. |
| Cross-module rename hazard | Single sprint dedicated to it; CI catches stragglers. |

---

## Concrete user flow (new in S13)

1. User opens SketchUp, starts Planara.
2. Login dialog → JWT acquired.
3. **Project dialog** (new) → "Office Tower A" (Bangalore / CBD /
   Residential) created.
4. User models. `LiveValidator` runs. Save current run. `r1` is
   associated with project `p1`.
5. User starts a second design — back to **Project dialog** →
   "Office Tower B" (Bangalore / CBD / Residential — same context!).
6. User models. Save. `r2` associated with project `p2`.
7. User saves another iteration of A. `r3` associated with `p1`.
8. `GET /history/r3/diff` → auto-diff matches `r1` (same project),
   not `r2` (different project, same context).

Without S13, step 8 would have matched `r2` and produced a
meaningless "diff" between two unrelated designs.

---

## Status as of doc-write date

`git status` at the time of this documentation:

```
RM planara_engine/src/planara_engine/domain/project.py -> .../project_context.py
 M planara_engine/src/planara_engine/api/app.py
 M planara_engine/src/planara_engine/api/routes_history.py
 M planara_engine/src/planara_engine/core/errors.py
 M planara_engine/src/planara_engine/domain/__init__.py
 M planara_engine/src/planara_engine/domain/snapshot.py
 M planara_engine/src/planara_engine/persistence/database.py
 M planara_engine/src/planara_engine/persistence/models.py
 M planara_engine/src/planara_engine/persistence/reports.py
 M planara_engine/src/planara_engine/rules/schema.py
 M planara_engine/tests/integration/test_history.py
 M planara_engine/tests/unit/test_*.py
 M planara_plugin/planara/boot.rb
 M planara_plugin/planara/engine_client.rb
 M planara_plugin/planara/session.rb
 M planara_plugin/planara/ui/history_dialog.rb
 M planara_plugin/test/test_engine_client.rb
?? planara_engine/src/planara_engine/api/routes_projects.py
?? planara_engine/src/planara_engine/persistence/projects.py
?? planara_engine/tests/integration/test_projects.py
?? planara_engine/tests/unit/test_projects_repository.py
?? planara_plugin/planara/ui/project_picker.rb
```

The shape is locked; the rename ripple is being finalized.

---

## Deferred from this sprint

- Project soft-delete (today: hard delete or none).
- Project sharing between users.
- Project archival (read-only after a certain date).
- Project templates ("New CBD Residential project from template").
- Project-level reports (a summary across all the report runs in a
  project — average FSI, trend chart, etc.).
- Cloud project sync (out of MVP).

---

## After S13: what's next?

S13 closes the MVP-plus surface. After this, the deferred backlog
[Phase 4 §4.7](../phase-1-to-4-architecture/04-migration-strategy.md#47-what-was-deferred-and-why)
becomes the candidate set for S14+. The most valuable next sprints
by impact:

1. **In-model violation visualization** — highlight non-compliant
   edges back in SketchUp. UX win. 2–3 sprints.
2. **PDF report variant** — WeasyPrint, 1 sprint.
3. **More cities** — Delhi DCR, Chennai CMDA. 1 sprint each.
4. **FAR road-width premium evaluator** — `road_widths_m` already
   on the wire. 1 sprint.
5. **Audit log** — regulatory traceability. 1 sprint.

None of these are gated on architectural changes. The chassis
holds.
