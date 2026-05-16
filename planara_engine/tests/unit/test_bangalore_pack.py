"""Smoke test the shipped Bangalore rule pack.

Loads the real production JSON from the package and walks the
classification × zone matrix to confirm each cell resolves to
exactly one applicable rule. Catches accidental cross-wiring of
applies_when fields (e.g. CBD rule that fires on Heritage too)
before it lands on a user.
"""

from __future__ import annotations

import pytest

from planara_engine.rules import applicable_rules
from planara_engine.rules.loader import PACKS_DIR, get_pack, load_pack


@pytest.fixture(autouse=True)
def fresh_pack_cache():
    get_pack.cache_clear()
    yield
    get_pack.cache_clear()


def test_pack_loads_clean() -> None:
    pack = load_pack("Bangalore")
    assert pack.city == "Bangalore"
    assert pack.version == "0.1.0"
    assert len(pack.rules) == 9  # 3 classifications x 3 zones


@pytest.mark.parametrize("classification", ["Heritage", "CBD", "HDZ"])
@pytest.mark.parametrize("zone", ["Residential", "Commercial", "Industry"])
def test_each_cell_has_exactly_one_rule(classification: str, zone: str) -> None:
    pack = load_pack("Bangalore")
    matched = applicable_rules(pack, classification=classification, zone=zone)
    assert len(matched) == 1, (
        f"expected exactly one rule for ({classification}, {zone}), got "
        f"{[r.id for r in matched]}"
    )


def test_pack_ships_inside_package() -> None:
    """The pack must be importable from the installed wheel.

    setuptools.package-data in pyproject already declares it, but
    this test pins that we can resolve it via the PACKS_DIR
    constant the loader uses. If someone moves the dir without
    updating pyproject, this test fails before any user does.
    """

    assert (PACKS_DIR / "bangalore-0.1.0.json").is_file()


def test_fsi_limits_match_legacy_config() -> None:
    """The pack should preserve the legacy SV-Abid fsi-config.json values.

    Lifted from SV-Abid/config/fsi-config.json. The migration is
    a format change, not a values change.
    """

    pack = load_pack("Bangalore")
    by_id = {r.id: r for r in pack.rules}

    expected: dict[str, float] = {
        "blr.fsi.heritage.residential": 1.0,
        "blr.fsi.heritage.commercial": 1.5,
        "blr.fsi.heritage.industry": 0.8,
        "blr.fsi.cbd.residential": 2.5,
        "blr.fsi.cbd.commercial": 4.0,
        "blr.fsi.cbd.industry": 3.0,
        "blr.fsi.hdz.residential": 1.2,
        "blr.fsi.hdz.commercial": 2.0,
        "blr.fsi.hdz.industry": 1.5,
    }

    for rid, limit in expected.items():
        assert rid in by_id
        assert by_id[rid].params["max_fsi"] == limit
