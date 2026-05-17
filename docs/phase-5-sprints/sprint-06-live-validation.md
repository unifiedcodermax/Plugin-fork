# Sprint 6 — Live validation: schema_version + Session.project + LiveValidator + Results dialog

**Dates:** 2026-05-16 16:48–18:44 IST (~2 hours)
**Version:** 0.1.0-dev
**Commits:** 6
**Headline:** The plugin now validates **live** as the user models — `LiveValidator` debounced at 500 ms on `ModelObserver` events, results in a non-modal HtmlDialog, snapshot schema versioned, plugin contract tests pinning the wire format.

---

## Goal

Replace the inputbox-then-messagebox flow inherited from legacy
with a real **live-modeling loop**: every model change triggers
a debounced `/validate` call; results render in a dockable dialog
that doesn't block modeling.

This is the sprint that makes the plugin feel like a real CAD
assistant.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `0a0f70e` | 16:48:30 | feat(engine/domain): Snapshot.schema_version with mismatch warning |
| `4c0a86f` | 18:32:49 | feat(plugin/extractor): emit schema_version + overlays in snapshot |
| `24e69e1` | 18:34:15 | feat(plugin/session): Session.project + reused setup across runs |
| `d5f8fb8` | 18:37:40 | feat(plugin): ModelObserver-driven live validate loop |
| `b43fe58` | 18:40:39 | feat(plugin/ui): live results HtmlDialog replaces messagebox wall |
| `8034c77` | 18:44:40 | test(plugin): pin extractor wire format via build_payload/normalize_project |

---

## Engine deliverables

### `Snapshot.schema_version`

> verbatim from `0a0f70e`:
> *"`Snapshot.schema_version` (default '1.0', warns on mismatch
> instead of rejecting)."*

Field added to the `Snapshot` Pydantic model. Default `"1.0"`.
Engine behaviour on mismatch:

- Plugin sends a version older than what engine knows about → log
  a warning, proceed as if `"1.0"`.
- Plugin sends a version newer than what engine knows → 415
  `Unsupported Schema`.

The forward-compatibility direction is by design (D17): older
plugins must keep working when the engine upgrades.

---

## Plugin deliverables

### Extractor emits `schema_version` + `overlays`

> verbatim from `4c0a86f`:
> *"Extractor emits schema_version + overlays in snapshot."*

The extractor now produces a complete, current-schema snapshot
including the version stamp and the overlay set from
`Session.project`.

### `Session.project`

> verbatim from `24e69e1`:
> *"`Session.project` + reused setup across runs."*

`Session.project` is a structured value:

```ruby
Session.project = {
  city: "Bangalore",
  classification: "CBD",
  zone: "Residential",
  overlays: ["airport"]
}
```

It replaces the loose `DataPoints[:overlays]` from S5. Set once
in the project setup dialog; re-used by every subsequent
extraction.

### `LiveValidator` (`observers/live_validator.rb`)

> verbatim from `d5f8fb8`:
> *"ModelObserver-driven live validate loop."*

Attached to the active model. Every transaction commit / undo
triggers:

```
ModelObserver event
  → LiveValidator.schedule
      (debounce timer; reset to 500ms on each new event)
  → after 500ms idle, fire validate
      → Extractor.snapshot(model, Session.project)
      → EngineClient.validate(snapshot)
      → ResultsDialog.update(response)
```

The 500 ms debounce (D15) batches mid-drag updates into a single
post-drag validate.

### Results HtmlDialog replaces messagebox

> verbatim from `b43fe58`:
> *"Live results HtmlDialog replaces messagebox wall."*

The legacy `UI.messagebox` on FSI violation is gone. In its place:

```
planara_plugin/planara/ui/
  results_dialog.rb         # Wraps HtmlDialog with assets/results.html
  assets/results.html       # Plain HTML; receives violations via execute_script
```

Behaviour:

- Non-modal — opens on first violation, stays open across edits.
- Sectioned by category (FSI, setback, coverage, …).
- Each violation shows rule id + message + computed-vs-limit.
- Empty-state when `ok: true`.

This is **the UX change that justifies the whole architecture**.
The legacy prototype interrupted modeling on every violation.

---

## Tests added

- `tests/plugin/test_extractor.rb` extended — pin
  `build_payload` and `normalize_project` outputs against
  snapshot fixtures.
- Engine integration tests cover schema_version mismatch paths.

> verbatim from `8034c77`:
> *"Pin extractor wire format via build_payload/normalize_project."*

12 minitest cases added across this and adjacent sprints pinning
the contract.

---

## Files added/changed

```
+ planara_plugin/planara/observers/live_validator.rb
+ planara_plugin/planara/ui/results_dialog.rb
+ planara_plugin/planara/ui/assets/results.html
~ planara_plugin/planara/session.rb            (project struct)
~ planara_plugin/planara/geometry/extractor.rb (schema_version, overlays)
~ planara_plugin/planara/boot.rb               (LiveValidator attach)
~ planara_plugin/test/test_extractor.rb        (contract tests)
~ planara_engine/src/planara_engine/domain/snapshot.py        (schema_version)
~ planara_engine/src/planara_engine/api/routes_validate.py    (version warning)
```

---

## Invariants locked

### D15 — Live validation debounced at 500 ms

500 ms balances UX (feels responsive) against engine load (no
storm).

### D16 — Replace messagebox with HtmlDialog

Non-modal results panel. Stays out of the way.

### D17 — `schema_version` warns on minor mismatch

Forward-compat by default; loud reject on newer-than-engine.

---

## Risks mitigated

| Risk | How |
|---|---|
| R4 — geometry contract drift | Extractor pinned by minitest fixtures. |
| R11 — schema evolution breaks older plugins | Warn-on-mismatch policy. |

---

## Live-validation flow (the full picture)

```
User drags a wall in SketchUp
  │
  ▼
ModelObserver fires onTransactionCommit
  │
  ▼
LiveValidator schedules a 500ms idle timer
  │  (more edits reset the timer)
  ▼
Timer fires
  │
  ▼
Extractor.snapshot(active_model, Session.project)
  │
  ▼
EngineClient.validate(snapshot)
  │
  POST /validate (Authorization: Bearer ...)
  │
  ▼
Engine: applicability filter → evaluators → ValidationResponse
  │
  ▼
ResultsDialog.update(response)
  │
  ▼
HtmlDialog re-renders sections; user sees verdict in <1s
```

---

## Concrete example

User is mid-design of a 15-storey CBD/Residential in the airport
overlay. They make the top floor taller, pushing total height
from 44 m to 47 m.

```
T-0     : edit happens
T+0.5s  : LiveValidator fires
T+0.6s  : engine responds — height.airport violation surfaces
T+0.6s  : ResultsDialog highlights the new violation
```

The user reverses the edit. T+1.1 s the violation disappears.

---

## Deferred from this sprint

- In-model violation visualization (highlight the offending edge
  in SketchUp) — listed in the deferred backlog as a future 2–3
  sprint UX initiative.
- Tooltip integration on the dialog.
- Performance optimization for very large models (deferred until
  observed slow in practice).

---

## Why this sprint matters more than its commit count suggests

S6 is a small sprint (6 commits, 2 hours) but it changes the
**character** of the product. Before S6, the plugin is a glorified
HTTP client. After S6, it's a real CAD assistant — the kind of
tool the user would actually want open while modeling.
