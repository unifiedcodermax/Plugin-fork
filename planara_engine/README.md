# planara_engine

The Python compliance engine for Planara. A FastAPI service that
the Ruby SketchUp plugin talks to over localhost HTTP.

See `../ARCHITECTURE.md` for the full system design.

---

## Quickstart

```bash
cd planara_engine
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run the service
planara-engine
# or
uvicorn planara_engine.api.app:app --reload --port 8765
```

The service binds to `127.0.0.1:8765` by default. Override via
environment variables (see `planara_engine/core/settings.py`).

Health check:

```bash
curl http://127.0.0.1:8765/health
```

---

## Tests

```bash
pytest                          # all tests
pytest tests/unit/              # unit only
pytest -k fsi                   # everything FSI-related
pytest --cov=planara_engine     # with coverage
ruff check src tests            # lint
mypy src                        # type-check
```

CI runs `pytest`, `ruff check`, and `mypy` on every push and pull
request (`.github/workflows/ci.yml`).

---

## Routes

| Method | Path                              | Purpose                                             |
| ------ | --------------------------------- | --------------------------------------------------- |
| GET    | `/health`                         | Cheap liveness probe; no auth required              |
| POST   | `/auth/login`                     | Username + password → JWT                           |
| GET    | `/auth/me`                        | Identity of the bearer of the current JWT           |
| POST   | `/validate`                       | Evaluate a Snapshot, return violations + metrics    |
| POST   | `/reports`                        | Evaluate + render an `ArchivalReport` (JSON), no DB |
| GET    | `/reports/html`                   | Evaluate + render the same as standalone HTML       |
| POST   | `/history`                        | Like `/reports` but **persisted** — returns report_id |
| GET    | `/history`                        | Paginated list of the caller's saved runs           |
| GET    | `/history/{id}`                   | Fetch one stored archive (JSON)                     |
| GET    | `/history/{id}/html`              | Re-render that archive as HTML                      |
| GET    | `/history/{id}/diff`              | Auto-diff vs the most-recent prior (same context)   |
| GET    | `/history/{id}/diff/html`         | HTML variant of the auto-diff                       |
| GET    | `/history/diff?from=X&to=Y`       | Explicit pairwise diff (JSON)                       |
| GET    | `/history/diff/html?from=X&to=Y`  | Explicit pairwise diff (HTML)                       |

All `/history/*` routes are user-scoped via the JWT — a caller
cannot see another user's reports; both "missing" and "owned by
someone else" surface as 404 so the response shape doesn't leak
existence.

---

## Layout

```
src/planara_engine/
  api/          FastAPI app + routers (incl. /validate, /reports, /history)
  auth/         Local user store, JWT, password hashing
  core/         Settings, logging, errors, middleware
  domain/       Pydantic schemas — the Ruby↔Python contract
  rules/        Rule schema, loader, packs/ (Bangalore + Mumbai)
  engine/       RuleEngine — selects + dispatches rules
  compliance/   Evaluators: fsi, setback, coverage, open_space, parking, height
  geometry/     Shapely-backed polygon ops
  reporting/    HTML/JSON renderers + report-to-report diff
  persistence/  SQLModel — users, sessions, ValidationReport (history)
  adapters/     Future: PDF/OCR, GIS, CAD interop
tests/
  unit/         Per-module unit tests
  integration/  Full HTTP flows
  fixtures/     Golden snapshots & expected violations
```

---

## Conventions

- **Type-checked.** `mypy --strict` is part of the dev loop and CI.
- **Linted.** `ruff check` runs in CI; the rule set lives in
  `pyproject.toml`.
- **All public APIs are Pydantic models.** The schema is the
  contract.
- **Geometry is meters, always.** Ruby converts at extraction
  time.
- **Polygons follow GeoJSON ordering.** Outer ring CCW, holes CW.
- **No I/O in domain/.** Pure data; persistence and HTTP live
  elsewhere.
