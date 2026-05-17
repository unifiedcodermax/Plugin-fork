"""Archival report: a self-contained JSON document.

The JSON wire shape returned by /validate is the *minimum* a plugin
needs to render results. An archival report is broader: it's what
you'd save to disk in 2026 and still understand in 2030. It echoes
both the input (Snapshot) AND the output (ValidationResponse),
stamps engine + rule-pack versions, and carries its OWN schema
version so the archive format can evolve without touching the
runtime contract.

Pre-stages Sprint 9 (persistence): ArchivalReport is the natural
unit to write to a project history table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from planara_engine import __version__ as ENGINE_VERSION
from planara_engine.domain import Snapshot, ValidationResponse

# Independent from Snapshot.schema_version. Bumped when the
# ArchivalReport's *outer* shape changes (e.g. adding a new
# top-level field, or rearranging the layout). A change to the
# embedded snapshot's schema does not bump this — that's what
# the inner snapshot.schema_version is for.
ARCHIVAL_SCHEMA_VERSION = "1.0"


class ArchivalReport(BaseModel):
    """Self-contained record of a single validation run.

    report_id:              unique per render — even two calls with
                            the same inputs get distinct ids.
    report_schema_version:  the archival doc's own wire format.
    generated_at:           UTC timestamp the report was rendered.
    engine_version:         planara_engine package version.
    snapshot:               full echo of the validated input.
    response:               full echo of the engine's verdict.
    """

    report_id: UUID = Field(default_factory=uuid4)
    report_schema_version: str = Field(default=ARCHIVAL_SCHEMA_VERSION)
    generated_at: datetime
    engine_version: str = Field(default=ENGINE_VERSION)
    snapshot: Snapshot
    response: ValidationResponse


def render_archive(
    snapshot: Snapshot,
    response: ValidationResponse,
    *,
    generated_at: datetime | None = None,
) -> ArchivalReport:
    """Build an ArchivalReport from a snapshot+response pair.

    ``generated_at`` is injectable for deterministic tests; defaults
    to the current UTC time. Each call produces a new ``report_id``
    even when inputs are identical — there's no caching layer here.
    """

    return ArchivalReport(
        generated_at=generated_at or datetime.now(UTC),
        snapshot=snapshot,
        response=response,
    )
