"""Rule + RulePack schemas.

A rule is JSON; an evaluator is Python. The rule declares WHO it
applies to (city/classification/zone), WHICH evaluator to dispatch
to, WHAT parameters that evaluator needs, and HOW to render the
violation. The evaluator owns the math.

This split keeps city-specific data (FSI limits, setback values)
out of code. New municipalities ship as new rule packs without
touching the engine.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from planara_engine.domain.violation import Severity


class Applicability(BaseModel):
    """When a rule fires.

    Any field set to None means "matches anything for this
    dimension". A rule with classification=None applies to every
    classification in the rule's city.

    ``overlay`` is the Sprint-5 addition. When set, the rule fires
    only when ``ProjectContext.overlays`` contains that overlay key.
    Overlay rules fire IN ADDITION to base rules (the matcher does
    not exclude either side); to override a base limit, ship an
    overlay rule with a stricter param value and a distinct
    rule_id.
    """

    classification: str | None = None
    zone: str | None = None
    overlay: str | None = None


class Rule(BaseModel):
    """One declarative rule.

    id:               unique within the rule pack, namespaced
                      like "blr.fsi.cbd.residential".
    category:         coarse bucket the engine groups by
                      ("fsi", "setback", "coverage", ...).
    applies_when:     project-dimension filter.
    evaluator:        registered evaluator key. Unknown values
                      surface as a load-time error so a typo
                      doesn't silently disable a rule.
    params:           free-form dict passed to the evaluator.
                      Schema is the evaluator's responsibility.
    severity:         error/warning/info; defaults to error.
    message_template: f-string-like, rendered with the
                      evaluator's computed dict + the rule's
                      params + applicability.
    """

    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9._-]+$")
    category: str = Field(min_length=1, max_length=32)
    applies_when: Applicability = Field(default_factory=Applicability)
    evaluator: str = Field(min_length=1, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    severity: Severity = Severity.error
    message_template: str = Field(default="", max_length=512)


class RulePack(BaseModel):
    """A versioned bundle of rules for one city.

    city:    must match ProjectContext.city for rules to apply.
    version: SemVer-ish string. Stored on the response metrics
             so a user can verify which pack was used.
    rules:   the rules. Duplicate ids are rejected at load time.
    """

    city: str = Field(min_length=1, max_length=64)
    version: str = Field(min_length=1, max_length=32)
    rules: list[Rule] = Field(default_factory=list)
