"""
utils.py
--------
Shared utilities: timestamp helper, result interpreter, and the NFHL HTTP client.

The client functions use only the stdlib (urllib) to keep dependencies minimal
and remain unit-testable in isolation from MCP.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .models import (
    BASE_URL,
    DEFAULT_MAX_RECORDS,
    DEFAULT_TIMEOUT,
    FLOOD_ZONE_FIELDS,
    LAYER_FLOOD_HAZARD_ZONES,
    WGS84,
    Provenance,
    QueryResult,
)


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Result interpreter
# ---------------------------------------------------------------------------

def _interpret(features: list[dict[str, Any]], geometry_type: str = "Point") -> str:
    """Turn raw attributes into a one-line plain-language finding for the agent."""
    subject = "Area" if geometry_type in ("Polygon", "Envelope", "Polyline") else "Point"
    if not features:
        return f"No mapped flood hazard zone at this location (outside NFHL coverage or unmapped)."
    in_sfha = any(f.get("SFHA_TF") == "T" for f in features)
    zones = sorted({f.get("FLD_ZONE") for f in features if f.get("FLD_ZONE")})
    subtypes = sorted({f.get("ZONE_SUBTY") for f in features if f.get("ZONE_SUBTY")})
    lead = "intersects a Special Flood Hazard Area" if in_sfha else "does NOT intersect a Special Flood Hazard Area"
    detail = f" Zone(s): {', '.join(zones)}." if zones else ""
    sub = f" Subtype(s): {', '.join(subtypes)}." if subtypes else ""
    return f"{subject} {lead}.{detail}{sub}"


# ---------------------------------------------------------------------------
# NFHL HTTP client
# ---------------------------------------------------------------------------

class NFHLError(RuntimeError):
    """Raised when the NFHL service errors or returns something unusable."""


# ---------------------------------------------------------------------------
# GeoJSON → Esri geometry conversion
# ---------------------------------------------------------------------------

# Maps GeoJSON geometry type to the Esri geometryType parameter value.
_GEOJSON_TO_ESRI_TYPE: dict[str, str] = {
    "Point":           "esriGeometryPoint",
    "MultiPoint":      "esriGeometryMultipoint",
    "LineString":      "esriGeometryPolyline",
    "MultiLineString": "esriGeometryPolyline",
    "Polygon":         "esriGeometryPolygon",
    "MultiPolygon":    "esriGeometryPolygon",
}

# Convenience alias accepted as a shorthand in the tool layer.
_BBOX_TYPE = "BoundingBox"


def _geojson_to_esri(geojson: dict[str, Any]) -> tuple[str, str]:
    """Convert a GeoJSON geometry object to (esri_json_str, esri_geometry_type).

    Supports: Point, MultiPoint, LineString, MultiLineString, Polygon,
    MultiPolygon. Also accepts a synthetic {"type": "BoundingBox",
    "bbox": [minLon, minLat, maxLon, maxLat]} shorthand that maps to
    esriGeometryEnvelope.

    All coordinates must be WGS84 (EPSG:4326).

    Raises NFHLError on unknown or malformed geometry.
    """
    geo_type = geojson.get("type")
    sr = {"wkid": WGS84}

    # ---- BoundingBox shorthand ----------------------------------------
    if geo_type == _BBOX_TYPE:
        bbox = geojson.get("bbox")
        if not bbox or len(bbox) != 4:
            raise NFHLError("BoundingBox geometry requires a 'bbox' array of [minLon, minLat, maxLon, maxLat].")
        min_lon, min_lat, max_lon, max_lat = bbox
        esri = {"xmin": min_lon, "ymin": min_lat, "xmax": max_lon, "ymax": max_lat, "spatialReference": sr}
        return json.dumps(esri), "esriGeometryEnvelope"

    if geo_type not in _GEOJSON_TO_ESRI_TYPE:
        raise NFHLError(
            f"Unsupported geometry type '{geo_type}'. "
            f"Supported types: {', '.join(sorted(_GEOJSON_TO_ESRI_TYPE))} or BoundingBox."
        )

    esri_type = _GEOJSON_TO_ESRI_TYPE[geo_type]
    coords = geojson.get("coordinates")
    if coords is None:
        raise NFHLError(f"GeoJSON geometry of type '{geo_type}' is missing 'coordinates'.")

    # ---- Point -------------------------------------------------------
    if geo_type == "Point":
        # GeoJSON: [lon, lat] — Esri: {x, y}
        esri = {"x": coords[0], "y": coords[1], "spatialReference": sr}

    # ---- MultiPoint --------------------------------------------------
    elif geo_type == "MultiPoint":
        # GeoJSON: [[lon, lat], ...] — Esri: {points: [[lon, lat], ...]}
        esri = {"points": [[c[0], c[1]] for c in coords], "spatialReference": sr}

    # ---- LineString --------------------------------------------------
    elif geo_type == "LineString":
        # GeoJSON: [[lon, lat], ...] — Esri: {paths: [[[lon, lat], ...]]}
        esri = {"paths": [[[c[0], c[1]] for c in coords]], "spatialReference": sr}

    # ---- MultiLineString ---------------------------------------------
    elif geo_type == "MultiLineString":
        # GeoJSON: [[[lon, lat], ...], ...] — Esri: {paths: [[[lon, lat], ...], ...]}
        esri = {"paths": [[[c[0], c[1]] for c in line] for line in coords], "spatialReference": sr}

    # ---- Polygon -----------------------------------------------------
    elif geo_type == "Polygon":
        # GeoJSON: [exterior_ring, *hole_rings] where rings are [[lon, lat], ...]
        # Esri:    {rings: [[[lon, lat], ...], ...]} — same structure, same winding OK
        esri = {"rings": [[[c[0], c[1]] for c in ring] for ring in coords], "spatialReference": sr}

    # ---- MultiPolygon ------------------------------------------------
    elif geo_type == "MultiPolygon":
        # GeoJSON: [[rings], [rings], ...] — flatten all rings into one Esri polygon
        rings = []
        for polygon in coords:
            for ring in polygon:
                rings.append([[c[0], c[1]] for c in ring])
        esri = {"rings": rings, "spatialReference": sr}

    else:
        raise NFHLError(f"Unhandled geometry type '{geo_type}'.")  # unreachable, but mypy-safe

    return json.dumps(esri), esri_type


# ---------------------------------------------------------------------------
# NFHL HTTP client
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# NFHL HTTP helpers
# ---------------------------------------------------------------------------

def _get_json(url: str, params: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """GET a URL with query params and parse JSON, with clear error handling.

    ArcGIS returns HTTP 200 even for logical errors, embedding an "error"
    object in the body -- so we check for that explicitly.
    """
    query = urllib.parse.urlencode(params, doseq=True)
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, headers={"User-Agent": "nfhl-mcp/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 -- surface a clean error upward
        raise NFHLError(f"Request to NFHL failed: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise NFHLError(f"NFHL returned non-JSON (first 200 chars): {raw[:200]!r}") from exc

    if isinstance(data, dict) and "error" in data:
        raise NFHLError(f"NFHL service error: {data['error']}")
    return data


def count_at_geometry(
    geometry_json: str,
    geometry_type: str,
    layer_id: int,
    timeout: int = DEFAULT_TIMEOUT,
) -> int:
    """Return ONLY the number of features intersecting an arbitrary geometry.

    This is the cost/completeness guardrail: check size before fetching.
    geometry_json and geometry_type should come from _geojson_to_esri().
    """
    params = {
        "geometry": geometry_json,
        "geometryType": geometry_type,
        "inSR": WGS84,
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json",
    }
    data = _get_json(f"{BASE_URL}/{layer_id}/query", params, timeout=timeout)
    return int(data.get("count", 0))


def query_geometry(
    geometry_json: str,
    geometry_type: str,
    layer_id: int = LAYER_FLOOD_HAZARD_ZONES,
    out_fields: list[str] | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    timeout: int = DEFAULT_TIMEOUT,
) -> QueryResult:
    """Return flood features intersecting an arbitrary Esri geometry, with provenance.

    geometry_json and geometry_type should come from _geojson_to_esri().
    Geometry is intentionally NOT returned (returnGeometry=false) to keep the
    payload small for the agent's context window. Paginates automatically.
    """
    out_fields = out_fields or FLOOD_ZONE_FIELDS

    base_params = {
        "geometry": geometry_json,
        "geometryType": geometry_type,
        "inSR": WGS84,
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": ",".join(out_fields),
        "returnGeometry": "false",
        "f": "json",
    }

    features: list[dict[str, Any]] = []
    offset = 0
    truncated = False
    while True:
        params = dict(base_params)
        params["resultOffset"] = offset
        params["resultRecordCount"] = DEFAULT_MAX_RECORDS
        data = _get_json(f"{BASE_URL}/{layer_id}/query", params, timeout=timeout)
        page = [f.get("attributes", {}) for f in data.get("features", [])]
        features.extend(page)

        if len(features) >= max_records:
            features = features[:max_records]
            truncated = True
            break
        if not data.get("exceededTransferLimit") and len(page) < DEFAULT_MAX_RECORDS:
            break  # got everything
        offset += len(page)
        if not page:
            break

    citation = None
    for f in features:
        if f.get("SOURCE_CIT"):
            citation = f["SOURCE_CIT"]
            break

    prov = Provenance(layer_id=layer_id, source_citation=citation)
    return QueryResult(
        features=features,
        count=len(features),
        truncated=truncated,
        provenance=prov,
    )


def list_layers(timeout: int = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Return the layer catalog (id, name, geometry type) for discovery."""
    data = _get_json(BASE_URL, {"f": "json"}, timeout=timeout)
    return [
        {"id": l.get("id"), "name": l.get("name"), "geometry_type": l.get("geometryType")}
        for l in data.get("layers", [])
    ]
