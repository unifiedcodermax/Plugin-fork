"""HTML view for ReportDiff — regression tracking, visual form.

Same hand-rolled approach as html_renderer.py: html.escape on every
interpolated value, f-string templating, single inline stylesheet so
the document is self-contained. No external deps.
"""

from __future__ import annotations

from html import escape
from typing import Any

from planara_engine.reporting.diff import (
    DiffStatus,
    MetricDelta,
    ReportDiff,
    Verdict,
    ViolationDiff,
)


def render_diff_html(diff: ReportDiff) -> str:
    """Render the diff as a standalone HTML document."""

    title = f"Planara regression report — {diff.from_report_id} → {diff.to_report_id}"
    return _DOC_TEMPLATE.format(
        title=escape(title),
        style=_CSS,
        header=_render_header(diff),
        verdict=_render_verdict(diff),
        summary=_render_summary(diff),
        violations=_render_violations(diff.violations),
        metrics=_render_metrics(diff.metrics),
    )


# ---- sections ----------------------------------------------------------------


def _render_header(diff: ReportDiff) -> str:
    rows = [
        ("From", str(diff.from_report_id)),
        ("To", str(diff.to_report_id)),
        ("From generated (UTC)", diff.from_generated_at.strftime("%Y-%m-%d %H:%M:%S")),
        ("To generated (UTC)", diff.to_generated_at.strftime("%Y-%m-%d %H:%M:%S")),
    ]
    body = "".join(
        f'<dt>{escape(k)}</dt><dd>{escape(v)}</dd>' for k, v in rows
    )
    return f'<section class="header"><h1>Regression report</h1><dl>{body}</dl></section>'


def _render_verdict(diff: ReportDiff) -> str:
    v = diff.overall
    msg, cls = _VERDICT_DISPLAY[v]
    return (
        f'<section class="verdict {cls}">'
        f'<h2>{escape(msg)}</h2>'
        f'<p>{escape(_verdict_explainer(diff))}</p>'
        f'</section>'
    )


_VERDICT_DISPLAY: dict[Verdict, tuple[str, str]] = {
    Verdict.improved: ("IMPROVED", "ok"),
    Verdict.regressed: ("REGRESSED", "fail"),
    Verdict.mixed: ("MIXED", "warn"),
    Verdict.unchanged: ("UNCHANGED", "neutral"),
}


def _verdict_explainer(diff: ReportDiff) -> str:
    s = diff.summary
    parts = []
    if s.get("added"):
        parts.append(f"{s['added']} new violation{'s' if s['added'] != 1 else ''}")
    if s.get("removed"):
        parts.append(f"{s['removed']} resolved")
    if s.get("changed"):
        parts.append(f"{s['changed']} changed")
    if not parts:
        return "No violations changed between these runs."
    return ", ".join(parts) + "."


def _render_summary(diff: ReportDiff) -> str:
    s = diff.summary
    cells = "".join(
        f'<dt>{escape(k.title())}</dt><dd>{s.get(k, 0)}</dd>'
        for k in ("added", "removed", "changed", "unchanged")
    )
    return f'<section class="summary"><h2>Summary</h2><dl class="summary-grid">{cells}</dl></section>'


def _render_violations(violations: list[ViolationDiff]) -> str:
    if not violations:
        return '<section class="violations"><h2>Violations</h2><p class="empty">None.</p></section>'

    # Group by status; order: added (what broke) → removed (what was
    # fixed) → changed → unchanged. Most actionable first.
    order = [DiffStatus.added, DiffStatus.removed, DiffStatus.changed, DiffStatus.unchanged]
    by_status: dict[DiffStatus, list[ViolationDiff]] = {s: [] for s in order}
    for v in violations:
        by_status[v.status].append(v)

    blocks: list[str] = []
    for status in order:
        rows = by_status[status]
        if not rows:
            continue
        body = "".join(_render_violation_row(v) for v in rows)
        blocks.append(
            f'<h3 class="status-{escape(status.value)}">'
            f'{escape(status.value.title())} ({len(rows)})</h3>'
            f'<table><thead><tr>'
            f'<th class="rule-col">Rule</th>'
            f'<th class="cat-col">Category</th>'
            f'<th>Before</th>'
            f'<th>After</th>'
            f'</tr></thead><tbody>{body}</tbody></table>'
        )
    return f'<section class="violations"><h2>Violations</h2>{"".join(blocks)}</section>'


def _render_violation_row(v: ViolationDiff) -> str:
    return (
        f'<tr class="row-{escape(v.status.value)}">'
        f'<td><code>{escape(v.rule_id)}</code></td>'
        f'<td>{escape(v.category)}</td>'
        f'<td>{_render_violation_cell(v.prev)}</td>'
        f'<td>{_render_violation_cell(v.curr)}</td>'
        f'</tr>'
    )


def _render_violation_cell(violation: Any) -> str:
    if violation is None:
        return '<span class="missing">—</span>'
    sev = violation.severity.value if hasattr(violation.severity, "value") else str(violation.severity)
    return (
        f'<span class="pill pill-{escape(sev)}">{escape(sev)}</span> '
        f'{escape(violation.message)}'
    )


def _render_metrics(metrics: list[MetricDelta]) -> str:
    if not metrics:
        return '<section class="metrics"><h2>Metrics</h2><p class="empty">No metric changes.</p></section>'

    rows = "".join(_render_metric_row(m) for m in metrics)
    return (
        f'<section class="metrics"><h2>Metrics</h2>'
        f'<table><thead><tr>'
        f'<th>Key</th><th>Before</th><th>After</th><th>Δ</th>'
        f'</tr></thead><tbody>{rows}</tbody></table></section>'
    )


def _render_metric_row(m: MetricDelta) -> str:
    delta_str = f"{m.delta:+g}" if m.delta is not None else "—"
    return (
        f'<tr>'
        f'<td><code>{escape(m.key)}</code></td>'
        f'<td>{escape(_fmt_value(m.prev))}</td>'
        f'<td>{escape(_fmt_value(m.curr))}</td>'
        f'<td class="delta">{escape(delta_str)}</td>'
        f'</tr>'
    )


def _fmt_value(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


# ---- template + style --------------------------------------------------------


_DOC_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{style}</style>
</head>
<body>
{header}
{verdict}
{summary}
{violations}
{metrics}
</body>
</html>
"""

_CSS = """
:root {
  color-scheme: light;
  --fg: #1f2328;
  --muted: #5e6471;
  --border: #d0d7de;
  --bg: #ffffff;
  --error-bg: #ffe9e9;
  --error-fg: #a40e0e;
  --warning-bg: #fff5d1;
  --warning-fg: #7a5b00;
  --ok-bg: #e7f7e8;
  --ok-fg: #167314;
  --info-bg: #eef4ff;
  --info-fg: #2256a4;
  --neutral-bg: #f3f4f6;
  --neutral-fg: #5e6471;
  --added-fg: #a40e0e;
  --removed-fg: #167314;
  --changed-fg: #7a5b00;
}
* { box-sizing: border-box; }
body { font-family: system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 32px; max-width: 1000px; color: var(--fg); background: var(--bg); }
h1 { font-size: 22px; margin: 0 0 18px 0; }
h2 { font-size: 16px; margin: 28px 0 10px 0; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
h3 { font-size: 13px; font-weight: 600; margin: 18px 0 6px 0; text-transform: uppercase; letter-spacing: 0.04em; }
h3.status-added    { color: var(--added-fg); }
h3.status-removed  { color: var(--removed-fg); }
h3.status-changed  { color: var(--changed-fg); }
h3.status-unchanged { color: var(--muted); }
dl { display: grid; grid-template-columns: 200px 1fr; gap: 4px 16px; margin: 0; font-size: 13px; }
dt { font-weight: 600; color: var(--muted); }
.summary-grid { grid-template-columns: repeat(4, 1fr); font-size: 13px; text-align: center; }
.summary-grid dt { color: var(--muted); }
.summary-grid dd { margin: 0; font-size: 22px; font-weight: 600; }
section.verdict { padding: 16px 20px; border-radius: 8px; margin: 18px 0; }
section.verdict h2 { border: none; margin: 0 0 6px 0; padding: 0; font-size: 20px; }
section.verdict p { margin: 0; font-size: 13px; }
section.verdict.ok      { background: var(--ok-bg); color: var(--ok-fg); }
section.verdict.fail    { background: var(--error-bg); color: var(--error-fg); }
section.verdict.warn    { background: var(--warning-bg); color: var(--warning-fg); }
section.verdict.neutral { background: var(--neutral-bg); color: var(--neutral-fg); }
table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 14px; }
th, td { text-align: left; padding: 7px 9px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: 10px; }
.rule-col { width: 32%; }
.cat-col { width: 90px; }
tr.row-added    { background: rgba(164, 14, 14, 0.04); }
tr.row-removed  { background: rgba(22, 115, 20, 0.04); }
tr.row-changed  { background: rgba(122, 91, 0, 0.04); }
.pill { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10px; font-weight: 600; text-transform: uppercase; margin-right: 6px; }
.pill-error   { background: var(--error-bg);   color: var(--error-fg); }
.pill-warning { background: var(--warning-bg); color: var(--warning-fg); }
.pill-info    { background: var(--info-bg);    color: var(--info-fg); }
.missing { color: var(--muted); }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.delta { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }
.empty { color: var(--muted); font-style: italic; }
"""
