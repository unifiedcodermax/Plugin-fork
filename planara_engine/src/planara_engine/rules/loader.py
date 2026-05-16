"""Load rule packs from JSON files.

Rule packs live under ``planara_engine/rules/packs/<city>-<version>.json``
and are loaded by city name. The loader caches packs per process —
no disk I/O on the hot path.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from planara_engine.core.errors import NotFound, ValidationFailed
from planara_engine.core.logging import get_logger
from planara_engine.rules.schema import Rule, RulePack

log = get_logger("planara.rules")

PACKS_DIR = Path(__file__).resolve().parent / "packs"


def load_pack(city: str, *, packs_dir: Path | None = None) -> RulePack:
    """Load and validate the rule pack for ``city``.

    Packs are discovered by glob: ``<city-lower>-*.json``. If
    multiple match, the highest-versioned (lexicographic) wins —
    which works because we use semver-ish strings.
    """

    base = packs_dir or PACKS_DIR
    candidates = sorted(base.glob(f"{city.lower()}-*.json"))
    if not candidates:
        raise NotFound(f"no rule pack found for city: {city}", details={"city": city})

    chosen = candidates[-1]
    log.info("rule_pack_loading", path=str(chosen), city=city)

    try:
        raw = json.loads(chosen.read_text(encoding="utf-8"))
        pack = RulePack.model_validate(raw)
    except json.JSONDecodeError as exc:
        raise ValidationFailed(
            f"rule pack {chosen.name} is not valid JSON: {exc}",
            details={"path": str(chosen)},
        ) from exc
    except ValidationError as exc:
        raise ValidationFailed(
            f"rule pack {chosen.name} failed schema validation",
            details={"path": str(chosen), "errors": exc.errors(include_url=False)},
        ) from exc

    _check_unique_rule_ids(pack)
    log.info(
        "rule_pack_loaded", city=pack.city, version=pack.version, rule_count=len(pack.rules)
    )
    return pack


@lru_cache(maxsize=16)
def get_pack(city: str) -> RulePack:
    """Cached pack lookup. Clear with ``get_pack.cache_clear()`` in tests."""

    return load_pack(city)


def _check_unique_rule_ids(pack: RulePack) -> None:
    seen: set[str] = set()
    dupes: list[str] = []
    for rule in pack.rules:
        if rule.id in seen:
            dupes.append(rule.id)
        seen.add(rule.id)
    if dupes:
        raise ValidationFailed(
            "rule pack contains duplicate rule ids",
            details={"city": pack.city, "duplicates": dupes},
        )


def applicable_rules(
    pack: RulePack,
    *,
    classification: str,
    zone: str,
    overlays: list[str] | None = None,
) -> list[Rule]:
    """Filter the pack's rules to those matching the project context.

    A rule's ``applies_when`` fields use ``None`` as wildcard.

    Overlay semantics:
      - Rule has applies_when.overlay = None  -> base rule, always
        eligible (overlays don't exclude it).
      - Rule has applies_when.overlay = "X"   -> overlay rule, fires
        only when "X" is in ``overlays``.
      - Overlay rules ADD to base rules; they don't replace. To
        override a base value with a stricter limit, ship an
        overlay rule with a distinct rule_id and the stricter
        param value — both rules fire; the worst-case violation
        is what the user sees.

    Returns rules in their original order so the engine's
    violation list is stable.
    """

    active_overlays = set(overlays or [])

    out: list[Rule] = []
    for rule in pack.rules:
        when = rule.applies_when
        if when.classification is not None and when.classification != classification:
            continue
        if when.zone is not None and when.zone != zone:
            continue
        if when.overlay is not None and when.overlay not in active_overlays:
            continue
        out.append(rule)
    return out
