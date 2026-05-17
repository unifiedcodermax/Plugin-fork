"""RuleEngine: registry behavior, dispatch, message rendering."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from planara_engine.core.errors import RuleEvaluationError
from planara_engine.domain import (
    Building,
    Floor,
    Plot,
    Polygon,
    ProjectContext,
    Severity,
    Snapshot,
)
from planara_engine.engine import EvaluationResult, evaluate, registry
from planara_engine.rules import loader as rules_loader


@pytest.fixture(autouse=True)
def fresh_registry() -> Iterator[None]:
    registry._reset_for_tests()
    yield
    registry._reset_for_tests()


@pytest.fixture
def packs_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect rules.loader.PACKS_DIR to a per-test tmp dir."""

    target = tmp_path / "packs"
    target.mkdir()
    monkeypatch.setattr(rules_loader, "PACKS_DIR", target)
    rules_loader.get_pack.cache_clear()
    yield target
    rules_loader.get_pack.cache_clear()


def _square(size: float = 10.0) -> Polygon:
    return Polygon(exterior=[[0, 0], [size, 0], [size, size], [0, size]])


def _snapshot(classification: str = "CBD", zone: str = "Residential") -> Snapshot:
    return Snapshot(
        project=ProjectContext(city="Testopolis", classification=classification, zone=zone),
        plot=Plot(polygon=_square(20.0), area_m2=400.0),
        building=Building(floors=[Floor(level=0, polygon=_square(10.0), height_m=3.0)]),
    )


def _write_pack(packs_dir: Path, rules: list[dict]) -> None:
    (packs_dir / "testopolis-0.1.0.json").write_text(
        json.dumps({"city": "Testopolis", "version": "0.1.0", "rules": rules}),
        encoding="utf-8",
    )


# ---- registry ----------------------------------------------------------------


def test_register_and_lookup() -> None:
    @registry.register("noop")
    def _noop(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(passed=True)

    assert "noop" in registry.known_evaluators()
    assert registry.get("noop") is _noop


def test_duplicate_registration_raises() -> None:
    @registry.register("dup")
    def _a(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(passed=True)

    with pytest.raises(RuleEvaluationError, match="already registered"):

        @registry.register("dup")
        def _b(snapshot, rule):  # type: ignore[no-untyped-def]
            return EvaluationResult(passed=True)


def test_unknown_evaluator_lookup_raises() -> None:
    with pytest.raises(RuleEvaluationError, match="unknown evaluator"):
        registry.get("does-not-exist")


# ---- engine dispatch ---------------------------------------------------------


def test_engine_passes_with_no_violations(packs_dir: Path) -> None:
    @registry.register("always_pass")
    def _passer(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(passed=True, computed={"value": 1.0})

    _write_pack(
        packs_dir,
        [{"id": "r.pass", "category": "test", "evaluator": "always_pass"}],
    )

    response = evaluate(_snapshot())

    assert response.ok is True
    assert response.violations == []
    assert response.metrics["value"] == 1.0
    assert response.metrics["rule_count"] == 1
    assert response.metrics["rule_pack_version"] == "0.1.0"


def test_engine_records_violation(packs_dir: Path) -> None:
    @registry.register("always_fail")
    def _failer(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(
            passed=False,
            computed={"actual": 3.1, "limit": 2.5},
        )

    _write_pack(
        packs_dir,
        [
            {
                "id": "r.fail",
                "category": "fsi",
                "applies_when": {"classification": "CBD", "zone": "Residential"},
                "evaluator": "always_fail",
                "params": {"limit": 2.5},
                "message_template": "value {actual} exceeds limit {limit}",
            }
        ],
    )

    response = evaluate(_snapshot())

    assert response.ok is False
    assert len(response.violations) == 1
    v = response.violations[0]
    assert v.rule_id == "r.fail"
    assert v.severity is Severity.error
    assert v.message == "value 3.1 exceeds limit 2.5"


def test_engine_skips_non_applicable_rules(packs_dir: Path) -> None:
    @registry.register("always_fail")
    def _failer(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(passed=False)

    _write_pack(
        packs_dir,
        [
            {
                "id": "r.heritage_only",
                "category": "fsi",
                "applies_when": {"classification": "Heritage"},
                "evaluator": "always_fail",
            }
        ],
    )

    response = evaluate(_snapshot(classification="CBD"))
    assert response.ok is True


def test_engine_severity_override(packs_dir: Path) -> None:
    @registry.register("warn_only")
    def _warner(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(passed=False, severity_override=Severity.warning)

    _write_pack(
        packs_dir,
        [{"id": "r.w", "category": "fsi", "evaluator": "warn_only"}],
    )

    response = evaluate(_snapshot())
    assert response.ok is True  # warnings don't flip ok
    assert response.violations[0].severity is Severity.warning


def test_engine_missing_template_field_does_not_crash(packs_dir: Path) -> None:
    @registry.register("typo_template")
    def _e(snapshot, rule):  # type: ignore[no-untyped-def]
        return EvaluationResult(passed=False, computed={"actual": 1})

    _write_pack(
        packs_dir,
        [
            {
                "id": "r.typo",
                "category": "x",
                "evaluator": "typo_template",
                "message_template": "value {wrong_key} is bad",
            }
        ],
    )

    response = evaluate(_snapshot())
    # SafeDict keeps the placeholder verbatim, plugin still shows
    # something useful and we don't 500 over a typo'd rule.
    assert response.violations[0].message == "value {wrong_key} is bad"
