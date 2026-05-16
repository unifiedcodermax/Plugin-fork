"""Report-to-report diff: regression tracking for validation runs.

Two ArchivalReports (a "prev" baseline and a "curr" current) reduce
to a ReportDiff that classifies each rule's outcome:

  added      — a violation that fired in curr but not in prev
                (something the user newly broke).
  removed    — fired in prev but not in curr (something the user
                fixed).
  changed    — same rule_id in both, but severity or computed
                values differ (still failing, but the numbers
                moved — could be better or worse).
  unchanged  — same rule_id in both, identical severity + computed.

Identifying key is ``rule_id``. The engine emits stable rule IDs
(blr.fsi.cbd.residential, mum.overlay.crz.fsi, etc.), so the same
rule across two runs is reliably the same row in this diff.

The diff is pure: no DB, no I/O. Routes load two stored payloads,
parse them into ArchivalReports, and call diff_reports.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from planara_engine.domain import Violation
from planara_engine.reporting import ArchivalReport


class DiffStatus(StrEnum):
    added = "added"
    removed = "removed"
    changed = "changed"
    unchanged = "unchanged"


class Verdict(StrEnum):
    """Overall direction of the change."""

    improved = "improved"
    regressed = "regressed"
    unchanged = "unchanged"
    mixed = "mixed"


class ViolationDiff(BaseModel):
    """One rule's row in the diff.

    rule_id:   stable, namespaced rule id (e.g. blr.fsi.cbd.residential).
    category:  pulled from whichever side has the rule — for ``added``
               it's curr's, for ``removed`` it's prev's, for changed/
               unchanged both agree.
    status:    see DiffStatus.
    prev:      the Violation as it appeared in the baseline report,
               or None when status="added".
    curr:      the Violation as it appears in the current report,
               or None when status="removed".
    """

    rule_id: str
    category: str
    status: DiffStatus
    prev: Violation | None = None
    curr: Violation | None = None


class MetricDelta(BaseModel):
    """One metrics-dict entry's change across runs.

    key:    metrics key (fsi, coverage_pct, rule_pack_version, ...).
    prev:   value in the baseline; None when the key was missing.
    curr:   value in current; None when the key was missing.
    delta:  numeric (curr - prev) when both sides are numbers, else None.
    """

    key: str
    prev: Any = None
    curr: Any = None
    delta: float | None = None


class ReportDiff(BaseModel):
    """Full diff envelope.

    overall:  human-friendly summary of which direction we went.
              improved   added=0, removed>0
              regressed  added>0, removed=0
              unchanged  added=removed=0  (changed-only counts here;
                         the UI surfaces summary['changed'] separately)
              mixed      both added and removed > 0 (refactor; some
                         issues fixed, others introduced)
    """

    from_report_id: UUID
    to_report_id: UUID
    from_generated_at: datetime
    to_generated_at: datetime

    summary: dict[str, int] = Field(
        description="Counts keyed by DiffStatus value (added/removed/changed/unchanged)."
    )
    overall: Verdict

    violations: list[ViolationDiff]
    metrics: list[MetricDelta]


# ---- core --------------------------------------------------------------------


def diff_reports(prev: ArchivalReport, curr: ArchivalReport) -> ReportDiff:
    """Compute the ReportDiff between two archived runs.

    ``prev`` is the baseline ("from"), ``curr`` is the new state
    ("to"). Order matters — added/removed are relative to that.
    """

    prev_by_id = {v.rule_id: v for v in prev.response.violations}
    curr_by_id = {v.rule_id: v for v in curr.response.violations}

    violations: list[ViolationDiff] = []
    # Stable order: walk prev first, then curr's added-only keys.
    seen: set[str] = set()
    for rid, p in prev_by_id.items():
        seen.add(rid)
        c = curr_by_id.get(rid)
        if c is None:
            violations.append(
                ViolationDiff(
                    rule_id=rid, category=p.category, status=DiffStatus.removed, prev=p
                )
            )
        elif _violations_equal(p, c):
            violations.append(
                ViolationDiff(
                    rule_id=rid,
                    category=p.category,
                    status=DiffStatus.unchanged,
                    prev=p,
                    curr=c,
                )
            )
        else:
            violations.append(
                ViolationDiff(
                    rule_id=rid,
                    category=p.category,
                    status=DiffStatus.changed,
                    prev=p,
                    curr=c,
                )
            )
    for rid, c in curr_by_id.items():
        if rid in seen:
            continue
        violations.append(
            ViolationDiff(
                rule_id=rid, category=c.category, status=DiffStatus.added, curr=c
            )
        )

    summary = {s.value: 0 for s in DiffStatus}
    for v in violations:
        summary[v.status.value] += 1

    metrics = _diff_metrics(prev.response.metrics, curr.response.metrics)

    return ReportDiff(
        from_report_id=prev.report_id,
        to_report_id=curr.report_id,
        from_generated_at=prev.generated_at,
        to_generated_at=curr.generated_at,
        summary=summary,
        overall=_verdict(summary),
        violations=violations,
        metrics=metrics,
    )


# ---- helpers -----------------------------------------------------------------


def _violations_equal(a: Violation, b: Violation) -> bool:
    """Two Violations are 'the same outcome' iff severity and computed
    values match. Message text is derived from those values so we
    don't compare it independently — a message-only divergence would
    mean someone changed the template, which is a rule-pack edit
    rather than a user-visible regression."""

    return a.severity == b.severity and a.computed == b.computed


def _diff_metrics(
    prev: dict[str, Any], curr: dict[str, Any]
) -> list[MetricDelta]:
    keys = sorted(set(prev) | set(curr))
    out: list[MetricDelta] = []
    for k in keys:
        p = prev.get(k)
        c = curr.get(k)
        if p == c:
            # Skip identical metrics from the diff; the list would
            # otherwise be dominated by noise. The diff stays focused
            # on what actually changed.
            continue
        delta = _numeric_delta(p, c)
        out.append(MetricDelta(key=k, prev=p, curr=c, delta=delta))
    return out


def _numeric_delta(prev: Any, curr: Any) -> float | None:
    if isinstance(prev, (int, float)) and isinstance(curr, (int, float)):
        return float(curr) - float(prev)
    return None


def _verdict(summary: dict[str, int]) -> Verdict:
    """Direction of change. Driven only by set membership (added /
    removed), not by changed-counts.

    Why: 'changed' means the same rule fires in both runs but the
    numbers moved. Whether that's better or worse depends on the
    metric (lower-FSI is better, higher-open-space is better). We
    refuse to guess; the caller reads ``summary['changed']`` for a
    finer signal."""

    added = summary["added"]
    removed = summary["removed"]

    if added == 0 and removed == 0:
        return Verdict.unchanged
    if added == 0:
        return Verdict.improved
    if removed == 0:
        return Verdict.regressed
    # Both added and removed > 0 — a refactor: some violations gone,
    # others introduced. Caller decides whether that's good or bad.
    return Verdict.mixed
