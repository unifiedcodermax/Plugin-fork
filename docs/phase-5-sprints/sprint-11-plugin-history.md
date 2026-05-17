# Sprint 11 — Plugin history wiring: Recent runs UI + diff in browser

**Dates:** 2026-05-17 05:55 IST
**Version:** 0.2.0-dev
**Commits:** 1 (large)
**Headline:** Plugin `EngineClient` grows a history surface (`save_history`, `list_history`, `get_history`, `auto_diff`, `explicit_diff`, plus `_html` variants); four new menu items; `HistoryDialog` HtmlDialog with paginated list + actions; `BrowserView` opens engine HTML in the user's browser.

---

## Goal

Make the engine's S9–S10 history + diff surface usable from
SketchUp. The user shouldn't have to know `curl` to save and
compare runs.

---

## Commits

| SHA | Date | Subject |
|---|---|---|
| `ea188db` | 05:55:40 | feat(plugin): /history client + Recent runs UI + diff in browser |

This is one large commit covering plugin client + UI + dialog +
menu wiring + tests. Per the user's "small commits" preference,
this could have been split — it landed atomic because the pieces
don't usefully ship alone (a history client without UI menu items
is dead weight).

---

## Plugin deliverables

### `EngineClient` extensions

New methods:

```ruby
class Planara::EngineClient
  def save_history(snapshot)        # POST /history
  def list_history(filters)         # GET /history
  def get_history(id)               # GET /history/{id}
  def get_history_html(id)          # GET /history/{id}.html
  def auto_diff(id)                 # GET /history/{id}/diff
  def auto_diff_html(id)            # GET /history/{id}/diff/html
  def explicit_diff(from_id, to_id) # GET /history/diff
  def explicit_diff_html(from, to)  # GET /history/diff/html
end
```

### `request_raw` transport

For the HTML endpoints, a new `request_raw` method bypasses the
JSON-parsing path and returns the raw HTML string. The dialog
hands it to `BrowserView` which writes a tempfile and opens it.

### Menu items added

Four new entries under the `Planara` menu:

- **Save current run** — extracts snapshot, POSTs `/history`,
  stores the new `report_id` in `Session.last_report_id`.
- **Recent runs…** — opens `HistoryDialog`.
- **Compare with last save** — calls `auto_diff` for
  `Session.last_report_id`; opens the HTML view in a browser tab.
- **Open last report in browser** — calls `get_history_html` for
  `Session.last_report_id`; opens in a browser.

### `HistoryDialog` (`ui/history_dialog.rb`)

> verbatim from `ea188db`:
> *"Paginated list of saved runs with per-row open + auto-diff
> actions and a two-row picker for pairwise diff."*

- Paginated table of saved runs (most-recent first).
- Each row: timestamp, city/classification/zone, verdict
  (ok/violations).
- Row actions: "Open in browser", "Diff against last".
- Two-row picker: select any two rows → "Compare selected" →
  calls `explicit_diff_html`.

### `BrowserView` (`ui/browser_view.rb`)

> verbatim:
> *"Write engine-rendered HTML to a tempfile and open it with
> `UI.openURL`."*

```ruby
def self.open_html(html_body)
  path = Dir.mktmpdir + "/planara-report.html"
  File.write(path, html_body)
  UI.openURL("file://#{path}")
end
```

Trade-off: the user's default browser opens the file (full HTML
rendering, copy/save/print). Cost: a tempfile per open call.
Acceptable for the volume.

### `Session.last_report_id`

Process-scoped id of the most recent save. Powers "Open last
report in browser" and "Compare with last save".

> verbatim:
> *"`Session.last_report_id` — process-scoped id of the most
> recent save, powering 'Open last report in browser'."*

Lives in `Session` (D37 — session is process-scoped). Restarting
SketchUp clears it.

---

## Tests added

### Plugin

> verbatim:
> *"`test/test_engine_client.rb` — 13 minitest cases stubbing
> `open_http` to pin URL shape, headers, query encoding, raw HTML
> return, and JSON error-envelope translation."*

13 minitest cases:

- URL shape per method.
- Authorization header attached.
- Query encoding for `list_history` filters.
- Raw HTML returned by `*_html` methods.
- JSON error envelope → Ruby exception.

---

## Files added/changed

```
~ planara_plugin/planara/engine_client.rb       (8 new methods + request_raw)
+ planara_plugin/planara/ui/history_dialog.rb
+ planara_plugin/planara/ui/browser_view.rb
+ planara_plugin/planara/ui/assets/history.html
~ planara_plugin/planara/boot.rb                (4 new menu items)
~ planara_plugin/planara/session.rb             (last_report_id)
+ planara_plugin/test/test_engine_client.rb     (13 cases)
```

---

## Invariants locked

### Plugin → engine contract pinned by minitest

13 cases assert the wire shape from the plugin side. Combined
with the engine-side pytest integration suite (`test_history.py`,
`test_reports.py`), drift between the two would fail one or the
other.

---

## Risks mitigated

| Risk | How |
|---|---|
| R4 — geometry contract drift (extended to history) | Minitest cases pin URL, headers, query, body, response transport. |

---

## Concrete user flow

1. User models a CBD/Residential building.
2. `LiveValidator` (S6) shows violations in `ResultsDialog`.
3. User clicks **Planara → Save current run**.
   - Snapshot extracted, POSTed to `/history`.
   - `report_id` stored in `Session.last_report_id`.
4. User iterates: reduces FSI by adding setback.
5. `LiveValidator` shows fewer violations.
6. User clicks **Planara → Compare with last save**.
   - `auto_diff_html(last_report_id)` called.
   - Tempfile written; `UI.openURL` opens browser.
   - User sees the diff: violations removed in green, metrics
     moved in the right direction.
7. User decides this is good. Clicks **Save current run** again.
8. Clicks **Planara → Recent runs…**.
   - `HistoryDialog` lists all saves.
   - User picks two rows → "Compare selected" → another browser
     tab with the explicit diff.

---

## Why this is one commit

The history client, the dialog, the browser view, and the menu
items don't ship usefully alone. A history client with no menu
item is dead weight. Menu items pointing at non-existent client
methods crash. The pieces have to land together.

Per the user's "small commits" preference, this is the
exception case — atomic landing because the seam is the user
flow, not the file boundary.

---

## Deferred from this sprint

- Compare selected with a saved "baseline".
- Tag / name a report (today: only timestamp + context).
- Bulk delete from `HistoryDialog`.
- Search by snapshot id or text.
- Export the listing as CSV.

---

## What S11 leaves S12 to clean up

- Move legacy code to `legacy/` (the original SV-Abid tree is
  still at repo root).
- Tighten ruff + mypy configs to passing.
- Set up GitHub Actions CI.
- Cut the **0.2.0** release.

S12 is the next sprint.
