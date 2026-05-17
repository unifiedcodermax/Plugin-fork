# Cross-cutting Decisions Log

This file is a flat list of the **locked architectural decisions**
made during Phase 1–4 — preserved verbatim where the original
wording matters, paraphrased where it doesn't. Each entry has:

- **Decision** — what was chosen.
- **Alternatives considered** — what else was on the table.
- **Reason** — why this one.
- **Where it lives** — file/module that embodies it today.
- **Sprint** — when it was applied.

The intent is that a future contributor can scan this file and
understand "*why* is it like this?" without having to reconstruct
the design conversation.

---

## D1 — Hybrid architecture (Option C)

**Decision:** Thin Ruby SketchUp plugin + Python FastAPI sidecar
over localhost HTTP/JSON.

**Alternatives considered:**

- Option A: Ruby plugin + remote-only Python backend.
- Option B: Replace plugin entirely with a Python desktop app.

**Reason:**

- Option B fails because SketchUp doesn't embed Python — a Python
  "plugin" cannot exist.
- Option A fails on UX because the user has to install and run
  Python themselves.
- Option C subsumes A: the same Python service deployed remotely
  works without code change. Only `PLANARA_ENGINE_URL` flips.

> verbatim:
> *"Recommendation: C (Hybrid) → degrades cleanly to A. Build the
> Python engine as a standalone HTTP service (FastAPI). The Ruby
> plugin manages its lifecycle (spawn on init, shut down on
> `onQuit`) and POSTs geometry snapshots + receives validation
> results."*

**Where it lives:** `planara_plugin/planara/engine_supervisor.rb`,
`planara_engine/src/planara_engine/cli.py`.

**Sprint:** Locked pre-S1.

---

## D2 — Localhost HTTP/JSON, not gRPC or sockets

**Decision:** HTTP/JSON over `127.0.0.1`.

**Alternatives considered:** gRPC, WebSockets, named pipes, Unix
sockets, raw TCP.

**Reason:**

- SketchUp's Ruby is sandboxed — no gem install. gRPC would
  require `grpcio` (impossible to install). HTTP/JSON works with
  Ruby's stdlib `Net::HTTP`.
- Bidirectional streaming is not needed; request/response covers
  every endpoint.
- HTTP is debuggable with `curl`.
- HTTP is identical for localhost and cloud.

**Where it lives:** `planara_plugin/planara/engine_client.rb`,
`planara_engine/src/planara_engine/api/`.

**Sprint:** S1.

---

## D3 — Stdlib only on the Ruby side

**Decision:** Ruby plugin uses Ruby stdlib only — no gems.

**Reason:**

- SketchUp's embedded Ruby is sandboxed; gem installs are
  unreliable across versions and OSes.
- `Net::HTTP`, `JSON`, `UI::HtmlDialog`, `Logger`, `securerandom`,
  `fileutils` cover everything the plugin needs.

**Where it lives:** Every file under `planara_plugin/`. No
Gemfile.

**Sprint:** S1.

---

## D4 — FastAPI + Pydantic + Shapely + SQLite + SQLModel

**Decision:** Python stack.

**Alternatives considered:** Flask (rejected — less typed), Django
(rejected — too heavy), raw asyncio (rejected — no typed-route
support), MongoDB (rejected — daemon), Postgres (deferred — daemon),
argon2 (rejected — bcrypt has wider Python-version support).

**Reason:** Typed-everywhere, ecosystem fit for geometry math,
single-file persistence for MVP.

**Where it lives:** `planara_engine/pyproject.toml`.

**Sprint:** S1.

---

## D5 — Push to main per commit; small, descriptive commits

**Decision:** No long-lived feature branches for MVP work. Push
each commit to `main`.

> verbatim from user:
> *"push to GitHub with proper commit message and in smaller
> commits with detailed description."*

**Reason:** Single-developer MVP; the cost of branch overhead
outweighs the benefit.

**Where it lives:** Git history.

**Sprint:** S1 onwards.

---

## D6 — Local auth with JWT (MVP)

**Decision:** SQLite users + bcrypt + PyJWT.

> verbatim from locked decisions:
> *"Hybrid architecture, push-to-main per commit, local auth with
> JWT."*

**Alternatives considered:** OAuth, SSO, magic-link, license keys.

**Reason:** MVP needs *some* authentication boundary (audit
trail, future licensing). Cloud auth is out of scope. SQLite
covers it with no daemon.

**Where it lives:** `planara_engine/src/planara_engine/auth/`.

**Sprint:** S2.

---

## D7 — No-leak login

**Decision:** Login response cannot distinguish "user not found"
from "wrong password". Same message, same timing.

> verbatim:
> *"No-leak auth: identical message + timing-balanced bcrypt for
> 'no such user' vs 'wrong password'. Test enforces this; a
> regression would be silent and bad."*

**Reason:** Username enumeration is a real exploit vector even
for local auth, because the engine is potentially exposed via
config (`PLANARA_ENGINE_URL`).

**Where it lives:** `auth/service.py`.

**Sprint:** S2.

---

## D8 — `password_hash` boundary via `MeResponse`

**Decision:** A dedicated Pydantic model (`MeResponse`) is what
`/auth/me` returns — not the ORM model.

> verbatim:
> *"`password_hash` boundary: `MeResponse` Pydantic model is the
> explicit boundary; integration test asserts the field never
> appears in /me responses."*

**Reason:** The ORM model has the hash; the wire model must not.
A dedicated boundary class makes the asymmetry visible in code.

**Where it lives:** `auth/service.py`, `domain/...` (response
models).

**Sprint:** S2.

---

## D9 — Pydantic is the source of truth for the wire

**Decision:** The Ruby ↔ Python wire contract is whatever the
Pydantic models accept. Ruby mirrors as plain hashes.

**Reason:** One schema definition, not two. Drift becomes an
engine-side validation error, surfaced via the error envelope to
the plugin.

**Where it lives:** `domain/snapshot.py`, `domain/violation.py`,
…

**Sprint:** S3.

---

## D10 — Meters on the wire

**Decision:** All lengths on the wire are in meters. The plugin
converts from SketchUp's internal inches once, at extraction time.

**Reason:** Eliminates per-evaluator unit-handling code. Engine
never has to ask "what unit is this?"

**Where it lives:** `planara_plugin/planara/geometry/units.rb`,
`planara_plugin/planara/geometry/extractor.rb`.

**Sprint:** S3.

---

## D11 — `_SafeDict` for message-template substitution

**Decision:** Render `message_template` strings using a
`_SafeDict` that returns `{missing_key}` for unknown keys instead
of raising.

> verbatim from S3, commit `5d01b1e`:
> *"RuleEngine + evaluator registry with `_SafeDict` template
> fallback so a typo'd `{wrong_key}` doesn't 500 the whole
> evaluate call."*

**Reason:** A typo in rule-pack JSON should not crash the engine
or break unrelated rules in the same evaluate.

**Where it lives:** `engine/rule_engine.py`.

**Sprint:** S3.

---

## D12 — Shapely rejects bowties; does not auto-repair

**Decision:** Self-intersecting polygons cause a `geometry_invalid`
error at the snapshot's entry gate. The engine does **not** silently
make them valid.

> verbatim:
> *"Shapely-backed geometry — area, union, inset (mitered),
> within, distance-to-boundary; bowtie polygon correctly
> rejected, not silently repaired."*

**Reason:** Auto-repair masks real upstream bugs in extraction or
modeling. Surfacing it teaches the user to fix the model.

**Where it lives:** `geometry/normalize.py`.

**Sprint:** S3.

---

## D13 — Bangalore v0.1.0 is preserved for version-pinning evidence

**Decision:** Even after `bangalore-0.2.0.json` ships, the older
`0.1.0` pack is kept on disk.

> verbatim from S3, commit `02d3932`:
> *"Bangalore v0.1.0 rule pack — all 9 classification×zone cells,
> values pinned to legacy file by test."*

**Reason:** Demonstrates that pack versions are independently
loadable. Useful for regression tests against a known-good baseline.

**Where it lives:** `rules/packs/bangalore-0.1.0.json`.

**Sprint:** S3.

---

## D14 — Overlays are an applicability dimension, not inheritance

**Decision:** Overlay membership (`airport`, `heritage_influence`,
`crz`) is a key on `applies_when`. Rules opt in via
`overlays_include`. There is no rule-inheritance mechanism.

> verbatim:
> *"`airport` overlay reused across both packs; `crz` stays
> Mumbai-only — proving overlay keys can be either shared or
> city-scoped."*

**Reason:** Inheritance becomes a graph; the applicability
predicate stays declarative and grep-able.

**Where it lives:** `rules/schema.py`, evaluator filters in
`engine/rule_engine.py`.

**Sprint:** S5.

---

## D15 — Live validation debounced at 500 ms

**Decision:** `LiveValidator` attaches to `ModelObserver` and waits
500 ms after the last edit before firing `/validate`.

**Reason:** SketchUp fires transaction events for every micro-edit.
Without debounce, the engine receives a burst per drag-gesture.
500 ms balances UX responsiveness against engine load.

**Where it lives:** `planara_plugin/planara/observers/live_validator.rb`.

**Sprint:** S6.

---

## D16 — Replace `UI.messagebox` with HtmlDialog results

**Decision:** Violations render in a non-modal HtmlDialog, not in
a blocking `UI.messagebox`.

**Reason:** A blocking modal interrupts modeling — exactly the UX
that the legacy plugin got wrong. HtmlDialog is dockable and stays
out of the way.

**Where it lives:** `planara_plugin/planara/ui/results_dialog.rb`,
`planara_plugin/planara/ui/assets/results.html`.

**Sprint:** S6.

---

## D17 — `schema_version` warns on minor mismatch

**Decision:** Engine accepts older `Snapshot.schema_version`
values (warning logged); newer-than-supported raises explicit
`415 Unsupported Schema`.

> verbatim:
> *"Snapshot.schema_version (default '1.0', warns on mismatch
> instead of rejecting)."*

**Reason:** Older plugins keep working when the engine upgrades;
newer plugins fail loudly when the engine is behind.

**Where it lives:** `domain/snapshot.py`, `api/routes_validate.py`.

**Sprint:** S6.

---

## D18 — Adding a new city is data-only

**Decision:** The engine is city-agnostic. A new city = a new
JSON pack at `rules/packs/<city>-<semver>.json`. No code change.

> verbatim:
> *"Audit — engine is already city-agnostic; zero code changes
> needed."*

**Reason:** Proven by Mumbai pack shipping in S7 with zero
evaluator changes.

**Where it lives:** `rules/loader.py`, `engine/rule_engine.py`.

**Sprint:** S7.

---

## D19 — `Accept: text/html` for browser-friendly variants

**Decision:** `/reports`, `/history/{id}`, `/history/{id}/diff`,
`/history/diff` all respect `Accept`. JSON for programmatic
clients, HTML for opening in a browser.

**Reason:** The plugin uses `BrowserView` to write engine HTML to
a tempfile and `UI.openURL` it — no client-side rendering needed.

**Where it lives:** `api/routes_reports.py`, `api/routes_history.py`,
`reporting/html_renderer.py`, `reporting/diff_html.py`.

**Sprint:** S8 / S10.

---

## D20 — `/reports` doesn't write; `/history` does

**Decision:** Two separate endpoints. `/reports` renders an
ArchivalReport without DB write; `/history` does the same +
persists.

**Reason:** Some callers want a one-shot "render this nicely"
that doesn't bloat history. The two-endpoint split makes the
distinction explicit.

**Where it lives:** `api/routes_reports.py`,
`api/routes_history.py`.

**Sprint:** S8 / S9.

---

## D21 — Server re-runs `evaluate`; client cannot forge response

**Decision:** When persisting a report, the engine re-runs
`evaluate` on the supplied snapshot, ignoring any client-supplied
`response`.

> verbatim from S8:
> *"XSS-safe HTML (escapes rule_id + message), Mumbai-routed
> archives carry Mumbai pack version, server re-runs `evaluate`
> so callers can't forge a `response` payload."*

**Reason:** The client cannot decide what counts as compliance.
The engine is the only authority on `ok`/violations.

**Where it lives:** `api/routes_reports.py`,
`api/routes_history.py`.

**Sprint:** S8.

---

## D22 — User-scope isolation: 404 for "yours-or-others"

**Decision:** Every history read filters by `user_id`. Both
"doesn't exist" and "belongs to someone else" surface as **404**.

> verbatim from S9:
> *"User-scope isolation enforced at the repo layer (`user_id`
> filter on every read) so 404 means the same thing whether the
> report doesn't exist or belongs to someone else."*

**Reason:** A 403 would leak existence. 404 keeps the response
shape uniform.

**Where it lives:** `persistence/reports.py`, route guards.

**Sprint:** S9.

---

## D23 — Diff by `rule_id`, not by message

**Decision:** Two violations diff as "same" if their `rule_id`
matches, even if `message` differs. Message-only differences are
ignored — they reflect rule-pack template edits, not regressions.

> verbatim from S10:
> *"Identification by `rule_id`; message-only differences are
> ignored (those are rule-pack edits, not regressions). Verdict
> is set-membership only — 'changed' surfaces in
> `summary['changed']` for the UI but doesn't flip the overall
> direction."*

**Reason:** Otherwise a cosmetic rule-pack bump shows every
report as "regressed".

**Where it lives:** `reporting/diff.py`.

**Sprint:** S10.

---

## D24 — Auto-diff context is `(city, classification, zone)`

**Decision:** Auto-diff finds the most-recent prior report for
the same user with matching `(city, classification, zone)`. Each
save gets a fresh `snapshot_id` from the plugin so it cannot be
the matching key.

**Reason:** The user's typical question is "did *this design* get
better or worse than the last time I saved?" — the matching key
is the project, not the snapshot.

**Where it lives:** `persistence/reports.py:auto_diff_lookup`.

**Sprint:** S10.

---

## D25 — `/history/diff` registered before `/history/{id}`

**Decision:** FastAPI's path ordering matters. `/history/diff`
must be registered first or FastAPI will try to parse `"diff"` as
a UUID and 422.

> verbatim:
> *"Route ordering: `/history/diff` registered before
> `/history/{id}` so FastAPI doesn't try to parse 'diff' as a
> UUID."*

**Where it lives:** `api/routes_history.py`.

**Sprint:** S10.

---

## D26 — `ArchivalReport.report_schema_version` is independent

**Decision:** The report archive format has its own version,
decoupled from `Snapshot.schema_version`.

> verbatim:
> *"`ArchivalReport.report_schema_version` is decoupled from
> `Snapshot.schema_version` so the archive format can evolve
> independently."*

**Reason:** The two artifacts evolve at different rates. A new
field in the archival shape (e.g., a `correlation_id`) shouldn't
force a snapshot version bump.

**Where it lives:** `reporting/archive.py`.

**Sprint:** S8.

---

## D27 — `payload TEXT` is source of truth; summary columns indexed

**Decision:** Persist the full `ArchivalReport` JSON in a
`payload TEXT` column. Denormalize a few fields (city,
classification, zone, ok, violation counts) into typed columns
for indexing.

> verbatim:
> *"Persisted `payload` is the source of truth — re-renders read
> it back, never re-evaluate. Denormalized summary columns
> (city/ok/counts) are indexed; full archive stays in `payload
> TEXT` so storage is portable to Postgres JSONB later.
> Pagination capped at 100 via FastAPI `Query(le=100)`."*

**Reason:** Indexed reads stay fast; full archive stays portable
(JSONB on Postgres later).

**Where it lives:** `persistence/models.py`,
`persistence/reports.py`.

**Sprint:** S9.

---

## D28 — Pagination capped at 100

**Decision:** `GET /history?limit=N` caps at 100 via
`Query(le=100)`.

**Reason:** Avoid full-table scans on a runaway client.

**Where it lives:** `api/routes_history.py`.

**Sprint:** S9.

---

## D29 — Project entity introduced post-MVP (S13)

**Decision:** A `Project` SQLModel with FK from
`ValidationReport`. Plugin gets a `ProjectPicker` HtmlDialog.

> verbatim:
> *"The auto-diff anchor `(city, classification, zone)` breaks
> the moment a user has two Bangalore/CBD/Residential designs. A
> real `Project` row solves it and unlocks better history
> navigation."*

**Reason:** Two designs with the same `(city, classification,
zone)` would auto-diff against each other, which is wrong. The
project entity makes "design identity" first-class.

**Where it lives:** `persistence/projects.py`,
`api/routes_projects.py`,
`domain/project_context.py` (renamed from `project.py`),
`planara_plugin/planara/ui/project_picker.rb`.

**Sprint:** S13 (in flight, uncommitted as of doc-write date).

---

## D30 — `adapters/` is the reserved seam for OCR / GIS / DWG / IFC

**Decision:** A top-level `adapters/` package with no contents
beyond `__init__.py` exists in the engine.

**Reason:** Reserves the seam so future contributors know where
to add document parsing / spatial overlays / CAD ingest without
re-architecting.

**Where it lives:** `planara_engine/src/planara_engine/adapters/`.

**Sprint:** S1 (slot reserved); no fill scheduled.

---

## D31 — `mypy --strict`, ruff with the passing subset

**Decision:** Lint with ruff (`E, F, W, I, B, UP, SIM, C4`).
Types with `mypy --strict`. Shapely treated as untyped at one
seam (`geometry/normalize.py`).

> verbatim from 0.2.0 changelog:
> *"`mypy --strict` now passes on the engine. Shapely is treated
> as untyped at the seam — the only direct importer is
> `geometry/normalize.py`."*

**Reason:** Strict types catch contract drift early. The one
Shapely seam is documented; importing Shapely anywhere else
re-introduces the unchecked surface.

**Where it lives:** `planara_engine/pyproject.toml`,
GitHub Actions workflow.

**Sprint:** S12.

---

## D32 — GitHub Actions: pytest + ruff + mypy + minitest, Python 3.11/3.12 matrix

**Decision:** CI runs the full test matrix on every push and PR.

**Reason:** Catches regressions before they reach `main`.

**Where it lives:** `.github/workflows/...`.

**Sprint:** S12.

---

## D33 — Legacy code preserved unmodified under `legacy/`

**Decision:** The original SV-Abid Ruby code is preserved
**unchanged** under `legacy/SV-Abid/`. No bug fixes, no
refactors. Treated as reference only.

**Reason:** Audit trail — anyone can compare claims in this
documentation against the on-disk source.

**Where it lives:** `legacy/SV-Abid/`, `legacy/README.md`.

**Sprint:** Pre-S1 reorganization.

---

## D34 — Pack version sort is lexicographic (known limitation)

**Decision:** `latest_version("Bangalore")` sorts pack filenames
lexicographically. This works up to `v0.9.x`.

**Reason:** Acceptable trade-off — bumping `v0.10.0` needs a sort
fix, but that's a one-line change and the test suite pins the
current behavior.

> verbatim:
> *"Pack version sort still uses lex order (`bangalore-0.10.0`
> would sort below `0.2.0` — pinned by an existing test, harmless
> until we hit v0.10)."*

**Where it lives:** `rules/loader.py`.

**Sprint:** S10 (open).

---

## D35 — Engine binds to `127.0.0.1` by default

**Decision:** Loopback only. Other machines on the LAN cannot
reach the engine without explicit config.

**Reason:** Defense-in-depth. Auth is still required, but a
loopback bind eliminates the trivial attack surface.

**Where it lives:** `cli.py`, `core/settings.py`.

**Sprint:** S1.

---

## D36 — Engine supervisor: adopt-or-spawn

**Decision:** If a healthy engine is already listening on the
configured port, the supervisor **adopts** it instead of spawning
a duplicate.

**Reason:** Multiple SketchUp windows shouldn't each spawn their
own engine. One shared engine handles everyone.

**Where it lives:** `planara_plugin/planara/engine_supervisor.rb`.

**Sprint:** S1.

---

## D37 — Plugin session is process-scoped, not persistent

**Decision:** `Session.token`, `Session.project`,
`Session.last_report_id` live in process memory only. Restarting
SketchUp = new login.

**Reason:** Avoids on-disk token storage and the associated
exfiltration risk. The 30-day JWT lifetime is for the engine's
internal session validity, not the plugin's UX.

**Where it lives:** `planara_plugin/planara/session.rb`.

**Sprint:** S2 (login); S6 (project); S11 (last_report_id).

---

## D38 — No frontend framework inside HtmlDialog

**Decision:** UI screens use plain HTML + vanilla JS.

> verbatim:
> *"HTML + vanilla JS inside `UI::HtmlDialog`. No frontend
> framework (HtmlDialog is constrained)."*

**Reason:** HtmlDialog's embedded browser is constrained. Modern
frontend frameworks (React, Vue) require build tooling and runtime
size that don't match the constraint.

**Where it lives:** `planara_plugin/planara/ui/assets/`.

**Sprint:** S2 onwards.

---

## Closing notes

This log is not exhaustive — sprint-internal micro-decisions
aren't here. The intent is to preserve the *architectural*
decisions that would otherwise be lost if the conversation
history were ever discarded.

If you make a new architectural decision, add it here. Format:

```
## D{N} — Short title

**Decision:**
**Alternatives considered:**
**Reason:**
**Where it lives:**
**Sprint:**
```
