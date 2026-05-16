"""Smoke test the shipped Mumbai rule pack.

Mirrors test_bangalore_pack.py: walks the classification × zone
matrix to confirm each cell resolves to the expected set of rules.
Mumbai's primary purpose in the test suite is to catch
"accidentally hardcoded Bangalore" regressions in the engine — if
any change to shared code breaks Mumbai but not Bangalore (or
vice versa), the city-isolation contract has slipped.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from planara_engine.rules import applicable_rules
from planara_engine.rules.loader import PACKS_DIR, get_pack, load_pack


CURRENT_VERSION = "0.2.0"

# Mumbai uses Island (south Mumbai) and Suburbs as classification —
# DCPR 2034 has a meaningful FSI split between the two. Distinct
# from Bangalore's CBD/Heritage/HDZ, which is the whole point of
# adding this pack.
CLASSIFICATIONS = ["Island", "Suburbs"]
ZONES = ["Residential", "Commercial", "Industry"]

EXPECTED_CATEGORIES_PER_CELL = {"fsi", "setback", "coverage", "open_space", "parking"}


@pytest.fixture(autouse=True)
def fresh_pack_cache() -> Iterator[None]:
    get_pack.cache_clear()
    yield
    get_pack.cache_clear()


def test_pack_loads_clean() -> None:
    pack = load_pack("Mumbai")
    assert pack.city == "Mumbai"
    assert pack.version == CURRENT_VERSION
    # 21 base + 2 overlays (CRZ fsi, airport height) = 23.
    assert len(pack.rules) == 23


def test_pack_ships_inside_package() -> None:
    assert (PACKS_DIR / f"mumbai-{CURRENT_VERSION}.json").is_file()


@pytest.mark.parametrize("classification", CLASSIFICATIONS)
@pytest.mark.parametrize("zone", ZONES)
def test_each_cell_has_every_category(classification: str, zone: str) -> None:
    """Every (classification, zone) cell fires exactly one rule per
    base category. Same shape as the Bangalore guarantee — proves
    the matrix completeness doesn't depend on which city we look at."""

    pack = load_pack("Mumbai")
    matched = applicable_rules(pack, classification=classification, zone=zone)
    cats = [r.category for r in matched]
    assert set(cats) == EXPECTED_CATEGORIES_PER_CELL, (
        f"({classification}, {zone}) missing categories: "
        f"{EXPECTED_CATEGORIES_PER_CELL - set(cats)}"
    )
    assert sorted(cats) == sorted(EXPECTED_CATEGORIES_PER_CELL)


def test_rule_ids_use_mum_prefix() -> None:
    """Pins that Mumbai rules use the mum.* prefix — the engine
    doesn't care, but mixed prefixes in one pack would be a
    copy-paste error from Bangalore."""

    pack = load_pack("Mumbai")
    for r in pack.rules:
        assert r.id.startswith("mum."), f"non-Mumbai rule id slipped in: {r.id}"


def test_fsi_island_vs_suburbs_diverges() -> None:
    """Island and Suburbs FSI limits should NOT be the same for
    every zone — that's the architectural justification for two
    classifications. If a future edit accidentally aligns them,
    Mumbai loses its city-shape and stops stressing isolation."""

    pack = load_pack("Mumbai")
    by_id = {r.id: r for r in pack.rules}
    island_res = by_id["mum.fsi.island.residential"].params["max_fsi"]
    suburbs_res = by_id["mum.fsi.suburbs.residential"].params["max_fsi"]
    assert island_res != suburbs_res


def test_classifications_disjoint_from_bangalore() -> None:
    """Mumbai's classification names must not collide with Bangalore's.
    A "CBD" rule in Mumbai (or "Island" in Bangalore) would be a sign
    the rule files got crossed."""

    pack = load_pack("Mumbai")
    classifications = {
        r.applies_when.classification for r in pack.rules if r.applies_when.classification is not None
    }
    assert classifications == {"Island", "Suburbs"}
    assert "CBD" not in classifications
    assert "Heritage" not in classifications
    assert "HDZ" not in classifications


def test_coverage_open_space_parking_apply_by_zone_only() -> None:
    """Same convention as Bangalore: coverage/open_space/parking are
    classification-wildcard. Pin it for Mumbai too so a future
    'Island gets stricter coverage' is intentional."""

    pack = load_pack("Mumbai")
    for cat in ("coverage", "open_space", "parking"):
        rules = [r for r in pack.rules if r.category == cat]
        assert len(rules) == 3, f"expected 3 {cat} rules, got {len(rules)}"
        for r in rules:
            assert r.applies_when.classification is None
            assert r.applies_when.zone in {"Residential", "Commercial", "Industry"}


def test_bangalore_still_loads_independently() -> None:
    """Cross-city isolation: adding Mumbai must not break Bangalore.
    Both packs must coexist in PACKS_DIR with no glob/load collision."""

    bangalore = load_pack("Bangalore")
    mumbai = load_pack("Mumbai")
    assert bangalore.city == "Bangalore"
    assert mumbai.city == "Mumbai"
    # No rule ID collides across packs.
    blr_ids = {r.id for r in bangalore.rules}
    mum_ids = {r.id for r in mumbai.rules}
    assert blr_ids.isdisjoint(mum_ids)


# ---- overlay rules -----------------------------------------------------------


def test_no_overlay_skips_overlay_rules() -> None:
    """A plot with no overlays must not pick up CRZ or airport rules."""

    pack = load_pack("Mumbai")
    matched = applicable_rules(
        pack, classification="Island", zone="Residential", overlays=[]
    )
    ids = {r.id for r in matched}
    assert "mum.overlay.crz.fsi" not in ids
    assert "mum.overlay.airport.height" not in ids


def test_crz_overlay_adds_strict_fsi_rule() -> None:
    """CRZ overlay adds a stricter FSI rule on top of the base.
    Both fire together; the user sees whichever they violate."""

    pack = load_pack("Mumbai")
    matched = applicable_rules(
        pack, classification="Island", zone="Residential", overlays=["crz"]
    )
    ids = [r.id for r in matched]
    fsi_ids = [i for i in ids if "fsi" in i]
    # Base FSI rule + CRZ overlay FSI rule, both with category="fsi".
    assert "mum.fsi.island.residential" in fsi_ids
    assert "mum.overlay.crz.fsi" in fsi_ids


def test_airport_overlay_shared_with_bangalore() -> None:
    """The 'airport' overlay key is reused across cities — proves
    overlay names are NOT a global enum but a per-pack label. Both
    packs fire their own airport rule when the overlay is active."""

    mumbai = load_pack("Mumbai")
    bangalore = load_pack("Bangalore")

    m_matched = applicable_rules(
        mumbai, classification="Island", zone="Commercial", overlays=["airport"]
    )
    b_matched = applicable_rules(
        bangalore, classification="CBD", zone="Commercial", overlays=["airport"]
    )
    assert "mum.overlay.airport.height" in {r.id for r in m_matched}
    assert "blr.overlay.airport.height" in {r.id for r in b_matched}


def test_crz_overlay_is_mumbai_only() -> None:
    """CRZ is Mumbai-specific. Bangalore doesn't define it — projects
    that send overlays=['crz'] through Bangalore must silently match
    nothing (per the unknown-overlay forward-compat contract)."""

    bangalore = load_pack("Bangalore")
    matched = applicable_rules(
        bangalore, classification="CBD", zone="Residential", overlays=["crz"]
    )
    # Only the base rules fire; no CRZ rule in Bangalore.
    for r in matched:
        assert "crz" not in r.id
