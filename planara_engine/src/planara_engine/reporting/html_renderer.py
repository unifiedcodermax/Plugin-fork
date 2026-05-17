"""HTML compliance report.

Produces a self-contained HTML document a user can save, email, or
attach to a submission package. No external templating dependency —
hand-rolled with ``html.escape`` and f-strings. One report shape;
when we grow to multiple variants (per-city branding, summary vs
detailed) the right move is to lift the markup into Jinja templates
and keep this function as the entry point.

Inputs are the *same* Snapshot and ValidationResponse that flow
through /validate. The renderer is pure: callers re-run validate
themselves when they need a fresh result.
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from typing import Any

from planara_engine.domain import Snapshot, ValidationResponse, Violation


def render_html(
    snapshot: Snapshot,
    response: ValidationResponse,
    *,
    generated_at: datetime | None = None,
) -> str:
    """Render the snapshot+response pair as a standalone HTML doc.

    ``generated_at`` is injectable so tests can pin the timestamp;
    production callers pass None and get the current UTC time.
    """

    ts = generated_at or datetime.now(UTC)

    title = (
        f"Planara compliance report — "
        f"{snapshot.project.city} / {snapshot.project.classification} / {snapshot.project.zone}"
    )

    return _DOC_TEMPLATE.format(
        title=escape(title),
        style=_CSS,
        header=_render_header(snapshot, response, ts),
        summary=_render_summary(response),
        violations=_render_violations(response.violations),
        metrics=_render_metrics(response.metrics),
        footer=_render_footer(snapshot, response, ts),
    )


# ---- sections ----------------------------------------------------------------


def _render_header(
    snapshot: Snapshot, response: ValidationResponse, ts: datetime
) -> str:
    p = snapshot.project
    overlays = ", ".join(p.overlays) if p.overlays else "—"
    rows = [
        ("City", p.city),
        ("Classification", p.classification),
        ("Zone", p.zone),
        ("Overlays", overlays),
        ("Snapshot ID", str(snapshot.snapshot_id)),
        ("Rule pack", str(response.metrics.get("rule_pack_version", "—"))),
        ("Generated (UTC)", ts.strftime("%Y-%m-%d %H:%M:%S")),
    ]
    body = "".join(
        f'<dt>{escape(k)}</dt><dd>{escape(v)}</dd>' for k, v in rows
    )
    return f'<section class="header"><h1>Planara compliance report</h1><dl>{body}</dl></section>'


def _render_summary(response: ValidationResponse) -> str:
    n = len(response.violations)
    n_err = sum(1 for v in response.violations if v.severity == "error")
    n_warn = sum(1 for v in response.violations if v.severity == "warning")

    if response.ok and n == 0:
        verdict = "PASS"
        msg = "Design is compliant with every rule that fired."
        cls = "ok"
    elif response.ok:
        # warnings only — passes but worth flagging.
        verdict = "PASS WITH WARNINGS"
        msg = f"{n_warn} warning{'s' if n_warn != 1 else ''} — no blocking violations."
        cls = "warn"
    else:
        verdict = "FAIL"
        msg = f"{n_err} error{'s' if n_err != 1 else ''}, {n_warn} warning{'s' if n_warn != 1 else ''}."
        cls = "fail"

    return (
        f'<section class="summary {cls}">'
        f'<h2>{escape(verdict)}</h2>'
        f'<p>{escape(msg)}</p>'
        f'</section>'
    )


def _render_violations(violations: list[Violation]) -> str:
    if not violations:
        return '<section class="violations"><h2>Violations</h2><p class="empty">None.</p></section>'

    # Group by category for readability; sort categories alphabetically
    # but preserve insertion order within a category (engine emits in
    # rule-pack order).
    by_cat: dict[str, list[Violation]] = {}
    for v in violations:
        by_cat.setdefault(v.category, []).append(v)

    blocks: list[str] = []
    for cat in sorted(by_cat):
        rows = "".join(_render_violation_row(v) for v in by_cat[cat])
        blocks.append(
            f'<h3>{escape(cat.title())}</h3>'
            f'<table><thead><tr>'
            f'<th class="sev-col">Severity</th>'
            f'<th class="rule-col">Rule</th>'
            f'<th>Message</th>'
            f'</tr></thead><tbody>{rows}</tbody></table>'
        )
    return f'<section class="violations"><h2>Violations</h2>{"".join(blocks)}</section>'


def _render_violation_row(v: Violation) -> str:
    sev = v.severity.value if hasattr(v.severity, "value") else str(v.severity)
    return (
        f'<tr class="row-{escape(sev)}">'
        f'<td><span class="pill pill-{escape(sev)}">{escape(sev)}</span></td>'
        f'<td><code>{escape(v.rule_id)}</code></td>'
        f'<td>{escape(v.message)}</td>'
        f'</tr>'
    )


def _render_metrics(metrics: dict[str, Any]) -> str:
    if not metrics:
        return ""

    # Stable order — rule_pack_version and rule_count surface first
    # because the user reads them most; everything else alphabetical.
    pinned = ["rule_pack_version", "rule_count"]
    keys = [k for k in pinned if k in metrics] + sorted(
        k for k in metrics if k not in pinned
    )
    rows = "".join(
        f'<dt>{escape(str(k))}</dt><dd>{escape(_fmt_metric(metrics[k]))}</dd>'
        for k in keys
    )
    return f'<section class="metrics"><h2>Metrics</h2><dl>{rows}</dl></section>'


def _fmt_metric(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    if isinstance(value, list):
        return ", ".join(str(v) for v in value) or "—"
    return str(value)


def _render_footer(
    snapshot: Snapshot, response: ValidationResponse, ts: datetime
) -> str:
    bits = [
        f"Snapshot schema {escape(snapshot.schema_version)}",
        f"Generated {escape(ts.isoformat())}",
    ]
    return f'<footer>{" · ".join(bits)}</footer>'


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
{summary}
{violations}
{metrics}
{footer}
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
}
* { box-sizing: border-box; }
body { font-family: system-ui, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 32px; max-width: 920px; color: var(--fg); background: var(--bg); }
h1 { font-size: 22px; margin: 0 0 18px 0; }
h2 { font-size: 16px; margin: 28px 0 10px 0; padding-bottom: 4px; border-bottom: 1px solid var(--border); }
h3 { font-size: 13px; font-weight: 600; margin: 18px 0 6px 0; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }
dl { display: grid; grid-template-columns: 180px 1fr; gap: 4px 16px; margin: 0; font-size: 13px; }
dt { font-weight: 600; color: var(--muted); }
section.summary { padding: 14px 18px; border-radius: 8px; margin: 18px 0; }
section.summary h2 { border: none; margin: 0 0 6px 0; padding: 0; font-size: 18px; }
section.summary p { margin: 0; font-size: 13px; }
section.summary.ok { background: var(--ok-bg); color: var(--ok-fg); }
section.summary.warn { background: var(--warning-bg); color: var(--warning-fg); }
section.summary.fail { background: var(--error-bg); color: var(--error-fg); }
table { width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 14px; }
th, td { text-align: left; padding: 7px 9px; border-bottom: 1px solid var(--border); vertical-align: top; }
th { font-weight: 600; color: var(--muted); text-transform: uppercase; font-size: 10px; }
.sev-col { width: 90px; }
.rule-col { width: 32%; }
.pill { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 10px; font-weight: 600; text-transform: uppercase; }
.pill-error { background: var(--error-bg); color: var(--error-fg); }
.pill-warning { background: var(--warning-bg); color: var(--warning-fg); }
.pill-info { background: #eef4ff; color: #2256a4; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; }
.empty { color: var(--muted); font-style: italic; }
footer { margin-top: 36px; padding-top: 12px; border-top: 1px solid var(--border); font-size: 11px; color: var(--muted); }
"""
