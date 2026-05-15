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
```

---

## Layout

```
src/planara_engine/
  api/          FastAPI app + routers
  auth/         Local user store, JWT, password hashing
  core/         Settings, logging, errors, middleware
  domain/       Pydantic schemas — the Ruby↔Python contract
  rules/        Rule schema, loader, packs/
  engine/       RuleEngine — selects + dispatches rules
  compliance/   Evaluators: fsi, setback, coverage, open_space, parking
  geometry/     Shapely-backed polygon ops
  reporting/    Violation aggregation, report rendering
  persistence/  SQLModel — users, sessions, projects
  adapters/     Future: PDF/OCR, GIS, CAD interop
tests/
  unit/         Per-module unit tests
  integration/  Full HTTP flows
  fixtures/     Golden snapshots & expected violations
```

---

## Conventions

- **Type-checked.** `mypy --strict` is part of the dev loop.
- **All public APIs are Pydantic models.** The schema is the
  contract.
- **Geometry is meters, always.** Ruby converts at extraction
  time.
- **Polygons follow GeoJSON ordering.** Outer ring CCW, holes CW.
- **No I/O in domain/.** Pure data; persistence and HTTP live
  elsewhere.
