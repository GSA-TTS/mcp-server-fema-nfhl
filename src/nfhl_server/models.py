"""
models.py
---------
Pydantic-free data models for the FEMA NFHL client.

These dataclasses carry structured results and provenance information
between the client functions and the MCP tool layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants shared by both models and client code
# ---------------------------------------------------------------------------

BASE_URL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"

# WGS84 lon/lat. This is what GPS coordinates are in, and what we require
# callers to pass. We NEVER silently assume a CRS.
WGS84 = 4326

# Layer IDs we care about for permitting screening. Discovered live from the
# service metadata; see list_layers() to refresh this at runtime.
LAYER_FLOOD_HAZARD_ZONES = 28   # polygons: FLD_ZONE, SFHA_TF, STATIC_BFE, ...
LAYER_FLOODWAYS = 27            # polylines: flood hazard boundaries

# The service caps each response at this many records. Above this you MUST page.
DEFAULT_MAX_RECORDS = 2000

# Attributes worth returning for a flood-zone screen. Explicit > wildcard:
# keeps payloads small and makes the contract stable.
FLOOD_ZONE_FIELDS = [
    "FLD_ZONE",     # e.g. "AE", "X", "VE" -- the flood zone designation
    "ZONE_SUBTY",   # subtype, e.g. "FLOODWAY", "AREA WITH REDUCED FLOOD RISK..."
    "SFHA_TF",      # "T"/"F": is this a Special Flood Hazard Area?
    "STATIC_BFE",   # base flood elevation (may be -9999 when not applicable)
    "V_DATUM",      # vertical datum for the BFE (e.g. NAVD88) -- provenance!
    "DEPTH",        # flood depth where published
    "SOURCE_CIT",   # citation for the source study -- provenance!
    "DFIRM_ID",     # the DFIRM (map panel) this feature belongs to
]

DEFAULT_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Provenance:
    """Where a result came from -- non-negotiable for a permitting record."""
    source_agency: str = "FEMA"
    dataset: str = "National Flood Hazard Layer (NFHL)"
    service_url: str = BASE_URL
    layer_id: int | None = None
    crs_epsg: int = WGS84
    source_citation: str | None = None  # from SOURCE_CIT when available
    retrieved_utc: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_agency": self.source_agency,
            "dataset": self.dataset,
            "service_url": self.service_url,
            "layer_id": self.layer_id,
            "crs_epsg": self.crs_epsg,
            "source_citation": self.source_citation,
            "retrieved_utc": self.retrieved_utc,
        }


@dataclass
class QueryResult:
    """A compact, model-friendly answer with provenance attached."""
    features: list[dict[str, Any]] = field(default_factory=list)
    count: int = 0
    truncated: bool = False   # True if there were more records than we fetched
    provenance: Provenance = field(default_factory=Provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "truncated": self.truncated,
            "features": self.features,
            "provenance": self.provenance.to_dict(),
        }
