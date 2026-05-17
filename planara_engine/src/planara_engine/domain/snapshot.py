"""Snapshot: the full payload Ruby sends to /validate."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from planara_engine.domain.building import Building
from planara_engine.domain.plot import Plot
from planara_engine.domain.project_context import ProjectContext

# The current wire-format version. Bumped when a non-additive change
# lands (e.g. renaming a required field, changing units). Additive
# changes (new optional field) do NOT bump it — old clients keep
# working. The engine accepts older versions and logs a warning;
# rejecting on version mismatch would brick plugins that lag behind.
CURRENT_SCHEMA_VERSION = "1.0"


class Snapshot(BaseModel):
    """One compliance check input.

    schema_version: declared wire-format the client speaks. Optional
                   on the wire (defaults to CURRENT_SCHEMA_VERSION);
                   when present and below the current version, the
                   server logs a warning but still validates so users
                   of older plugins aren't locked out mid-session.
    snapshot_id:   client-generated UUID for correlation. The
                   server echoes it back so the plugin can match
                   responses to the in-flight transactions that
                   produced them (SketchUp can fire several
                   commits in quick succession during user
                   editing).
    project:       classification/zone/city/overlays/road widths.
    plot:          site polygon.
    building:      floors + heights.
    """

    schema_version: str = Field(default=CURRENT_SCHEMA_VERSION, min_length=1, max_length=16)
    snapshot_id: UUID = Field(default_factory=uuid4)
    project: ProjectContext
    plot: Plot
    building: Building
