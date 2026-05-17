"""Unit tests for the reporting renderers (HTML + archival JSON)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from planara_engine import __version__ as ENGINE_VERSION
from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    Project,
    Severity,
    Snapshot,
    ValidationResponse,
    Violation,
)
from planara_engine.reporting import (
    ARCHIVAL_SCHEMA_VERSION,
    render_archive,
    render_html,
)

# ---- fixtures ----------------------------------------------------------------


def _square(size: float, ox: float = 0.0, oy: float = 0.0) -> Polygon:
    return Polygon(
        exterior=[[ox, oy], [ox + size, oy], [ox + size, oy + size], [ox, oy + size]]
    )


def _snap(**project_overrides) -> Snapshot:
    return Snapshot(
        project=Project(
            city=project_overrides.get("city", "Bangalore"),
            classification=project_overrides.get("classification", "CBD"),
            zone=project_overrides.get("zone", "Residential"),
            overlays=project_overrides.get("overlays", []),
        ),
        plot=Plot(polygon=_square(50.0)),
        building=Building(
            floors=[Floor(level=0, polygon=_square(10.0, 20.0, 20.0), height_m=3.0)],
            parking_slots_provided=2,
        ),
    )


def _resp(*violations: Violation, ok: bool | None = None, metrics: dict | None = None) -> ValidationResponse:
    snap_id = UUID(int=0)
    return ValidationResponse(
        snapshot_id=snap_id,
        ok=ok if ok is not None else not any(v.severity == Severity.error for v in violations),
        violations=list(violations),
        metrics=metrics or {"rule_pack_version": "0.3.0", "rule_count": 5},
    )


@pytest.fixture
def fixed_ts() -> datetime:
    return datetime(2026, 1, 15, 12, 30, 0, tzinfo=UTC)


# ---- HTML --------------------------------------------------------------------


def test_html_renders_ok_summary(fixed_ts: datetime) -> None:
    html = render_html(_snap(), _resp(), generated_at=fixed_ts)
    assert "<!DOCTYPE html>" in html
    assert "PASS" in html
    assert "summary ok" in html
    assert "Design is compliant" in html


def test_html_renders_fail_summary(fixed_ts: datetime) -> None:
    v = Violation(rule_id="t.fsi", category="fsi", severity=Severity.error, message="FSI 3.0 > 2.5")
    html = render_html(_snap(), _resp(v), generated_at=fixed_ts)
    assert "FAIL" in html
    assert "summary fail" in html
    assert "1 error" in html


def test_html_renders_warning_only_summary(fixed_ts: datetime) -> None:
    v = Violation(rule_id="t.fsi", category="fsi", severity=Severity.warning, message="close to limit")
    html = render_html(_snap(), _resp(v), generated_at=fixed_ts)
    # ok stays True when no errors fire — Sprint-4 contract.
    assert "PASS WITH WARNINGS" in html
    assert "summary warn" in html
    assert "1 warning" in html


def test_html_violations_table_carries_rule_id_and_message(fixed_ts: datetime) -> None:
    v = Violation(
        rule_id="blr.fsi.cbd.residential",
        category="fsi",
        severity=Severity.error,
        message="FSI 3.43 exceeds the CBD/Residential limit of 2.5.",
    )
    html = render_html(_snap(), _resp(v), generated_at=fixed_ts)
    assert "blr.fsi.cbd.residential" in html
    assert "FSI 3.43 exceeds the CBD/Residential limit of 2.5." in html
    assert 'class="pill pill-error"' in html


def test_html_groups_violations_by_category(fixed_ts: datetime) -> None:
    """Two categories should produce two H3 section headers."""

    vs = [
        Violation(rule_id="t.fsi.a", category="fsi", severity=Severity.error, message="m1"),
        Violation(rule_id="t.setback.b", category="setback", severity=Severity.error, message="m2"),
    ]
    html = render_html(_snap(), _resp(*vs), generated_at=fixed_ts)
    assert "<h3>Fsi</h3>" in html
    assert "<h3>Setback</h3>" in html


def test_html_escapes_violation_message(fixed_ts: datetime) -> None:
    """A rule template that interpolates user-controlled data must not
    break out of HTML context. The renderer must escape <, >, &."""

    v = Violation(
        rule_id="t.x",
        category="fsi",
        severity=Severity.error,
        message="<script>alert('xss')</script>",
    )
    html = render_html(_snap(), _resp(v), generated_at=fixed_ts)
    assert "<script>alert" not in html
    assert "&lt;script&gt;alert" in html


def test_html_escapes_rule_id(fixed_ts: datetime) -> None:
    """Rule IDs are namespaced like blr.foo but the renderer should
    not assume that; it must still escape them."""

    v = Violation(
        rule_id="bad<id>",
        category="fsi",
        severity=Severity.error,
        message="x",
    )
    html = render_html(_snap(), _resp(v), generated_at=fixed_ts)
    assert "bad<id>" not in html
    assert "bad&lt;id&gt;" in html


def test_html_header_carries_project_metadata(fixed_ts: datetime) -> None:
    snap = _snap(city="Mumbai", classification="Island", zone="Commercial", overlays=["crz", "airport"])
    html = render_html(snap, _resp(), generated_at=fixed_ts)
    assert "Mumbai" in html
    assert "Island" in html
    assert "Commercial" in html
    assert "crz, airport" in html


def test_html_header_shows_dash_for_no_overlays(fixed_ts: datetime) -> None:
    html = render_html(_snap(), _resp(), generated_at=fixed_ts)
    assert "<dt>Overlays</dt><dd>—</dd>" in html


def test_html_empty_violations_renders_none(fixed_ts: datetime) -> None:
    html = render_html(_snap(), _resp(), generated_at=fixed_ts)
    assert "<p class=\"empty\">None.</p>" in html


def test_html_metrics_table_pins_rule_pack_version_first(fixed_ts: datetime) -> None:
    """rule_pack_version + rule_count are the most-read metrics; pin
    them above alphabetically-sorted later entries."""

    metrics = {"zebra_metric": 1.0, "fsi": 2.1, "rule_count": 5, "rule_pack_version": "0.3.0"}
    html = render_html(_snap(), _resp(metrics=metrics), generated_at=fixed_ts)
    pack_idx = html.index("rule_pack_version")
    count_idx = html.index("rule_count")
    fsi_idx = html.index(">fsi<")
    zebra_idx = html.index("zebra_metric")
    # pinned keys come first, in declaration order.
    assert pack_idx < count_idx < fsi_idx < zebra_idx


def test_html_footer_carries_schema_version(fixed_ts: datetime) -> None:
    html = render_html(_snap(), _resp(), generated_at=fixed_ts)
    assert "Snapshot schema 1.0" in html
    assert fixed_ts.isoformat() in html


# ---- Archival JSON -----------------------------------------------------------


def test_archive_has_uuid_report_id(fixed_ts: datetime) -> None:
    arch = render_archive(_snap(), _resp(), generated_at=fixed_ts)
    assert isinstance(arch.report_id, UUID)


def test_archive_pins_archival_schema_version(fixed_ts: datetime) -> None:
    arch = render_archive(_snap(), _resp(), generated_at=fixed_ts)
    assert arch.report_schema_version == "1.0"
    assert arch.report_schema_version == ARCHIVAL_SCHEMA_VERSION


def test_archive_stamps_engine_version(fixed_ts: datetime) -> None:
    arch = render_archive(_snap(), _resp(), generated_at=fixed_ts)
    assert arch.engine_version == ENGINE_VERSION


def test_archive_honors_injected_timestamp(fixed_ts: datetime) -> None:
    arch = render_archive(_snap(), _resp(), generated_at=fixed_ts)
    assert arch.generated_at == fixed_ts


def test_archive_each_call_new_report_id() -> None:
    """Two identical render_archive calls must produce different
    report_ids. The id is per-call, not per-snapshot — Sprint 9's
    persistence layer will use it as a primary key."""

    snap, resp = _snap(), _resp()
    a = render_archive(snap, resp)
    b = render_archive(snap, resp)
    assert a.report_id != b.report_id


def test_archive_echoes_snapshot_faithfully(fixed_ts: datetime) -> None:
    snap = _snap(city="Mumbai", classification="Suburbs", zone="Industry", overlays=["airport"])
    arch = render_archive(snap, _resp(), generated_at=fixed_ts)
    assert arch.snapshot.project.city == "Mumbai"
    assert arch.snapshot.project.overlays == ["airport"]
    assert arch.snapshot.building.parking_slots_provided == 2


def test_archive_echoes_response_faithfully(fixed_ts: datetime) -> None:
    v = Violation(rule_id="t.fsi", category="fsi", severity=Severity.error, message="m")
    arch = render_archive(_snap(), _resp(v, metrics={"x": 1}), generated_at=fixed_ts)
    assert arch.response.ok is False
    assert len(arch.response.violations) == 1
    assert arch.response.metrics == {"x": 1}


def test_archive_serializes_to_json(fixed_ts: datetime) -> None:
    """Pin that the report round-trips through JSON. The /reports
    route returns model_dump(mode='json'); a non-serializable field
    addition would fail here before reaching production."""

    arch = render_archive(_snap(), _resp(), generated_at=fixed_ts)
    payload = json.loads(arch.model_dump_json())
    assert payload["report_schema_version"] == "1.0"
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["generated_at"].startswith("2026-01-15")
    assert "snapshot" in payload and "response" in payload
