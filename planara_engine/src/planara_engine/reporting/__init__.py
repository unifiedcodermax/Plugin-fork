"""Reporting layer: human-readable artifacts from a validation run.

Two renderers ship today:
  - render_html: standalone HTML document for users and submissions.
  - render_archive: self-contained ArchivalReport for storage and
    later interpretation.

Both take the same Snapshot + ValidationResponse pair; the rendering
is pure (no DB, no I/O).
"""

from planara_engine.reporting.archive import (
    ARCHIVAL_SCHEMA_VERSION,
    ArchivalReport,
    render_archive,
)
from planara_engine.reporting.html_renderer import render_html

__all__ = [
    "ARCHIVAL_SCHEMA_VERSION",
    "ArchivalReport",
    "render_archive",
    "render_html",
]
