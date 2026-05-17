# Sprint 1 — Foundation: Engine skeleton + Ruby thin shell

**Dates:** 2026-05-15 19:52–20:20 IST (~30 min)
**Version:** 0.1.0-dev
**Commits:** 5
**Headline:** A FastAPI app that boots, returns 200 on `/health`, and a Ruby plugin shell that knows how to spawn it.

---

## Goal

Get both sides of the hybrid architecture *running*, end-to-end,
with nothing but a health check. The point is to prove the wiring
— supervisor spawn, HTTP loopback, structured logging — works
before any compliance logic exists.

By the end of this sprint, typing "Planara" in SketchUp's Plugins
menu must spawn uvicorn, poll `/health` until it returns 200, and
mark the engine as ready.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `24b4ba2` | 19:52:53 | chore(engine): scaffold planara_engine Python package |
| `bc0db8c` | 19:54:03 | feat(engine/core): settings, structured logging, domain errors |
| `f1f25d1` | 19:55:21 | feat(engine/api): FastAPI app, health endpoint, request middleware |
| `3c07412` | 20:16:11 | test(engine): smoke tests for settings, errors, /health endpoint |
| `61113c7` | 20:20:21 | feat(plugin): Ruby thin shell — boot, supervisor, engine client |

---

## Engine deliverables

### `planara_engine/` package scaffolded

```
planara_engine/
  pyproject.toml             # FastAPI, uvicorn, pydantic, sqlmodel, bcrypt, PyJWT
  src/planara_engine/
    __init__.py
    cli.py                   # `planara-engine` command launches uvicorn
    core/
      settings.py            # Pydantic Settings (env-driven)
      logging.py             # structlog setup
      errors.py              # PlanaraError base, PlanaraHTTPException
    api/
      __init__.py
      app.py                 # FastAPI app, routers wired
      middleware.py          # X-Request-ID generation + echo
      errors.py              # exception handlers → JSON envelope
      routes_health.py       # GET /health → {"ok": true}
  tests/
    conftest.py
    unit/
      test_settings.py
      test_errors.py
    integration/
      test_health.py
```

### Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"ok": true}` |

### Settings (`core/settings.py`)

Env-driven via Pydantic Settings. Variables introduced:

- `PLANARA_ENGINE_HOST` (default `127.0.0.1`)
- `PLANARA_ENGINE_PORT` (default `8765`)
- `PLANARA_LOG_LEVEL` (default `INFO`)
- `PLANARA_DATABASE_URL` (default `sqlite:///./planara.db`)
- `PLANARA_JWT_SECRET` (auto-generated on first boot if absent)

### Error envelope

```json
{ "error": { "code": "...", "message": "...", "request_id": "..." } }
```

Established here so every later route conforms.

---

## Plugin deliverables

### `planara_plugin/` thin shell

```
planara_plugin/
  loader.rb                  # SketchUp entry point
  planara/
    boot.rb                  # Extension registrar, menu wiring
    config.rb                # Engine URL, port, timeouts, retry delays
    logger.rb                # Stdlib Logger wrapper
    session.rb               # Token + project state (skeleton)
    engine_supervisor.rb     # spawn / health-check / stop
    engine_client.rb         # Net::HTTP wrapper, JSON, auth header
```

### `EngineSupervisor` capabilities

1. **Spawn** — `Process.spawn("planara-engine", ...)`, capture PID.
2. **Health-check** — poll `GET /health` with exponential backoff
   (50 ms, 100 ms, 250 ms, 500 ms, 1 s) up to 15 s default.
3. **Adopt** — if a healthy engine is already on the configured
   port, adopt it instead of spawning a duplicate.
4. **Stop** — SIGTERM, wait 5 s, SIGKILL if still alive.

### `EngineClient` capabilities

- `get(path)` / `post(path, body)` over `Net::HTTP`.
- Attaches `Authorization: Bearer <token>` if `Session.token` is set.
- Generates and sends `X-Request-ID` per request.
- Translates the JSON error envelope to a Ruby exception.

### Menu

`UI.menu("Plugins")` gets a single "Planara" item that, on click,
starts the supervisor and pings the engine.

---

## Tests added

- `tests/unit/test_settings.py` — env override, defaults.
- `tests/unit/test_errors.py` — error envelope shape.
- `tests/integration/test_health.py` — TestClient GET `/health` → 200.

No plugin tests yet — minitest harness is added in S3 once the
plugin has something testable beyond stdout.

---

## Files added/changed

```
+ planara_engine/pyproject.toml
+ planara_engine/src/planara_engine/__init__.py
+ planara_engine/src/planara_engine/cli.py
+ planara_engine/src/planara_engine/core/{settings,logging,errors}.py
+ planara_engine/src/planara_engine/api/{app,middleware,errors,routes_health}.py
+ planara_engine/tests/{conftest,unit/test_settings,unit/test_errors,integration/test_health}.py
+ planara_plugin/loader.rb
+ planara_plugin/planara/{boot,config,logger,session,engine_supervisor,engine_client}.rb
+ planara_plugin/README.md
+ planara_engine/README.md
```

---

## Invariants locked

- Engine binds to `127.0.0.1` by default (loopback only).
- Every request gets an `X-Request-ID`; structured logs echo it.
- Error envelope shape is fixed.
- Plugin owns the engine lifecycle — user never sees uvicorn.
- Plugin adopts an existing healthy engine rather than
  duplicating.

---

## Risks mitigated

| Risk | How |
|---|---|
| R2 — SketchUp is Ruby-only | Hybrid topology is now real, not a sketch. |
| R10 — engine lifecycle instability | Supervisor with health-check + adopt-or-spawn + SIGTERM-then-SIGKILL. |
| R17 — sidecar zombies | Health-check on startup discovers orphans and adopts/replaces. |

---

## Deferred from this sprint

- No auth yet (S2).
- No domain models (S3).
- No `/validate` (S3).
- Plugin can't read SketchUp models yet (S3 extractor).
- No UI dialogs beyond a menu item (S2 login).

---

## Smoke verification

> verbatim from the sprint summary:
> *"`planara-engine` boots, /health returns 200, structured logs
> land in stdout, X-Request-ID echoed back."*

That single sentence is the success criterion for S1.
