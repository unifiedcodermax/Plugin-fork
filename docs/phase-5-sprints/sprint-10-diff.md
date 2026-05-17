# Sprint 10 — Diff: regression tracking between reports

**Dates:** 2026-05-17 04:57–05:32 IST (~35 min)
**Version:** 0.2.0-dev
**Commits:** 3
**Headline:** `diff_reports` produces an `added / removed / changed / unchanged` decomposition plus signed metric deltas; `/history/{id}/diff` auto-diffs against the most recent prior with the same `(city, classification, zone)`; `/history/diff?from=&to=` is the explicit form. HTML variants render the diffs as a browser-friendly view.

---

## Goal

Answer the question every iterative designer asks: *"Did my
latest change make things better or worse than the last time I
saved?"*

The answer is a structured diff between two `ArchivalReport`s,
surfaced both as JSON (for the plugin) and HTML (for the
browser).

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `5f9b1f6` | 04:57:05 | feat(engine/reporting): report-to-report diff for regression tracking |
| `e57624a` | 05:26:38 | feat(engine/api): /history diff routes for regression tracking |
| `14f62b4` | 05:32:08 | feat(engine/reporting): HTML diff renderer + routes |

---

## Engine deliverables

### `reporting/diff.py`

```python
class ReportDiff(BaseModel):
    from_report_id: UUID
    to_report_id: UUID
    verdict: Literal["improved", "regressed", "mixed", "unchanged"]
    summary: dict[str, list[str]]    # {added, removed, changed, unchanged}: [rule_id, ...]
    metric_deltas: dict[str, MetricDelta]
    added: list[Violation]
    removed: list[Violation]
    changed: list[ChangedViolation]
    unchanged: list[Violation]

def diff_reports(prior: ArchivalReport, current: ArchivalReport) -> ReportDiff: ...
```

### Diff semantics

> verbatim from `5f9b1f6`:
> *"Identification by `rule_id`; message-only differences are
> ignored (those are rule-pack edits, not regressions)."*

Two violations are "the same" if `rule_id` matches. If the
`message` changed but the `computed` values and verdict didn't,
the violation is **unchanged** (because the message change is a
rule-pack template edit, not a design regression).

Categories:

- **added** — violation present in `current` but not `prior`.
- **removed** — violation present in `prior` but not `current`.
- **changed** — same `rule_id`, but `computed` values differ.
- **unchanged** — same `rule_id`, same `computed` values.

### Verdict

> verbatim:
> *"Verdict is set-membership only — 'changed' surfaces in
> `summary['changed']` for the UI but doesn't flip the overall
> direction."*

```
if added and not removed:      verdict = "regressed"
elif removed and not added:    verdict = "improved"
elif added and removed:        verdict = "mixed"
else:                          verdict = "unchanged"
```

`changed` is informational only. It surfaces in `summary` for the
UI but doesn't affect the verdict — a single rule whose computed
FSI moved from 3.1 to 3.0 (still violating) hasn't "improved".

### Metric deltas

```python
class MetricDelta(BaseModel):
    metric: str               # "fsi"
    from_value: float         # 3.1
    to_value: float           # 2.8
    delta: float              # -0.3
    direction: Literal["up", "down", "unchanged"]
```

Signed deltas across `fsi`, `coverage_pct`, `open_space_pct`,
`min_setback_m`, `height_m`, `parking_required`,
`parking_provided`.

### Endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/history/{id}/diff` | Auto-diff against prior with same context |
| GET | `/history/diff?from=&to=` | Explicit diff between two reports |
| GET | `/history/{id}/diff/html` | Auto-diff rendered as HTML |
| GET | `/history/diff/html?from=&to=` | Explicit diff rendered as HTML |

### Auto-diff context match

> verbatim:
> *"Auto-diff context-match is `(city, classification, zone)`,
> not `snapshot_id` (each save gets a fresh snapshot_id from the
> plugin)."*

Given report id `X`, find the most-recent prior report for the
same `user_id` with matching `(city, classification, zone)` and
diff against it. Returns 404 if no such prior exists.

### Route ordering

> verbatim:
> *"Route ordering: `/history/diff` registered before
> `/history/{id}` so FastAPI doesn't try to parse 'diff' as a
> UUID."*

FastAPI matches routes in registration order. `/history/diff`
must come before `/history/{id}` or FastAPI tries to coerce
`"diff"` to a UUID and 422s.

### User-scope isolation extends to diff

> verbatim:
> *"User-scope isolation extends to diffs: another user's report
> ID returns 404 from either side."*

`GET /history/diff?from=alice_report_id&to=bob_report_id` (as
Bob) returns 404. Same for explicit-from-other-user.

### HTML diff renderer

> verbatim from `14f62b4`:
> *"HTML diff renderer + routes."*

Renders the diff as a standalone HTML document:

- Header (from_report, to_report, verdict).
- Summary card (counts of added/removed/changed/unchanged).
- Three sections (added in red, removed in green, changed in
  yellow).
- Metric deltas table.
- Unchanged collapsed by default.

Same XSS-safe escaping as the report renderer.

---

## Tests added

- `tests/unit/test_diff.py` — added/removed/changed/unchanged
  classification; verdict logic; metric delta signs;
  message-only-difference invariant.
- `tests/integration/test_history.py` (extended) — auto-diff
  context match, explicit-diff happy path, cross-user 404s,
  route ordering.

---

## Files added/changed

```
+ planara_engine/src/planara_engine/reporting/diff.py
+ planara_engine/src/planara_engine/reporting/diff_html.py
~ planara_engine/src/planara_engine/api/routes_history.py    (diff routes)
~ planara_engine/src/planara_engine/persistence/reports.py   (latest_with_context)
+ planara_engine/tests/unit/test_diff.py
~ planara_engine/tests/integration/test_history.py           (diff scenarios)
```

---

## Invariants locked

### D23 — Diff by `rule_id`, not by message

Message-only differences are pack edits, not regressions.

### D24 — Auto-diff context is `(city, classification, zone)`

Snapshot id is fresh per save and can't be the matching key.

### D25 — `/history/diff` registered before `/history/{id}`

FastAPI route order matters.

---

## Risks mitigated

| Risk | How |
|---|---|
| Cosmetic rule-pack edits flagged as regressions | Diff identification by `rule_id`, not full equality. |
| User A diffs User B's report | User-scope filter on both `from` and `to`. |
| `/history/diff` parsed as UUID | Route registered first. |

---

## Open limitation

> verbatim:
> *"Pack version sort still uses lex order (`bangalore-0.10.0`
> would sort below `0.2.0` — pinned by an existing test, harmless
> until we hit v0.10)."*

Filed under D34. Future fix: semver-aware sort. Not gating this
sprint.

---

## Concrete example

Day 1: Bob saves report `r1` for Bangalore/CBD/Residential.
Result: FSI 3.1 (violation), coverage 65 % (violation).

Day 2: Bob reduces the building. Saves report `r2` for the same
context. Result: FSI 2.4 (ok), coverage 58 % (ok).

```
GET /history/r2/diff
→ 200 {
  verdict: "improved",
  summary: {
    added: [],
    removed: ["blr.fsi.cbd.residential", "blr.coverage.cbd.residential"],
    changed: [],
    unchanged: [...]
  },
  metric_deltas: {
    fsi: { from: 3.1, to: 2.4, delta: -0.7, direction: "down" },
    coverage_pct: { from: 65, to: 58, delta: -7, direction: "down" }
  }
}
```

Day 3: Bob raises the building. Saves `r3`. Result: FSI 3.5
(violation), setback 1.2 m (new violation).

```
GET /history/r3/diff
→ 200 {
  verdict: "mixed",       # both added AND removed since r2
  summary: {
    added: ["blr.fsi.cbd.residential", "blr.setback.cbd.residential"],
    removed: [],
    ...
  }
}
```

---

## Deferred from this sprint

- Diff against an arbitrary baseline (e.g. compare to a saved
  "before" snapshot).
- Per-edit diff (every transaction commit produces a mini-diff in
  the UI).
- Diff visualization in the SketchUp model itself.
- Pack-version-aware diffs (today: pack version is recorded,
  diffs don't surface it explicitly — future enhancement).
