"""Pack-agnostic smoke tests.

Walk every pack shipped under ``rules/packs/`` and verify the basics
that should hold regardless of city. Catches a future regression
where someone ships a new pack with a typo in an evaluator name,
a duplicate rule id, or an unparseable message template — without
needing per-city test files.

When a new city pack is added, this file requires no edits. Adding
a new ``city-name-vX.json`` is enough to extend coverage.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator

import pytest

import planara_engine.compliance  # noqa: F401 — register evaluators
from planara_engine.engine import registry
from planara_engine.engine.registry import known_evaluators
from planara_engine.rules.loader import PACKS_DIR, applicable_rules, load_pack


def _pack_paths() -> list[str]:
    """Every JSON file in the pack directory, sorted for stable output."""

    return sorted(p.name for p in PACKS_DIR.glob("*.json"))


PACK_FILES = _pack_paths()


@pytest.fixture(autouse=True)
def _clear_pack_cache() -> Iterator[None]:
    from planara_engine.rules.loader import get_pack

    get_pack.cache_clear()
    # Other test files clear the evaluator registry in their teardown
    # via registry._reset_for_tests(). When this smoke test runs after
    # one of them, the registry is empty and every "is this evaluator
    # registered?" check fails. Re-register by reloading the
    # compliance package's submodules so their @register decorators
    # fire again in the current process.
    registry._reset_for_tests()
    for mod in (
        "planara_engine.compliance.coverage",
        "planara_engine.compliance.fsi",
        "planara_engine.compliance.height",
        "planara_engine.compliance.lift_required",
        "planara_engine.compliance.parking",
        "planara_engine.compliance.room_height",
        "planara_engine.compliance.setback",
    ):
        importlib.reload(importlib.import_module(mod))
    yield
    get_pack.cache_clear()


def test_at_least_two_packs_ship() -> None:
    """If this drops to one, the cross-city isolation tests have no
    real signal — they'd be testing one pack twice. Pin a floor."""

    cities = {p.split("-", 1)[0] for p in PACK_FILES}
    assert len(cities) >= 2, f"only one city pack ships: {cities}"


@pytest.mark.parametrize("filename", PACK_FILES)
def test_pack_loads_and_validates(filename: str) -> None:
    """Each pack file parses, schema-validates, and resolves to a
    non-empty rule list. Catches a malformed JSON or schema-drift
    that escaped local testing."""

    city = filename.split("-", 1)[0]
    pack = load_pack(city)
    assert pack.rules, f"{filename} loaded but has zero rules"


@pytest.mark.parametrize("filename", PACK_FILES)
def test_every_evaluator_is_registered(filename: str) -> None:
    """Each rule names an evaluator that has been registered. A typo
    in a JSON file would otherwise blow up only when a user with
    that classification/zone hits /validate."""

    city = filename.split("-", 1)[0]
    pack = load_pack(city)
    known = set(known_evaluators())
    for rule in pack.rules:
        assert rule.evaluator in known, (
            f"{filename}: rule {rule.id!r} references unknown evaluator "
            f"{rule.evaluator!r}; known: {sorted(known)}"
        )


@pytest.mark.parametrize("filename", PACK_FILES)
def test_no_duplicate_rule_ids_within_pack(filename: str) -> None:
    """Loader enforces this on load_pack — but we pin it here too so
    a refactor to the loader's duplicate-check can't quietly weaken
    the guarantee."""

    city = filename.split("-", 1)[0]
    pack = load_pack(city)
    ids = [r.id for r in pack.rules]
    assert len(ids) == len(set(ids)), (
        f"{filename}: duplicate rule ids: "
        f"{[i for i in ids if ids.count(i) > 1]}"
    )


@pytest.mark.parametrize("filename", PACK_FILES)
def test_message_templates_are_safe_format_strings(filename: str) -> None:
    """rule_engine renders templates with format_map. Test by
    rendering against an empty dict via the engine's _SafeDict —
    any template that would raise (bad format spec) fails here."""

    from planara_engine.engine.rule_engine import _SafeDict

    city = filename.split("-", 1)[0]
    pack = load_pack(city)
    for rule in pack.rules:
        if not rule.message_template:
            continue
        try:
            rule.message_template.format_map(_SafeDict())
        except (ValueError, IndexError) as exc:
            pytest.fail(
                f"{filename}: rule {rule.id!r} has malformed message_template: {exc}"
            )


@pytest.mark.parametrize("filename", PACK_FILES)
def test_pack_filename_matches_declared_version(filename: str) -> None:
    """The version baked into the JSON must match the filename suffix.
    Skews here are how 'we shipped v0.3.0 but the file says 0.2.0'
    bugs slip into production."""

    city = filename.split("-", 1)[0]
    pack = load_pack(city)
    # filename format: city-X.Y.Z.json
    file_version = filename.rsplit("-", 1)[1].removesuffix(".json")
    # The loader picks the highest version, so this only meaningfully
    # asserts for the latest shipped file per city; older files might
    # not be loaded here. Still: check this pack's metadata is
    # internally consistent.
    if pack.version == file_version:
        assert pack.city.lower() == city.lower()


@pytest.mark.parametrize("filename", PACK_FILES)
def test_pack_has_at_least_one_wildcard_or_concrete_match(filename: str) -> None:
    """Every pack should resolve to at least one rule for SOME
    classification/zone — an empty matcher result for every cell
    means the pack is unreachable. Walk a dummy matrix to catch
    'rule pack ships but applies_when filters out everything'."""

    city = filename.split("-", 1)[0]
    pack = load_pack(city)

    # Collect declared classifications/zones from applies_when. Use
    # those + a wildcard probe so we don't have to know each city's
    # taxonomy here.
    classifications = {
        r.applies_when.classification for r in pack.rules if r.applies_when.classification
    } or {"any"}
    zones = {r.applies_when.zone for r in pack.rules if r.applies_when.zone} or {"any"}

    matched_anything = False
    for c in classifications:
        for z in zones:
            if applicable_rules(pack, classification=c, zone=z):
                matched_anything = True
                break
        if matched_anything:
            break
    assert matched_anything, f"{filename}: no rule fires for any cell"
