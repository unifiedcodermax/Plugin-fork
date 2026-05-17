"""Unit tests for the report-to-report diff."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    ProjectContext,
    Severity,
    Snapshot,
    ValidationResponse,
    Violation,
)
from planara_engine.reporting import (
    ArchivalReport,
    DiffStatus,
    Verdict,
    diff_reports,
    render_archive,
    render_diff_html,
)

# ---- fixtures ----------------------------------------------------------------


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> Polygon:
    return Polygon(
        exterior=[[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]
    )


def _snap() -> Snapshot:
    return Snapshot(
        project=ProjectContext(city="Bangalore", classification="CBD", zone="Residential"),
        plot=Plot(polygon=_square(50.0)),
        building=Building(
            floors=[Floor(level=0, polygon=_square(10.0, 20.0, 20.0), height_m=3.0)],
            parking_slots_provided=2,
        ),
    )


def _v(rule_id: str, *, category: str = "fsi", severity: Severity = Severity.error, computed: dict | None = None, message: str = "x") -> Violation:
    return Violation(
        rule_id=rule_id,
        category=category,
        severity=severity,
        message=message,
        computed=computed or {},
    )


def _resp(*vs: Violation, metrics: dict | None = None, ok: bool | None = None) -> ValidationResponse:
    from uuid import uuid4
    return ValidationResponse(
        snapshot_id=uuid4(),
        ok=ok if ok is not None else not any(v.severity == Severity.error for v in vs),
        violations=list(vs),
        metrics=metrics or {},
    )


def _arc(*vs: Violation, metrics: dict | None = None, ts: datetime | None = None, ok: bool | None = None) -> ArchivalReport:
    return render_archive(_snap(), _resp(*vs, metrics=metrics, ok=ok), generated_at=ts or datetime(2026, 1, 1, tzinfo=UTC))


# ---- structural --------------------------------------------------------------


def test_diff_carries_report_ids_and_timestamps() -> None:
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = t1 + timedelta(hours=2)
    prev = _arc(ts=t1)
    curr = _arc(ts=t2)
    d = diff_reports(prev, curr)
    assert d.from_report_id == prev.report_id
    assert d.to_report_id == curr.report_id
    assert d.from_generated_at == t1
    assert d.to_generated_at == t2


# ---- classification ----------------------------------------------------------


def test_identical_reports_all_unchanged() -> None:
    v = _v("blr.fsi.cbd.residential", computed={"fsi": 2.0, "max_fsi": 2.5})
    prev = _arc(v)
    curr = _arc(v)
    d = diff_reports(prev, curr)
    assert d.summary == {"added": 0, "removed": 0, "changed": 0, "unchanged": 1}
    assert d.overall == Verdict.unchanged


def test_added_violation_when_curr_only() -> None:
    """User introduced a new violation. Verdict: regressed."""

    prev = _arc()  # zero violations
    curr = _arc(_v("blr.fsi.cbd.residential"))
    d = diff_reports(prev, curr)
    assert d.summary == {"added": 1, "removed": 0, "changed": 0, "unchanged": 0}
    assert d.violations[0].status == DiffStatus.added
    assert d.violations[0].prev is None
    assert d.violations[0].curr is not None
    assert d.overall == Verdict.regressed


def test_removed_violation_when_prev_only() -> None:
    """User fixed a violation. Verdict: improved."""

    prev = _arc(_v("blr.fsi.cbd.residential"))
    curr = _arc()  # cleared it
    d = diff_reports(prev, curr)
    assert d.summary == {"added": 0, "removed": 1, "changed": 0, "unchanged": 0}
    assert d.violations[0].status == DiffStatus.removed
    assert d.violations[0].prev is not None
    assert d.violations[0].curr is None
    assert d.overall == Verdict.improved


def test_changed_when_severity_differs() -> None:
    """Severity flip (warning -> error) is a change, not an
    add+remove. Pins the rule_id-based identity."""

    prev = _arc(_v("r", severity=Severity.warning, computed={"fsi": 2.45}))
    curr = _arc(_v("r", severity=Severity.error, computed={"fsi": 2.45}))
    d = diff_reports(prev, curr)
    assert d.summary["changed"] == 1
    assert d.violations[0].status == DiffStatus.changed


def test_changed_when_computed_values_differ() -> None:
    """FSI moved but rule still fires — same rule_id, different
    numbers. Still 'changed', not added+removed."""

    prev = _arc(_v("r", computed={"fsi": 2.6, "max_fsi": 2.5}))
    curr = _arc(_v("r", computed={"fsi": 2.8, "max_fsi": 2.5}))
    d = diff_reports(prev, curr)
    assert d.summary["changed"] == 1
    diff = d.violations[0]
    assert diff.prev.computed["fsi"] == 2.6
    assert diff.curr.computed["fsi"] == 2.8


def test_unchanged_ignores_message_text_differences() -> None:
    """If a rule template changes wording but severity + computed are
    unchanged, the diff treats the row as unchanged. A message-only
    delta is a rule-pack edit, not a user-visible regression."""

    prev = _arc(_v("r", computed={"fsi": 2.6}, message="FSI 2.6 over 2.5"))
    curr = _arc(_v("r", computed={"fsi": 2.6}, message="FSI 2.60 exceeds 2.50"))
    d = diff_reports(prev, curr)
    assert d.summary["unchanged"] == 1
    assert d.summary["changed"] == 0


# ---- overall verdict ---------------------------------------------------------


def test_mixed_when_both_added_and_removed() -> None:
    """Refactor: fixed one violation, introduced another. Verdict: mixed."""

    prev = _arc(_v("r.a"))
    curr = _arc(_v("r.b"))
    d = diff_reports(prev, curr)
    assert d.summary == {"added": 1, "removed": 1, "changed": 0, "unchanged": 0}
    assert d.overall == Verdict.mixed


def test_changed_only_keeps_verdict_unchanged() -> None:
    """Same rule_id fires in both runs but the numbers moved
    (e.g. FSI 2.6 -> 2.9). We refuse to guess whether higher or
    lower is 'better' for a given metric, so the verdict stays
    'unchanged' and summary['changed'] surfaces the count for any
    UI that wants to flag it."""

    prev = _arc(_v("r", computed={"fsi": 2.6}))
    curr = _arc(_v("r", computed={"fsi": 2.9}))
    d = diff_reports(prev, curr)
    assert d.overall == Verdict.unchanged
    assert d.summary["changed"] == 1


# ---- metrics -----------------------------------------------------------------


def test_metric_delta_numeric() -> None:
    prev = _arc(metrics={"fsi": 2.0, "rule_pack_version": "0.3.0"})
    curr = _arc(metrics={"fsi": 2.4, "rule_pack_version": "0.3.0"})
    d = diff_reports(prev, curr)
    # Only the changed metric is in the diff; identical ones are skipped.
    keys = {m.key for m in d.metrics}
    assert keys == {"fsi"}
    fsi_delta = next(m for m in d.metrics if m.key == "fsi")
    assert fsi_delta.prev == 2.0
    assert fsi_delta.curr == 2.4
    assert fsi_delta.delta is not None
    assert abs(fsi_delta.delta - 0.4) < 1e-9


def test_metric_delta_non_numeric_skips_delta() -> None:
    prev = _arc(metrics={"rule_pack_version": "0.2.0"})
    curr = _arc(metrics={"rule_pack_version": "0.3.0"})
    d = diff_reports(prev, curr)
    m = next(m for m in d.metrics if m.key == "rule_pack_version")
    assert m.prev == "0.2.0"
    assert m.curr == "0.3.0"
    assert m.delta is None


def test_metric_added_or_removed_one_side() -> None:
    prev = _arc(metrics={"a": 1})
    curr = _arc(metrics={"b": 2})
    d = diff_reports(prev, curr)
    a = next(m for m in d.metrics if m.key == "a")
    b = next(m for m in d.metrics if m.key == "b")
    assert a.prev == 1 and a.curr is None
    assert b.prev is None and b.curr == 2


def test_metric_with_no_changes_emits_empty_list() -> None:
    prev = _arc(metrics={"a": 1, "b": "x"})
    curr = _arc(metrics={"a": 1, "b": "x"})
    d = diff_reports(prev, curr)
    assert d.metrics == []


# ---- ordering ----------------------------------------------------------------


def test_violation_ordering_prev_first_then_curr_added() -> None:
    """Stable layout: prev's rules in their original order, then
    curr-only adds appended. Keeps UI rendering predictable."""

    prev = _arc(_v("p1"), _v("p2"))
    curr = _arc(_v("p2", computed={"x": 1}), _v("p1"), _v("c-only"))
    d = diff_reports(prev, curr)
    rule_ids = [vd.rule_id for vd in d.violations]
    # prev order: p1 (unchanged), p2 (changed); then curr-only: c-only.
    assert rule_ids == ["p1", "p2", "c-only"]


# ---- HTML diff renderer ------------------------------------------------------


def test_diff_html_renders_doctype_and_title() -> None:
    d = diff_reports(_arc(), _arc())
    html = render_diff_html(d)
    assert "<!DOCTYPE html>" in html
    assert "Planara regression report" in html
    assert "Regression report" in html


def test_diff_html_verdict_banner_matches_overall() -> None:
    # Regressed: a new violation in curr.
    d = diff_reports(_arc(), _arc(_v("r")))
    html = render_diff_html(d)
    assert "REGRESSED" in html
    assert 'class="verdict fail"' in html

    # Improved: a violation went away.
    d = diff_reports(_arc(_v("r")), _arc())
    html = render_diff_html(d)
    assert "IMPROVED" in html
    assert 'class="verdict ok"' in html

    # Unchanged.
    d = diff_reports(_arc(), _arc())
    html = render_diff_html(d)
    assert "UNCHANGED" in html
    assert 'class="verdict neutral"' in html


def test_diff_html_summary_shows_each_count() -> None:
    """Summary grid carries all four statuses, even when zero."""

    d = diff_reports(_arc(_v("p1"), _v("p2")), _arc(_v("p1"), _v("c1")))
    html = render_diff_html(d)
    assert "Added" in html
    assert "Removed" in html
    assert "Changed" in html
    assert "Unchanged" in html


def test_diff_html_groups_violations_by_status_in_order() -> None:
    """Order: added (most actionable) -> removed -> changed -> unchanged."""

    d = diff_reports(_arc(_v("u")), _arc(_v("u"), _v("a")))
    html = render_diff_html(d)
    added_idx = html.find("Added (1)")
    unchanged_idx = html.find("Unchanged (1)")
    assert added_idx != -1
    assert unchanged_idx != -1
    assert added_idx < unchanged_idx


def test_diff_html_escapes_rule_id_and_message() -> None:
    """No XSS via injected fields."""

    p = _v("<script>", message="prev <b>m</b>")
    c = _v("<script>", message="curr <i>m</i>", computed={"x": 1})
    d = diff_reports(_arc(p), _arc(c))
    html = render_diff_html(d)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<b>m</b>" not in html
    assert "&lt;b&gt;m&lt;/b&gt;" in html


def test_diff_html_metrics_section_shows_deltas() -> None:
    prev = _arc(metrics={"fsi": 2.0})
    curr = _arc(metrics={"fsi": 2.4})
    d = diff_reports(prev, curr)
    html = render_diff_html(d)
    assert "fsi" in html
    # Numeric delta formatted with sign.
    assert "+0.4" in html


def test_diff_html_empty_metrics_renders_none() -> None:
    d = diff_reports(_arc(metrics={"a": 1}), _arc(metrics={"a": 1}))
    html = render_diff_html(d)
    assert "No metric changes" in html


def test_diff_html_missing_side_renders_dash() -> None:
    """Added/removed rows show '—' for the absent side."""

    d = diff_reports(_arc(), _arc(_v("r")))
    html = render_diff_html(d)
    assert "<span class=\"missing\">—</span>" in html
