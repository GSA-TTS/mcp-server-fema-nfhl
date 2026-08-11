"""
screen_flood_zone tool
-----------------------
Registers the nfhl_screen_flood_zone tool on the MCP server.

Design notes for the agent:
    - Inputs are ALWAYS latitude/longitude in WGS84 (EPSG:4326) decimal degrees.
    - Returns a summary + provenance, never raw geometry, to protect the
      model's context window.
    - Base flood elevation / depth of -9999 means "not applicable / not mapped".
"""

from __future__ import annotations

from typing import Annotated, Any

from fastmcp import FastMCP
from pydantic import Field

from ..models import LAYER_FLOOD_HAZARD_ZONES, WGS84
from ..utils import NFHLError, _interpret, _now_utc, query_point


def register(mcp: FastMCP) -> None:
    """Register the screen_flood_zone tool with the MCP server."""

    @mcp.tool(
        name="nfhl_screen_flood_zone",
        annotations={
            "title": "Screen Point for FEMA Flood Zone",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def screen_flood_zone(
        lat: Annotated[float, Field(description="Latitude in decimal degrees (WGS84 / EPSG:4326). Example: 29.9511")],
        lon: Annotated[float, Field(description="Longitude in decimal degrees (WGS84 / EPSG:4326). Example: -90.0715")],
    ) -> dict[str, Any]:
        """Screen a single point for FEMA flood-zone constraints.

        Use when: "Is this address in a flood zone?", "What is the flood zone at lat/lon?"
        Don't use when: You only need a feature count — use nfhl_count_flood_features instead.

        Returns a compact result:
        {
            "finding": str,        # plain-language summary (SFHA status, zone, subtype)
            "count": int,          # number of overlapping flood features
            "truncated": bool,     # true if result was capped at max_records
            "features": [...],     # raw flood-zone attributes (FLD_ZONE, SFHA_TF, BFE, etc.)
            "provenance": { source agency, service URL, layer, CRS, citation, retrieved_utc },
            "query_point": {"lat": float, "lon": float, "crs_epsg": int}
        }

        BFE/DEPTH of -9999 means "not applicable or not mapped" for that zone.

        Error responses:
        - "Error: NFHL request failed: ..." — network or service error
        """
        try:
            result = query_point(lon=lon, lat=lat, layer_id=LAYER_FLOOD_HAZARD_ZONES)
            result.provenance.retrieved_utc = _now_utc()
            out = result.to_dict()
            out["finding"] = _interpret(result.features)
            out["query_point"] = {"lat": lat, "lon": lon, "crs_epsg": WGS84}
            return out
        except NFHLError as exc:
            return {"error": f"Error: NFHL request failed: {exc}"}
