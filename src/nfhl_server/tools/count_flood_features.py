"""
count_flood_features tool
--------------------------
Registers a lightweight count-only guardrail tool on the MCP server.

Use this before screen_flood_zone when you want to gauge result size
without fetching full attributes (e.g. at highly-mapped urban intersections).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..models import LAYER_FLOOD_HAZARD_ZONES, WGS84, Provenance
from ..utils import NFHLError, _now_utc, count_at_point


def register(mcp: FastMCP) -> None:
    """Register the count_flood_features tool with the MCP server."""

    @mcp.tool(
        name="nfhl_count_flood_features",
        annotations={
            "title": "Count NFHL Flood Features at Point",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def count_flood_features(
        lat: Annotated[float, Field(description="Latitude in decimal degrees (WGS84 / EPSG:4326). Example: 29.9511")],
        lon: Annotated[float, Field(description="Longitude in decimal degrees (WGS84 / EPSG:4326). Example: -90.0715")],
    ) -> dict[str, Any]:
        """Return ONLY how many flood features intersect a point (a size check).

        Use this before nfhl_screen_flood_zone when you suspect a location may
        hit many overlapping features, to gauge result size before fetching
        attributes. A count of 0 means the point is outside NFHL coverage or
        falls in an unmapped area.

        Returns:
        {
            "count": int,
            "query_point": {"lat": float, "lon": float, "crs_epsg": int},
            "provenance": { source metadata }
        }

        Error responses:
        - "Error: NFHL request failed: ..." — network or service error
        """
        try:
            count = count_at_point(lon=lon, lat=lat, layer_id=LAYER_FLOOD_HAZARD_ZONES)
            return {
                "count": count,
                "query_point": {"lat": lat, "lon": lon, "crs_epsg": WGS84},
                "provenance": Provenance(
                    layer_id=LAYER_FLOOD_HAZARD_ZONES,
                    retrieved_utc=_now_utc(),
                ).to_dict(),
            }
        except NFHLError as exc:
            return {"error": f"Error: NFHL request failed: {exc}"}
