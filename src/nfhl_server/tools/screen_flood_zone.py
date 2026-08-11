"""
screen_flood_zone tool
-----------------------
Registers the nfhl_screen_flood_zone tool on the MCP server.

Accepts either:
  - A lat/lon point (convenience shorthand), or
  - An arbitrary GeoJSON geometry: Point, MultiPoint, LineString,
    MultiLineString, Polygon, MultiPolygon, or BoundingBox shorthand.

Design notes:
    - All coordinates are WGS84 (EPSG:4326) decimal degrees.
    - Results include provenance; no geometry is returned in the response.
    - BFE / DEPTH of -9999 means "not applicable or not mapped".
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Optional

from fastmcp import FastMCP
from pydantic import Field

from ..models import LAYER_FLOOD_HAZARD_ZONES, WGS84
from ..utils import NFHLError, _geojson_to_esri, _interpret, _now_utc, query_geometry


def register(mcp: FastMCP) -> None:
    """Register the screen_flood_zone tool with the MCP server."""

    @mcp.tool(
        name="nfhl_screen_flood_zone",
        annotations={
            "title": "Screen Geometry for FEMA Flood Zone",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def screen_flood_zone(
        lat: Annotated[Optional[float], Field(
            description=(
                "Latitude in decimal degrees (WGS84). Use with 'lon' for a quick point query. "
                "Omit when supplying 'geometry'."
            ),
        )] = None,
        lon: Annotated[Optional[float], Field(
            description=(
                "Longitude in decimal degrees (WGS84). Use with 'lat' for a quick point query. "
                "Omit when supplying 'geometry'."
            ),
        )] = None,
        geometry: Annotated[Optional[str], Field(
            description=(
                "GeoJSON geometry object as a JSON string. Supported types: "
                "Point, MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon. "
                "Also accepts a BoundingBox shorthand: "
                '{"type": "BoundingBox", "bbox": [minLon, minLat, maxLon, maxLat]}. '
                "All coordinates must be WGS84 decimal degrees. "
                "Supply either this OR lat+lon, not both."
            ),
        )] = None,
    ) -> dict[str, Any]:
        """Screen a point or arbitrary geometry for FEMA NFHL flood-zone constraints.

        Accepts EITHER a lat/lon pair (convenience) OR a GeoJSON geometry string.
        Supported GeoJSON types: Point, MultiPoint, LineString, MultiLineString,
        Polygon, MultiPolygon. Also accepts BoundingBox shorthand:
            {"type": "BoundingBox", "bbox": [minLon, minLat, maxLon, maxLat]}

        Use lat+lon when: "Is this address in a flood zone?", "Flood zone at 29.95, -90.07?"
        Use geometry when: "Does this parcel intersect an SFHA?", "What flood zones cross
            this pipeline corridor?", "Screen this project boundary for flood hazards."

        Returns:
        {
            "finding": str,        # plain-language summary (SFHA status, zone, subtype)
            "count": int,          # number of intersecting flood features
            "truncated": bool,     # true if capped at max_records
            "features": [...],     # flood-zone attributes (FLD_ZONE, SFHA_TF, BFE, etc.)
            "provenance": { source agency, service URL, layer, CRS, citation, retrieved_utc },
            "query_geometry": {"type": str, "crs_epsg": int}
        }

        BFE/DEPTH of -9999 means "not applicable or not mapped" for that zone.

        Error responses:
        - "Error: supply either lat+lon or geometry, not both (or neither)"
        - "Error: unsupported geometry type ..." — unknown GeoJSON type
        - "Error: NFHL request failed: ..." — network or service error
        """
        try:
            if lat is not None and lon is not None and geometry is None:
                # Convenience: wrap the point into a GeoJSON Point
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
            result = query_geometry(
                geometry_json=geometry_json,
                geometry_type=esri_type,
                layer_id=LAYER_FLOOD_HAZARD_ZONES,
            )
            result.provenance.retrieved_utc = _now_utc()
            out = result.to_dict()
            out["finding"] = _interpret(result.features, geometry_type=geo_type)
            out["query_geometry"] = {"type": geo_type, "crs_epsg": WGS84}
            return out

        except NFHLError as exc:
            return {"error": f"Error: NFHL request failed: {exc}"}
