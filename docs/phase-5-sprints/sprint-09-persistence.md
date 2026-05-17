# Sprint 9 — Persistence: ValidationReport table + reports repository + /history routes

**Dates:** 2026-05-17 03:41–04:51 IST (~70 min)
**Version:** 0.2.0-dev
**Commits:** 3
**Headline:** `ValidationReport` SQLModel persists validations; `POST /history` saves a report; `GET /history` lists paginated user-scoped; `GET /history/{id}` returns the full archive. User-scope isolation enforced at the repo layer.

---

## Goal

Make every validation run **persistable**. The user clicks "Save
current run", the engine stores the archive, and later list and
fetch endpoints expose the user's own history (and only their
own).

This is the foundation for diff (S10) and project navigation (S13).

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `5416977` | 03:41:43 | feat(engine/persistence): ValidationReport table for history |
| `6216021` | 04:02:20 | feat(engine/persistence): reports repository (save/list/get/count) |
| `eaf39c5` | 04:51:44 | feat(engine/api): /history — persist + list + fetch validation runs |

---

## Engine deliverables

### `ValidationReport` SQLModel

```python
class ValidationReport(SQLModel, table=True):
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="user.id", index=True)
    generated_at: datetime = Field(index=True)
    rule_pack_version: str = Field(index=True)

    # denormalized summary columns (indexed for filter/list views)
    city: str = Field(index=True)
    classification: str = Field(index=True)
    zone: str = Field(index=True)
    ok: bool = Field(index=True)
    violation_count: int = 0
    error_count: int = 0
    warning_count: int = 0

    # full archive as JSON
    payload: str  # serialized ArchivalReport
```

Indices:

- `(user_id, generated_at desc)` — primary list view.
- `(user_id, city, classification, zone, generated_at desc)` —
  auto-diff lookup (used in S10).

### Reports repository (`persistence/reports.py`)

> verbatim from `6216021`:
> *"Reports repository (save/list/get/count)."*

```python
class ReportRepository:
    def save(self, user_id, archive): ...
    def list(self, user_id, limit, offset, filters): ...
    def get(self, user_id, report_id): ...  # 404 if not exists OR not yours
    def count(self, user_id, filters): ...
    def latest_with_context(self, user_id, city, classification, zone, before): ...
```

### Endpoints

| Method | Path | Returns |
|---|---|---|
| POST | `/history` | `ArchivalReport` with the new `report_id` |
| GET | `/history` | Paginated list (most-recent first), filterable |
| GET | `/history/{id}` | Full `ArchivalReport` |
| GET | `/history/html` (deferred to S10) | Listing in HTML |
| GET | `/history/{id}/html` | Same as `/history/{id}` but rendered HTML |

### Pagination

> verbatim:
> *"Pagination capped at 100 via FastAPI `Query(le=100)`."*

```python
@router.get("/history")
def list_history(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    ...
)
```

### Filters

`GET /history?city=Bangalore&classification=CBD&zone=Residential&ok=false`

All filters are optional. Combined with `AND`.

### User-scope isolation

> verbatim:
> *"User-scope isolation enforced at the repo layer (`user_id`
> filter on every read) so 404 means the same thing whether the
> report doesn't exist or belongs to someone else."*

Every read in `ReportRepository` filters by `user_id`. There is
no `get_by_id_unrestricted` — the only API to fetch by id
requires the requesting user's id and returns 404 if either:

- The id doesn't exist.
- The id exists but belongs to someone else.

A 403 would leak existence. 404 keeps the response shape
uniform.

### Source-of-truth invariant

> verbatim:
> *"Persisted `payload` is the source of truth — re-renders read
> it back, never re-evaluate."*

When `GET /history/{id}` returns the archive, the engine **does
not** re-run `evaluate`. The stored `payload` is what's returned.
This preserves audit fidelity: the report represents the engine's
verdict at the time of save, even if the rule pack later changes.

### Denormalized columns + portable storage

> verbatim:
> *"Denormalized summary columns (city/ok/counts) are indexed;
> full archive stays in `payload TEXT` so storage is portable to
> Postgres JSONB later."*

Indexed reads stay fast (filter by city + ok); full archive
stays portable (just TEXT today, JSONB tomorrow on Postgres).

---

## Tests added

- `tests/unit/test_reports_repository.py` — save / list / get /
  count, user-scope isolation, latest_with_context.
- `tests/unit/test_persistence_reports.py` — model invariants,
  indexed columns.
- `tests/integration/test_history.py` — POST + GET + paginate +
  filter + cross-user-404.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/persistence/reports.py
+ planara_engine/src/planara_engine/api/routes_history.py
~ planara_engine/src/planara_engine/persistence/models.py    (ValidationReport)
~ planara_engine/src/planara_engine/persistence/database.py  (table creation)
+ planara_engine/tests/unit/test_reports_repository.py
+ planara_engine/tests/unit/test_persistence_reports.py
+ planara_engine/tests/integration/test_history.py
~ planara_engine/src/planara_engine/api/app.py               (routes_history)
```

---

## Invariants locked

### D22 — User-scope isolation: 404 for "yours-or-others"

### D27 — `payload TEXT` source of truth; summary columns indexed

### D28 — Pagination capped at 100

See [`05-decisions-log.md`](../phase-1-to-4-architecture/05-decisions-log.md).

---

## Risks mitigated

| Risk | How |
|---|---|
| R14 — User A reads User B's history | `user_id` filter on every repo read. |

---

## Concrete example

```
POST /history (Bob's token)
  body: { Snapshot for Bangalore/CBD/Residential, FSI 3.1 }
→ 200 { report_id: "r1", ok: false, violations: [...], ... }

GET /history (Bob's token)
→ 200 { items: [{ id: "r1", ok: false, city: "Bangalore", ... }], total: 1 }

GET /history?city=Mumbai (Bob's token)
→ 200 { items: [], total: 0 }

GET /history/r1 (Bob's token)
→ 200 { full archive }

GET /history/r1 (Alice's token)
→ 404
```

---

## Deferred from this sprint

- Diff endpoint (S10).
- HTML list view (deferred to S10).
- Search by snapshot id.
- Export to CSV / PDF.
- Bulk delete.
- Soft-delete (today: no delete endpoint exists at all).

---

## Why the auto-diff lookup index matters now

The `(user_id, city, classification, zone, generated_at desc)`
index is created in this sprint, not used until S10. It exists
here because adding a multi-column index after a million rows is
expensive — better to put it in place before the table grows.
