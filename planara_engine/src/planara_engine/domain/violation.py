"""Violation + ValidationResponse: the wire shape of compliance results."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class Severity(StrEnum):
    """How much a violation matters.

    error:    blocks approval — design as drawn is non-compliant.
    warning:  permitted but flagged (e.g. close to a limit).
    info:     advisory note, not a violation in the strict sense.
    """

    error = "error"
    warning = "warning"
    info = "info"


class Violation(BaseModel):
    """One rule's verdict.

    rule_id:           opaque, namespaced like
                       "blr.fsi.cbd.residential".
    category:          coarse bucket the UI groups by
                       (fsi/setback/coverage/...).
    severity:          see Severity.
    message:           rendered, human-readable.
    computed:          machine-readable values that produced the
                       verdict; the plugin can display them in
                       the UI without recomputing.
    """

    rule_id: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=32)
    severity: Severity
    message: str
    computed: dict[str, Any] = Field(default_factory=dict)


class ValidationResponse(BaseModel):
    """What /validate returns.

    snapshot_id:   echoed from the request.
    ok:            convenience boolean — true iff no errors.
                   Warnings and infos do not flip this. Plugins
                   that want to gate on warnings can inspect
                   ``violations`` directly.
    violations:    every rule that fired, regardless of severity.
                   Order is insertion order from the engine.
    metrics:       flat dict of computed quantities (fsi,
                   coverage_pct, etc.) for the plugin to render
                   in its results panel.
    """

    snapshot_id: UUID
    ok: bool
    violations: list[Violation] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
