"""Snapshot: the full payload Ruby sends to /validate."""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from planara_engine.domain.building import Building
from planara_engine.domain.plot import Plot
from planara_engine.domain.project import Project


class Snapshot(BaseModel):
    """One compliance check input.

    snapshot_id:   client-generated UUID for correlation. The
                   server echoes it back so the plugin can match
                   responses to the in-flight transactions that
                   produced them (SketchUp can fire several
                   commits in quick succession during user
                   editing).
    project:       classification/zone/city/road widths.
    plot:          site polygon.
    building:      floors + heights.
    """

    snapshot_id: UUID = Field(default_factory=uuid4)
    project: Project
    plot: Plot
    building: Building
