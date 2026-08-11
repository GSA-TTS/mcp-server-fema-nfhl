"""
count_flood_features tool
--------------------------
Registers a lightweight count-only guardrail tool on the MCP server.

Use this before screen_flood_zone when you want to gauge result size
without fetching full attributes (e.g. at highly-mapped urban intersections
or large project footprints).
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

from ..models import LAYER_FLOOD_HAZARD_ZONES, WGS84, Provenance
from ..utils import NFHLError, _geojson_to_esri, _now_utc, count_at_geometry


def register(mcp: FastMCP) -> None:
    """Register the count_flood_features tool with the MCP server."""

    @mcp.tool(
        name="nfhl_count_flood_features",
        annotations={
            "title": "Count NFHL Flood Features at Geometry",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def count_flood_features(
        lat: Annotated[Optional[float], Field(
            description=(
                "Latitude in decimal degrees (WGS84). Use with 'lon' for a quick point check. "
                "Omit when supplying 'geometry'."
            ),
        )] = None,
        lon: Annotated[Optional[float], Field(
            description=(
                "Longitude in decimal degrees (WGS84). Use with 'lat' for a quick point check. "
                "Omit when supplying 'geometry'."
            ),
        )] = None,
        geometry: Annotated[Optional[str], Field(
            description=(
                "GeoJSON geometry object as a JSON string. Supported types: "
                "Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon. "
                "Also accepts BoundingBox shorthand: "
                '{"type": "BoundingBox", "bbox": [minLon, minLat, maxLon, maxLat]}. '
                "All coordinates must be WGS84 decimal degrees. "
                "Supply either this OR lat+lon, not both."
            ),
        )] = None,
    ) -> dict[str, Any]:
        """Return ONLY how many flood features intersect a point or geometry (a size check).

        Use before nfhl_screen_flood_zone to gauge result size without fetching full
        attributes — useful for large polygons or densely mapped urban areas.
        A count of 0 means the geometry is outside NFHL coverage or in an unmapped area.

        Accepts EITHER a lat/lon pair (convenience) OR a GeoJSON geometry string.
        Supported GeoJSON types: Point, MultiPoint, LineString, MultiLineString,
        Polygon, MultiPolygon, or BoundingBox shorthand.

        Returns:
        {
            "count": int,
            "query_geometry": {"type": str, "crs_epsg": int},
            "provenance": { source metadata }
        }

        Error responses:
        - "Error: supply either lat+lon or geometry, not both (or neither)"
        - "Error: unsupported geometry type ..." — unknown GeoJSON type
        - "Error: NFHL request failed: ..." — network or service error
        """
        try:
            if lat is not None and lon is not None and geometry is None:
                geojson = {"type": "Point", "coordinates": [lon, lat]}
            elif geometry is not None and lat is None and lon is None:
                try:
                    geojson = json.loads(geometry)
                except json.JSONDecodeError as exc:
                    return {"error": f"Error: 'geometry' is not valid JSON: {exc}"}
            else:
                return {"error": "Error: supply either lat+lon or geometry, not both (or neither)."}

            geo_type = geojson.get("type", "Unknown")
            geometry_json, esri_type = _geojson_to_esri(geojson)
            count = count_at_geometry(
                geometry_json=geometry_json,
                geometry_type=esri_type,
                layer_id=LAYER_FLOOD_HAZARD_ZONES,
            )
            return {
                "count": count,
                "query_geometry": {"type": geo_type, "crs_epsg": WGS84},
                "provenance": Provenance(
                    layer_id=LAYER_FLOOD_HAZARD_ZONES,
                    retrieved_utc=_now_utc(),
                ).to_dict(),
            }

        except NFHLError as exc:
            return {"error": f"Error: NFHL request failed: {exc}"}
