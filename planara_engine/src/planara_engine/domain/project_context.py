"""ProjectContext metadata: classification, zone, city.

These are the dimensions rule applicability is keyed on. Strings
are intentionally not constrained to enums here — the rule pack
defines the universe of valid values for a given city, and a
typo in the plugin should surface as "no rules matched" rather
than "validation rejected your enum value", so the user can fix
it.

Note: this is the *context* of a design (the rule-applicability
dimensions), distinct from the persisted `Project` entity in
``persistence/models.py`` (the user-named row that groups runs
together for regression-tracking).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ProjectContext(BaseModel):
    """Compliance context for a single design.

    classification: typically CBD / Heritage / HDZ for Bangalore.
                    Other cities will use other tags.

                    Bangalore mapping to Building Byelaws 2003:
                      Heritage → Area A (Intensely Developed)
                      CBD      → Area B (Moderately Developed)
                      HDZ      → Area C (Sparsely Developed)
                    The byelaws define FAR, coverage, and setbacks
                    based on these area classifications combined with
                    plot area and abutting road width (Tables 4–6).

    zone:           Residential / Commercial / Industrial / etc.
    city:           Rule-pack key. Determines which pack to load.
    overlays:       Additional restriction layers in effect on
                    this plot. Examples: "airport" (approach
                    surface height limits), "heritage_influence"
                    (protected character zone — distinct from
                    a Heritage *classification*), "fire_zone",
                    "ASI_protected".
                    Overlay rules fire IN ADDITION to base rules.
                    Empty list (the default) means no overlays.
    road_widths_m:  Optional per-edge road width, in meters.
                    The legacy rules.json prices FAR premiums by
                    "front road width"; future evaluators will
                    consume this. Optional in v0.1.
    """

    city: str = Field(min_length=1, max_length=64)
    classification: str = Field(min_length=1, max_length=64)
    zone: str = Field(min_length=1, max_length=64)
    overlays: list[str] = Field(default_factory=list)
    road_widths_m: dict[str, float] = Field(default_factory=dict)
