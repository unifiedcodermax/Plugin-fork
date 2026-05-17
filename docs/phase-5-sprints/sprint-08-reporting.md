# Sprint 8 — Reporting: HTML + ArchivalReport + content negotiation

**Dates:** 2026-05-16 19:58–20:01 IST (~3 min for commits, longer for design)
**Version:** 0.1.0 (tagged after this sprint)
**Commits:** 2
**Headline:** `POST /reports` produces an `ArchivalReport` (snapshot + response + `generated_at` + `rule_pack_version`); `Accept: text/html` renders a standalone HTML view. Neither writes to the database.

---

## Goal

Separate **rendering** from **persistence**. Some callers want a
nicely-rendered report they can save or print; not every render
needs to bloat the database. `/reports` is the stateless render
endpoint; `/history` (S9) will add the persistence.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `7d5cc45` | 19:58:09 | feat(engine/reporting): HTML + archival JSON renderers + POST /reports |
| `7c485ba` | 20:01:07 | test(reporting): unit + integration coverage for renderers and /reports |

---

## Engine deliverables

### Reporting module (`reporting/`)

```
reporting/
  __init__.py
  archive.py                 # ArchivalReport Pydantic model
  html_renderer.py           # ValidationResponse → standalone HTML
```

### `ArchivalReport` shape

```python
class ArchivalReport(BaseModel):
    report_id: UUID
    report_schema_version: str = "1.0"
    generated_at: datetime
    rule_pack_version: str        # e.g. "bangalore-0.3.0"
    snapshot: Snapshot
    response: ValidationResponse
```

**Decoupled versioning** (D26):

> verbatim:
> *"`ArchivalReport.report_schema_version` is decoupled from
> `Snapshot.schema_version` so the archive format can evolve
> independently."*

### Endpoint

```
POST /reports
Authorization: Bearer <jwt>
Content-Type: application/json
Accept: application/json | text/html

{ Snapshot }

→ ArchivalReport (JSON) or standalone HTML document
```

Content negotiation via `Accept`:

- `application/json` (default) → JSON body.
- `text/html` → standalone HTML document with embedded CSS.

### Server-side re-evaluation

> verbatim from `7d5cc45`:
> *"Server re-runs `evaluate` so callers can't forge a `response`
> payload."*

The endpoint accepts only the `Snapshot` in the request body. The
engine runs `evaluate()` itself. A client cannot construct a fake
"all clear" response — only the engine decides compliance.

### XSS hardening

> verbatim:
> *"XSS-safe HTML (escapes rule_id + message)."*

`rule_id`, `message`, and any user-controlled string is HTML-
escaped before being embedded in the rendered document.

### Mumbai-routed reports

> verbatim:
> *"Mumbai-routed archives carry Mumbai pack version."*

`ArchivalReport.rule_pack_version` records exactly which pack
version produced the response — `bangalore-0.3.0`, `mumbai-0.2.0`,
etc. This is essential for later diff (S10) — comparing reports
against different pack versions surfaces as a pack-version delta
in the diff envelope.

---

## Plugin deliverables

None in this sprint. The plugin gets its history wiring in S11.

---

## Tests added

### Engine

- `tests/unit/test_reporting.py` — HTML renderer output shape,
  XSS escape, archive JSON shape.
- `tests/integration/test_reports.py` — POST /reports JSON + HTML
  variants, server-side re-eval invariant, Mumbai routing.

> verbatim from `7c485ba`:
> *"Unit + integration coverage for renderers and /reports."*

---

## Files added/changed

```
+ planara_engine/src/planara_engine/reporting/__init__.py
+ planara_engine/src/planara_engine/reporting/archive.py
+ planara_engine/src/planara_engine/reporting/html_renderer.py
+ planara_engine/src/planara_engine/api/routes_reports.py
+ planara_engine/tests/unit/test_reporting.py
+ planara_engine/tests/integration/test_reports.py
~ planara_engine/src/planara_engine/api/app.py            (routers_reports)
```

---

## Invariants locked

### D19 — `Accept: text/html` for browser variants

Single endpoint, two representations. The plugin uses the HTML
variant + `BrowserView` (S11) to open results in a browser tab.

### D20 — `/reports` doesn't write; `/history` will

Two endpoints, two responsibilities. Avoids accidental DB bloat
on every render.

### D21 — Server re-runs `evaluate`; client cannot forge response

Engine is the only authority on compliance. Clients can suggest
geometry, not verdicts.

### D26 — Decoupled archive versioning

`ArchivalReport.report_schema_version` evolves on its own
cadence; `Snapshot.schema_version` evolves separately.

---

## Risks mitigated

| Risk | How |
|---|---|
| Forged compliance reports | Server-side re-eval. |
| HTML injection via rule message | Output escape on all user-controlled strings. |
| Archive format coupling | Decoupled versioning. |

---

## Rendered HTML shape

The renderer produces a self-contained HTML document with:

- A header (project, generated_at, rule_pack_version).
- An overall verdict ("Compliant" / "Non-compliant").
- A section per category (FSI, setback, coverage, open space,
  parking, height).
- Each violation: rule id, message, computed-vs-limit table.
- Metrics summary at the bottom.

Embedded CSS — no external requests. Opens cleanly in any
browser tab (the plugin does exactly that in S11 via
`BrowserView` + `UI.openURL`).

---

## Deferred from this sprint

- PDF variant via WeasyPrint — listed in the deferred backlog as
  1-sprint future work.
- Email-the-report endpoints.
- Branded / themed reports.
- Multi-project comparison reports (different concern; needs
  multiple snapshots).

---

## Sprint 8 → 0.1.0 tagged release

After S8, the engine surface is:

- `/health` — S1.
- `/auth/login`, `/auth/me` — S2.
- `/validate` — S3.
- `/reports` — S8.

This is the **0.1.0** surface. CHANGELOG records it as "Initial
hybrid architecture release. `planara_plugin/` (Ruby inside
SketchUp) talks to `planara_engine/` (Python FastAPI sidecar)
over localhost HTTP." Tagged formally in S12 alongside the CI
work, but the **scope** of 0.1.0 closes here.
