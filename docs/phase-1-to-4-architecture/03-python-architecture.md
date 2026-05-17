# Phase 3 — Python Architecture Design

## 3.1 The architectural question that gates everything

The ROLE prompt explicitly required evaluating three options for
where the plugin runs:

- **Option A** — SketchUp plugin remains in Ruby; calls a Python
  backend over IPC.
- **Option B** — Replace the SketchUp plugin entirely (Python
  desktop app, no SketchUp).
- **Option C** — Hybrid: Ruby plugin + local Python sidecar +
  optional cloud.

Every other decision in this phase depends on this answer.

---

## 3.2 Option-by-option analysis

### Option A — Ruby plugin → Python backend (HTTP/IPC)

> verbatim from the foundational analysis:
> *"Feasible. Geometry extraction and observers stay in a thin Ruby
> layer; everything else (rule engine, validation, reporting, auth,
> persistence) is Python. SketchUp's Ruby has `Net::HTTP` baked in.
> Risk: serialization of geometry across the wire on every
> transaction commit could be slow if naive — mitigated by
> debouncing and sending diffs."*

**Pros**
- Clean separation of SketchUp concerns from compliance concerns.
- Python ecosystem (Shapely, Pydantic, FastAPI) becomes available.
- Net::HTTP is in SketchUp Ruby's stdlib — no gems needed.
- Backend is trivially deployable to a remote host.

**Cons**
- Per-transaction wire traffic.
- Process lifecycle complexity (someone has to run the Python).
- Two languages to maintain.

**Risk** — geometry serialization storm on every keystroke.
Mitigation: debounce (500 ms) in the Ruby observer.

### Option B — Replace plugin entirely (Python desktop app)

> verbatim:
> *"Not viable for the stated MVP. SketchUp doesn't load Python
> extensions. You'd have to import `.skp` files externally
> (limited via SDK), losing the live-design feedback loop that
> makes this useful."*

**Pros**
- Single language.
- Full Python ecosystem.

**Cons**
- **SketchUp does not embed Python.** No way to ship as a
  SketchUp plugin.
- Importing `.skp` externally requires the SDK (paid, limited).
- Lose the live "model is wrong, fix it now" UX entirely —
  designs round-trip through file export/import.
- The user's stated requirement is "live compliance checks as the
  user models." Option B kills that.

**Verdict: not viable.**

### Option C — Hybrid (Ruby plugin + Python sidecar)

> verbatim:
> *"Same as A in topology but the Python 'service' runs as a
> localhost process that the plugin spawns/connects to. Better
> than A for offline/desktop UX; identical code structure on the
> Python side."*

**Pros**
- All Option A benefits.
- Offline-capable (no remote dependency at runtime).
- Per-keystroke latency stays low (localhost loopback).
- Same Python code base also runs in cloud — no code change.
- Plugin manages lifecycle, so users see "Planara is ready" rather
  than "go install Python first."

**Cons**
- Plugin has to start/stop the sidecar reliably.
- Port allocation has to avoid conflicts.

**Risk** — sidecar lifecycle bugs (port conflicts, zombie
processes, crash recovery). Mitigation: `engine_supervisor.rb`
owns spawn / health-check / stop, with retry+backoff and SIGTERM-
then-SIGKILL.

### Decision

> verbatim:
> *"Recommendation: C (Hybrid) → degrades cleanly to A."*

Option C was selected because:

1. It satisfies the live-modeling UX (Option B's blocker).
2. It removes Option A's "Python isn't running" failure mode by
   making the plugin spawn its own engine.
3. It degenerates to Option A by changing one setting
   (`PLANARA_ENGINE_URL`) — so the cloud path is free.

This decision is the **load-bearing one** for all of Phase 3.

---

## 3.3 High-level topology

```
┌───────────────────────── SketchUp Process ────────────────────────────┐
│                                                                       │
│  planara_plugin/  (Ruby — thin shell, stdlib only, no gems)           │
│                                                                       │
│   ├─ loader.rb              Entry point loaded by SketchUp            │
│   ├─ boot.rb                Extension registrar, menu, lifecycle      │
│   ├─ config.rb              Engine URL, timeouts, debounce intervals  │
│   ├─ logger.rb              Stdlib Logger wrapper                     │
│   ├─ session.rb             JWT + project + last_report_id           │
│   ├─ engine_supervisor.rb   Spawn / health-check / stop the engine    │
│   ├─ engine_client.rb       Net::HTTP wrapper, JSON, auth header      │
│   ├─ observers/             Model/Entities/App observer wiring        │
│   │    └─ live_validator.rb 500ms-debounced validate loop             │
│   ├─ geometry/                                                        │
│   │    ├─ units.rb          inches/mm/feet → meters (one place)      │
│   │    └─ extractor.rb      Sketchup::* → Snapshot JSON               │
│   └─ ui/                                                              │
│        ├─ login_dialog.rb   HtmlDialog with assets/login.html         │
│        ├─ results_dialog.rb HtmlDialog with assets/results.html       │
│        ├─ history_dialog.rb HtmlDialog with assets/history.html       │
│        ├─ project_picker.rb Project selection dialog (S13)           │
│        ├─ browser_view.rb   Tempfile + UI.openURL for engine HTML     │
│        └─ assets/           Static HTML/CSS/JS, shipped with plugin   │
│                                                                       │
└──────────────────────────────┬────────────────────────────────────────┘
                               │ HTTP/JSON, localhost only
┌──────────────────────────────▼────────────────────────────────────────┐
│                                                                       │
│  planara_engine/  (Python 3.11+, FastAPI sidecar)                     │
│                                                                       │
│   src/planara_engine/                                                 │
│     api/        FastAPI routers (auth, validate, reports, history,    │
│                 projects), middleware (request-id), error envelope    │
│     auth/       Local user store, bcrypt, JWT mint/verify, deps       │
│     domain/     Pydantic schemas — Plot, Building, Floor, Snapshot,   │
│                 Violation, Response, ProjectContext, Overlay          │
│     rules/      Rule schema, JSON pack loader, packs/ per city        │
│     engine/     RuleEngine, evaluator registry                        │
│     compliance/ fsi.py, setback.py, coverage.py, open_space?,         │
│                 parking.py, height.py — one evaluator per concern     │
│     geometry/   Shapely-backed polygon ops (area, distance, offset)   │
│     reporting/  HTML renderer, archive shape, diff, diff_html         │
│     persistence/ SQLModel: User, ValidationReport, Project; database  │
│                 session, repositories                                 │
│     adapters/   Reserved for OCR / GIS / DWG / IFC (empty today)     │
│     core/       Settings, logging, errors, request-id middleware      │
│     cli.py      `planara-engine` uvicorn launcher                     │
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

---

## 3.4 Ruby layer responsibilities

The Ruby side is deliberately thin. It owns only:

1. **Extension registration** with SketchUp (`SketchupExtension.new`,
   `Sketchup.register_extension`).
2. **Menu wiring** — every menu item maps to a method on
   `Planara::Boot`.
3. **Observers** — `LiveValidator` attaches to `ModelObserver` with
   500 ms debounce.
4. **Geometry extraction** — discover `Plot` group + `Floor N`
   groups, build a `Snapshot` hash in meters.
5. **Unit conversion** — single place: `geometry/units.rb`. Handles
   inches / mm / cm / m / ft from SketchUp's `UnitsOptions`.
6. **UI** — `UI::HtmlDialog` screens for login, results, history,
   project picker.
7. **Engine lifecycle** — `EngineSupervisor` spawns uvicorn, polls
   `/health`, stops cleanly on quit.
8. **HTTP I/O** — `EngineClient` wraps Net::HTTP, attaches `Bearer`
   header, surfaces engine error envelope as Ruby exceptions.
9. **Session** — holds JWT + selected project + last report id in
   process memory.

The Ruby side **does not**:

- Compute any compliance metric.
- Decide which rule applies.
- Render violations (it shows what the engine returned).
- Persist anything.
- Hash passwords (the engine does).
- Verify JWTs (the engine does).

This split is enforced by the contract — the engine returns a
fully-rendered violations list with `message_template` already
substituted.

---

## 3.5 Python layer responsibilities

The engine owns:

- The **rule engine** (`engine/rule_engine.py`) — applicability
  matching and evaluator dispatch.
- **All evaluators** (`compliance/*.py`) — FSI, setback, coverage,
  open space, parking, height.
- **Rule packs** (`rules/packs/*.json`) — per-city, versioned JSON.
- **Geometry math** (`geometry/operations.py`,
  `geometry/normalize.py`) — Shapely-backed.
- **Auth** (`auth/`) — bcrypt, JWT, user store.
- **Persistence** (`persistence/`) — SQLite via SQLModel.
- **Reports** (`reporting/`) — HTML rendering, archival shape,
  diffing.
- **API** (`api/`) — FastAPI routers, OpenAPI docs.

The engine **does not**:

- Touch SketchUp.
- Read the user's filesystem outside its own data dir.
- Run any code from the plugin (no `exec`, no `eval`).

---

## 3.6 Tech-stack choices

### Why FastAPI

- **Typed** — Pydantic models become both validation and OpenAPI
  schemas.
- **Fast enough** — async + Starlette underneath; localhost
  loopback latency is sub-millisecond.
- **Test-friendly** — `TestClient` is built in.
- **Auto-docs** — `/docs` generated from Pydantic. Plugin
  developers can poke endpoints without a separate spec.
- **Future-proof** — same code works behind nginx or in a
  Kubernetes pod.

### Why Pydantic

- DTOs become the **contract**. Ruby mirrors as plain hashes; the
  engine validates on the way in.
- Used identically for HTTP I/O and internal models — no two-
  schema-system tax.

### Why Shapely

- The geometric operations needed (polygon area, distance,
  inward offset, intersection, union, within-test) are exactly
  Shapely's wheelhouse.
- GEOS underneath — production-grade, decades old.
- Bowtie / self-intersection detection is built in — used in
  `geometry/normalize.py` as the snapshot's entry gate.

> verbatim from Sprint 3:
> *"Shapely-backed geometry — area, union, inset (mitered),
> within, distance-to-boundary; bowtie polygon correctly rejected,
> not silently repaired."*

### Why SQLite + SQLModel

- **Local-first** — no daemon, no install, ships in-process.
- **Single file** (`planara.db`) — easy to back up, ship, inspect.
- **SQLModel** = SQLAlchemy + Pydantic — one model class for both
  ORM and HTTP.
- **Migration path** — SQLAlchemy underneath means a Postgres
  swap is a connection-string change plus migration testing.

### Why bcrypt + PyJWT

- bcrypt — standard, salted, slow-by-design, no algorithm
  surprises.
- PyJWT — minimal viable JWT library. Plugin never decodes the
  token, just stores the string and sends it back.

### Why uvicorn (not gunicorn, not raw asyncio)

- Single-process ASGI launcher.
- Plays well with `subprocess.Popen` from Ruby's `EngineSupervisor`.
- `--no-access-log` keeps stdout quiet for the supervisor to
  parse health probes.

### What was rejected

| Considered | Rejected because |
|---|---|
| gRPC for IPC | Adds protobuf toolchain; SketchUp Ruby can't import grpcio. HTTP/JSON wins on simplicity. |
| WebSockets | Bidirectional not needed; request/response model is sufficient. |
| Named pipes / Unix sockets | Less portable than TCP loopback; harder to debug. |
| Frontend framework inside HtmlDialog | "HtmlDialog is constrained" — limited DOM/JS environment. Plain HTML + vanilla JS works. |
| Ruby gems on the plugin side | SketchUp's Ruby is sandboxed — gems often fail to install. Stick to stdlib. |
| MongoDB / Postgres for MVP | Daemon to manage. SQLite has none of that overhead. |
| Argon2 instead of bcrypt | Bcrypt is more widely supported across Python versions; argon2 wins on theoretical grounds but bcrypt wins on practical grounds for MVP. |

### Tooling

- **Lint**: ruff (`E, F, W, I, B, UP, SIM, C4`).
- **Types**: `mypy --strict` (Shapely treated as untyped at one
  seam in `geometry/normalize.py`).
- **Tests**: pytest + httpx TestClient on engine; minitest on
  plugin.
- **CI**: GitHub Actions, Python matrix 3.11 / 3.12.

---

## 3.7 Rule engine design

### Rule schema

```json
{
  "id": "blr.fsi.cbd.residential",
  "city": "Bangalore",
  "applies_when": {
    "classification": "CBD",
    "zone": "Residential",
    "overlays_include": []
  },
  "category": "fsi",
  "evaluator": "fsi_limit",
  "params": { "max_fsi": 2.5 },
  "severity": "error",
  "message_template": "FSI {computed.fsi} exceeds limit {params.max_fsi} for {applies_when.classification}/{applies_when.zone}"
}
```

Fields:

- **`id`** — globally unique, dot-namespaced
  (`{city_short}.{category}.{classification_lower}.{zone_lower}`
  by convention).
- **`city`** — used by the loader to bucket packs.
- **`applies_when`** — predicate over `(classification, zone,
  overlays)`. All keys present must match; absent keys are wild.
- **`category`** — `fsi` / `setback` / `coverage` / `open_space` /
  `parking` / `height`. Used for grouping in reports.
- **`evaluator`** — function name registered in the evaluator
  registry. Each evaluator declares its own param shape.
- **`params`** — passed verbatim to the evaluator.
- **`severity`** — `error` or `warning`. Errors flip `ok=false`.
- **`message_template`** — Python `str.format`-style template,
  rendered through `_SafeDict` (verbatim Sprint 3, commit
  `5d01b1e`) so a typo'd key renders as `{wrong_key}` rather than
  500ing the request.

### Loader invariants

> verbatim from Sprint 3, commit `404993f`:
> *"Rule schema + JSON pack loader with versioning, applicability
> matcher, duplicate-id and bad-JSON guards."*

- **Duplicate-id guard** — two rules with the same `id` (even
  across packs) → load error.
- **Bad-JSON guard** — pack file with malformed JSON or missing
  required keys → load error with line number.
- **Version selection** — `load_pack("Bangalore", "0.3.0")` loads
  exactly that version; `latest_version("Bangalore")` picks the
  newest by **semver-aware** sort (deferred fix; lex sort works
  today for v0.x but breaks at v0.10).

### Engine dispatch

```python
def evaluate(snapshot: Snapshot) -> ValidationResponse:
    rules = load_pack(snapshot.project.city)
    applicable = [r for r in rules if matches(r.applies_when, snapshot.project)]
    violations = []
    metrics = {}
    for rule in applicable:
        evaluator = registry[rule.evaluator]
        result = evaluator(snapshot, rule.params)
        metrics.update(result.metrics)
        if result.violated:
            violations.append(render_violation(rule, result))
    return ValidationResponse(
        snapshot_id=snapshot.snapshot_id,
        ok=not any(v.severity == "error" for v in violations),
        violations=violations,
        metrics=metrics,
    )
```

The registry pattern means new evaluators are pure-additive:
register a function, write rules that reference it, ship. No
engine changes.

### Versioning policy

- Packs named `{city}-{semver}.json` under `rules/packs/`.
- `bangalore-0.1.0.json` is preserved even though `0.3.0` exists —
  for **version-pinning evidence** in tests.
- Cross-pack version bumps are independent: Bangalore can be at
  0.3.0 while Mumbai is at 0.2.0.

---

## 3.8 DTO design (the wire contract)

### Why this is critical

The wire format is the single most load-bearing artifact in the
system. Drift between Ruby's emitted JSON and Python's Pydantic
models silently breaks every downstream evaluator.

Mitigation: Pydantic is the **source of truth**; tests on both
sides pin the shape.

### Snapshot (Ruby → Python)

```json
{
  "snapshot_id": "uuid",
  "schema_version": "1.0",
  "project": {
    "city": "Bangalore",
    "classification": "CBD",
    "zone": "Residential",
    "overlays": ["airport"]
  },
  "plot": {
    "polygon": [[0, 0], [20, 0], [20, 20], [0, 20]],
    "area_m2": 400.0,
    "road_widths_m": { "front": 12.0 }
  },
  "building": {
    "floors": [
      { "level": 0, "polygon": [[1, 1], [19, 1], [19, 19], [1, 19]], "height_m": 3.2, "use": "residential" },
      { "level": 1, "polygon": [[1, 1], [19, 1], [19, 19], [1, 19]], "height_m": 3.0, "use": "residential" }
    ],
    "total_height_m": 6.2
  }
}
```

**Invariants:**

- All lengths in **meters**.
- Outer ring CCW, holes CW (GeoJSON convention).
- `polygon` is `list[list[float]]` of `[x, y]`. Z is dropped — 2-D
  validation only.
- `schema_version` defaults to `"1.0"`; engine **warns on mismatch
  instead of rejecting**, so older plugins keep working.

### Validation response (Python → Ruby)

```json
{
  "snapshot_id": "uuid",
  "ok": false,
  "violations": [
    {
      "rule_id": "blr.fsi.cbd.residential",
      "severity": "error",
      "category": "fsi",
      "message": "FSI 3.24 exceeds limit 2.5 for CBD/Residential",
      "computed": { "fsi": 3.24, "limit": 2.5 }
    }
  ],
  "metrics": {
    "fsi": 3.24,
    "coverage_pct": 81.0,
    "open_space_pct": 19.0,
    "min_setback_m": 0.0,
    "height_m": 6.2,
    "parking_required": 11,
    "parking_provided": 0
  }
}
```

**Invariants:**

- `message` is the rendered template — Ruby displays as-is.
- `computed` carries the values that drove the verdict (for
  display).
- `metrics` is a flat dict — the plugin shows the summary line.

### Schema version evolution policy

> verbatim from Sprint 6.1:
> *"`Snapshot.schema_version` (default '1.0', warns on mismatch
> instead of rejecting)."*

Chosen over hard rejection so older plugins keep working while the
engine evolves. Reverse compatibility (engine sees a newer schema
than it knows) raises an explicit `415 Unsupported Schema`.

### Archive (history) shape

> verbatim from Sprint 8/9:
> *"`ArchivalReport.report_schema_version` is decoupled from
> `Snapshot.schema_version` so the archive format can evolve
> independently."*

```json
{
  "report_id": "uuid",
  "report_schema_version": "1.0",
  "generated_at": "2026-05-17T12:34:56Z",
  "rule_pack_version": "bangalore-0.3.0",
  "snapshot": { ... },
  "response": { ... }
}
```

This is what `/history` and `/reports` return. The engine
**re-runs `evaluate`** on the snapshot rather than trusting any
client-supplied `response` payload — server-side invariant from
Sprint 8.

---

## 3.9 IPC strategy

### Choice: localhost HTTP/JSON

Reasons (verbatim):

> *"Same as A in topology but the Python 'service' runs as a
> localhost process… HTTP/JSON over localhost. Same transport
> works for future cloud deployment. Standard auth (Bearer JWT)
> plugs in cleanly. Tooling (OpenAPI, Postman) is free."*

### Loopback binding

The engine binds to `127.0.0.1:<port>` by default. Not `0.0.0.0`.
Other machines on the LAN cannot talk to it without an explicit
config change. Auth is still required regardless.

### Port allocation

- Configurable via `PLANARA_ENGINE_PORT` env var.
- Default `8765` (arbitrary).
- `EngineSupervisor` retries on bind failure with a port-bump
  strategy (deferred — today a port conflict surfaces as a startup
  error).

### Wire format

- JSON over HTTP.
- `Content-Type: application/json`.
- `Authorization: Bearer <jwt>` on everything except `/health` and
  `/auth/login`.
- `X-Request-ID` echoed back by the middleware — used by
  structured logs on both sides.

### Error envelope

```json
{
  "error": {
    "code": "validation_failed",
    "message": "polygon is self-intersecting (bowtie)",
    "request_id": "..."
  }
}
```

The plugin translates these to Ruby exceptions in
`EngineClient`. The contract is pinned by 13 minitest cases (per
the CHANGELOG entry for 0.2.0).

---

## 3.10 Engine lifecycle management

`engine_supervisor.rb` owns:

1. **Spawn** — `Process.spawn("planara-engine ...", [...])`,
   capturing PID.
2. **Health-check** — poll `GET /health` with exponential backoff
   (50 ms, 100 ms, 250 ms, 500 ms, 1 s, …) up to a configurable
   timeout (default 15 s).
3. **Reuse** — if a process is already listening, the supervisor
   adopts it instead of spawning a duplicate.
4. **Stop** — on SketchUp `onQuit`, send SIGTERM, wait up to 5 s,
   then SIGKILL.
5. **Restart** — on health-check failure during operation, mark
   degraded, restart with backoff, surface a UI banner if
   degraded for >30 s.

### Why the plugin owns this

The user shouldn't have to know what "uvicorn" is. The plugin
hides the engine entirely. The user clicks "Planara"; the engine
appears.

This is the difference between **Option A** ("install Python first
and run it") and **Option C** ("click the menu item"). C wins on
UX entirely because of this supervisor.

---

## 3.11 Auth design

### The login flow

```
User clicks Planara → Login
  │
  ▼
HtmlDialog (login.html) collects email + password
  │
  ▼
EngineClient.login(email, password)
  └─ POST /auth/login  { email, password }
       │
       ▼
  auth/service.py
    ├─ users repository: SELECT * FROM users WHERE email=?
    ├─ bcrypt.verify(password, user.password_hash)
    └─ jwt.mint(user_id, exp=now+30d)
       │
       ▼
  { access_token, expires_at }
  │
  ▼
Session.token = access_token
Session.user_id = ...
```

### No-leak invariants

- The `users` lookup and the bcrypt verify run **even if no user
  exists** — using a fixed bcrypt hash to keep timing constant.
- The error message is the same string for both failure modes.
- An integration test asserts that `password_hash` never appears
  in any response body (`/auth/login`, `/auth/me`, or anywhere
  else).

### JWT lifetime

- Default 30 days; signed with HS256.
- Secret read from `PLANARA_JWT_SECRET` env var, generated on
  first boot if absent and persisted to a dotfile.

### Session boundaries

The plugin's `Session` object lives in process memory. It carries:

- `token` — JWT string.
- `user_id` — convenience copy.
- `project` — the active project context (city/classification/
  zone/overlays).
- `last_report_id` — populated after each "Save current run"; powers
  the "Open last report in browser" menu item.

`Session` does **not** persist across SketchUp restarts. A new
session means a new login.

---

## 3.12 Reporting & history (designed in Phase 3, shipped S8–S10)

The report surface was designed up-front (even though most of it
shipped in S8–S10) because the persistence shape needed to be
locked before evaluator outputs were finalized.

Surfaces:

- **`/validate`** — stateless. Snapshot → response.
- **`/reports`** — wraps a validate result in `ArchivalReport`
  without DB write. `Accept: text/html` renders standalone HTML.
- **`/history` (POST)** — `/reports` + insert row in
  `ValidationReport`. Returns the new `report_id`.
- **`/history` (GET)** — paginated list, user-scoped, filterable
  by `city`, `classification`, `zone`, `ok`.
- **`/history/{id}`** — full archive.
- **`/history/{id}/diff`** — auto-diff against the most recent
  prior report with the same `(user_id, city, classification,
  zone)` context.
- **`/history/diff?from=&to=`** — explicit diff.
- HTML variants of all the above for opening in a browser.

### Diff invariants (S10)

> verbatim:
> *"Identification by `rule_id`; message-only differences are
> ignored (those are rule-pack edits, not regressions). Verdict is
> set-membership only — 'changed' surfaces in `summary['changed']`
> for the UI but doesn't flip the overall direction. Auto-diff
> context-match is `(city, classification, zone)`, not
> `snapshot_id` (each save gets a fresh snapshot_id from the
> plugin). User-scope isolation extends to diffs: another user's
> report ID returns 404 from either side. Route ordering:
> `/history/diff` registered before `/history/{id}` so FastAPI
> doesn't try to parse 'diff' as a UUID."*

### Persistence invariants (S9)

> verbatim:
> *"Persisted `payload` is the source of truth — re-renders read
> it back, never re-evaluate. User-scope isolation enforced at the
> repo layer (`user_id` filter on every read) so 404 means the
> same thing whether the report doesn't exist or belongs to
> someone else. Denormalized summary columns (city/ok/counts) are
> indexed; full archive stays in `payload TEXT` so storage is
> portable to Postgres JSONB later. Pagination capped at 100 via
> FastAPI `Query(le=100)`."*

---

## 3.13 Module map (final)

```
planara_engine/src/planara_engine/
├── api/
│   ├── app.py              FastAPI app, routers wired
│   ├── middleware.py       Request-ID, logging
│   ├── errors.py           Exception → error envelope translation
│   ├── routes_auth.py
│   ├── routes_health.py
│   ├── routes_validate.py
│   ├── routes_reports.py
│   ├── routes_history.py
│   └── routes_projects.py  (S13, in-flight)
├── auth/
│   ├── service.py          Login, register
│   ├── tokens.py           JWT mint/verify
│   ├── passwords.py        Bcrypt hash/verify
│   └── deps.py             FastAPI dependency for `current_user`
├── compliance/
│   ├── fsi.py
│   ├── setback.py
│   ├── coverage.py
│   ├── parking.py
│   ├── height.py
│   └── params.py           Shared param dataclasses
├── core/
│   ├── settings.py         Pydantic Settings, env vars
│   ├── logging.py          Structlog setup
│   └── errors.py           Domain exceptions
├── domain/
│   ├── plot.py
│   ├── building.py
│   ├── geometry.py
│   ├── violation.py
│   ├── snapshot.py
│   └── project_context.py  (renamed from project.py, S13)
├── engine/
│   ├── rule_engine.py
│   └── registry.py
├── geometry/
│   ├── operations.py       Shapely-backed pure functions
│   └── normalize.py        Bowtie detection, ring orientation
├── persistence/
│   ├── database.py         SQLModel engine + session
│   ├── models.py           User, ValidationReport, Project
│   ├── repository.py       Base repo class
│   ├── reports.py          ValidationReport repo
│   └── projects.py         (S13)
├── reporting/
│   ├── html_renderer.py
│   ├── archive.py
│   ├── diff.py
│   └── diff_html.py
├── rules/
│   ├── schema.py           Pydantic Rule
│   ├── loader.py
│   └── packs/
│       ├── bangalore-0.1.0.json
│       ├── bangalore-0.2.0.json
│       ├── bangalore-0.3.0.json
│       ├── mumbai-0.1.0.json
│       └── mumbai-0.2.0.json
├── adapters/               (empty; OCR/GIS/DWG/IFC reserved slot)
└── cli.py                  `planara-engine` entry point (uvicorn)
```

```
planara_plugin/planara/
├── boot.rb                 Extension registrar, menu wiring
├── config.rb               Engine URL, ports, timeouts
├── logger.rb
├── session.rb              JWT + project + last_report_id
├── engine_supervisor.rb
├── engine_client.rb        Net::HTTP wrapper
├── geometry/
│   ├── units.rb            Single conversion point
│   └── extractor.rb
├── observers/
│   └── live_validator.rb   500ms debounce
└── ui/
    ├── login_dialog.rb
    ├── results_dialog.rb
    ├── history_dialog.rb
    ├── project_picker.rb   (S13)
    ├── browser_view.rb
    └── assets/
        ├── login.html
        ├── results.html
        └── history.html
```

---

## 3.14 What this phase produced

By the end of Phase 3, settled and ready for Phase 4 / Sprint 1:

1. **Hybrid topology** (Ruby plugin + Python sidecar over localhost
   HTTP).
2. **Stack** (FastAPI + Pydantic + Shapely + SQLite + SQLModel +
   bcrypt + PyJWT + uvicorn).
3. **Module map** for both sides — every directory has a defined
   responsibility.
4. **Rule schema** with `applies_when` predicates, evaluator
   registry, `_SafeDict` template safety.
5. **Wire contract** (Snapshot in / Response out) with explicit
   schema versioning and warn-on-mismatch policy.
6. **Engine lifecycle** owned by the supervisor — UX is one
   click.
7. **Auth design** with no-leak invariants and explicit
   `password_hash` boundary.
8. **Reporting/history shape** designed up-front so persistence
   doesn't have to be retrofitted.

Phase 4 takes these and works out the **how** of getting from
legacy to here.
