"""Smoke test the shipped Bangalore rule pack.

Loads the real production JSON from the package and walks the
classification × zone matrix to confirm each cell resolves to
the expected set of rules. Catches accidental cross-wiring of
applies_when fields (e.g. CBD rule that fires on Heritage too)
before it lands on a user.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from planara_engine.rules import applicable_rules
from planara_engine.rules.loader import PACKS_DIR, get_pack, load_pack

# Bumped per pack version. Update alongside the JSON.
CURRENT_VERSION = "0.3.0"

# Categories expected to fire for every (classification, zone) cell
# when NO overlays are active. Overlay-only categories (e.g. height)
# are tested separately below.
EXPECTED_CATEGORIES_PER_CELL = {"fsi", "setback", "coverage", "open_space", "parking"}


@pytest.fixture(autouse=True)
def fresh_pack_cache() -> Iterator[None]:
    get_pack.cache_clear()
    yield
    get_pack.cache_clear()


def test_pack_loads_clean() -> None:
    pack = load_pack("Bangalore")
    assert pack.city == "Bangalore"
    assert pack.version == CURRENT_VERSION
    # 9 FSI + 9 setback + 3 coverage + 3 open_space + 3 parking
    # + 2 overlay height = 29.
    assert len(pack.rules) == 29


@pytest.mark.parametrize("classification", ["Heritage", "CBD", "HDZ"])
@pytest.mark.parametrize("zone", ["Residential", "Commercial", "Industry"])
def test_each_cell_has_every_category(classification: str, zone: str) -> None:
    """Every (classification, zone) should fire exactly one rule per
    Sprint-4 category. Catches an applies_when typo that would leave
    a category silently unenforced."""

    pack = load_pack("Bangalore")
    matched = applicable_rules(pack, classification=classification, zone=zone)
    cats = [r.category for r in matched]
    assert set(cats) == EXPECTED_CATEGORIES_PER_CELL, (
        f"({classification}, {zone}) missing categories: "
        f"{EXPECTED_CATEGORIES_PER_CELL - set(cats)}"
    )
    # Exactly one rule per category — no duplicates from a careless
    # applies_when wildcard.
    assert sorted(cats) == sorted(EXPECTED_CATEGORIES_PER_CELL)


def test_pack_ships_inside_package() -> None:
    """The pack must be importable from the installed wheel.

    setuptools.package-data in pyproject already declares it, but
    this test pins that we can resolve it via the PACKS_DIR
    constant the loader uses. If someone moves the dir without
    updating pyproject, this test fails before any user does.
    """

    assert (PACKS_DIR / f"bangalore-{CURRENT_VERSION}.json").is_file()


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


def test_setback_values_are_present_for_every_cell() -> None:
    pack = load_pack("Bangalore")
    setback_rules = [r for r in pack.rules if r.category == "setback"]
    assert len(setback_rules) == 9
    for r in setback_rules:
        assert "min_setback_m" in r.params
        assert isinstance(r.params["min_setback_m"], int | float)
        assert r.params["min_setback_m"] >= 0


def test_coverage_open_space_parking_apply_by_zone_only() -> None:
    """Coverage/open_space/parking are wildcards on classification —
    same limit across Heritage/CBD/HDZ for a given zone. That's the
    current policy; pin it so a future "Heritage gets stricter
    coverage" change is intentional, not accidental."""

    pack = load_pack("Bangalore")
    for cat in ("coverage", "open_space", "parking"):
        rules = [r for r in pack.rules if r.category == cat]
        assert len(rules) == 3, f"expected 3 {cat} rules, got {len(rules)}"
        for r in rules:
            assert r.applies_when.classification is None
            assert r.applies_when.zone in {"Residential", "Commercial", "Industry"}


# ---- overlay rules -----------------------------------------------------------


def test_overlay_height_rules_skipped_without_overlay() -> None:
    """A plot with no overlays must not pick up the overlay height rules,
    regardless of classification/zone."""

    pack = load_pack("Bangalore")
    matched = applicable_rules(
        pack, classification="CBD", zone="Commercial", overlays=[]
    )
    assert "height" not in {r.category for r in matched}


def test_airport_overlay_adds_height_rule() -> None:
    pack = load_pack("Bangalore")
    matched = applicable_rules(
        pack,
        classification="CBD",
        zone="Commercial",
        overlays=["airport"],
    )
    ids = [r.id for r in matched]
    assert "blr.overlay.airport.height" in ids
    assert "blr.overlay.heritage_influence.height" not in ids


def test_heritage_influence_overlay_adds_height_rule() -> None:
    pack = load_pack("Bangalore")
    matched = applicable_rules(
        pack,
        classification="HDZ",
        zone="Residential",
        overlays=["heritage_influence"],
    )
    ids = [r.id for r in matched]
    assert "blr.overlay.heritage_influence.height" in ids
    assert "blr.overlay.airport.height" not in ids


def test_both_overlays_stack() -> None:
    """When a plot sits inside the airport zone AND the heritage skyline,
    BOTH height limits fire. The user sees the worst-case violation."""

    pack = load_pack("Bangalore")
    matched = applicable_rules(
        pack,
        classification="CBD",
        zone="Commercial",
        overlays=["airport", "heritage_influence"],
    )
    height_ids = sorted(r.id for r in matched if r.category == "height")
    assert height_ids == [
        "blr.overlay.airport.height",
        "blr.overlay.heritage_influence.height",
    ]


def test_overlay_rules_preserve_base_rule_count() -> None:
    """Overlay rules must ADD to base; an overlay being present must
    not cause base rules (FSI/setback/coverage/etc.) to drop out."""

    pack = load_pack("Bangalore")
    base = applicable_rules(
        pack, classification="CBD", zone="Commercial", overlays=[]
    )
    with_overlay = applicable_rules(
        pack, classification="CBD", zone="Commercial", overlays=["airport"]
    )
    assert len(with_overlay) == len(base) + 1
    base_ids = {r.id for r in base}
    assert base_ids.issubset({r.id for r in with_overlay})
