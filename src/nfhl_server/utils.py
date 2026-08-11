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

def _interpret(features: list[dict[str, Any]]) -> str:
    """Turn raw attributes into a one-line plain-language finding for the agent."""
    if not features:
        return "No mapped flood hazard zone at this location (outside NFHL coverage or unmapped)."
    in_sfha = any(f.get("SFHA_TF") == "T" for f in features)
    zones = sorted({f.get("FLD_ZONE") for f in features if f.get("FLD_ZONE")})
    subtypes = sorted({f.get("ZONE_SUBTY") for f in features if f.get("ZONE_SUBTY")})
    lead = "IN a Special Flood Hazard Area" if in_sfha else "NOT in a Special Flood Hazard Area"
    detail = f" Zone(s): {', '.join(zones)}." if zones else ""
    sub = f" Subtype(s): {', '.join(subtypes)}." if subtypes else ""
    return f"Point is {lead}.{detail}{sub}"


# ---------------------------------------------------------------------------
# NFHL HTTP client
# ---------------------------------------------------------------------------

class NFHLError(RuntimeError):
    """Raised when the NFHL service errors or returns something unusable."""


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


def _point_geometry(lon: float, lat: float) -> str:
    """Encode a point as an Esri geometry JSON string.

    NOTE ORDER: Esri expects x=lon, y=lat. Swapping these is the single most
    common GIS bug -- we keep it in one place so it's only ever done once.
    """
    return json.dumps({"x": lon, "y": lat, "spatialReference": {"wkid": WGS84}})


def count_at_point(lon: float, lat: float, layer_id: int, timeout: int = DEFAULT_TIMEOUT) -> int:
    """Return ONLY the number of features intersecting a point.

    This is the cost/completeness guardrail: check size before fetching.
    """
    params = {
        "geometry": _point_geometry(lon, lat),
        "geometryType": "esriGeometryPoint",
        "inSR": WGS84,
        "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true",
        "f": "json",
    }
    data = _get_json(f"{BASE_URL}/{layer_id}/query", params, timeout=timeout)
    return int(data.get("count", 0))


def query_point(
    lon: float,
    lat: float,
    layer_id: int = LAYER_FLOOD_HAZARD_ZONES,
    out_fields: list[str] | None = None,
    max_records: int = DEFAULT_MAX_RECORDS,
    timeout: int = DEFAULT_TIMEOUT,
) -> QueryResult:
    """Return flood features intersecting a lon/lat point, with provenance.

    Geometry is intentionally NOT returned (returnGeometry=false) to keep the
    payload small for the agent's context window. If the count exceeds the
    service cap we page through with resultOffset and flag truncation only if
    we deliberately stop.
    """
    out_fields = out_fields or FLOOD_ZONE_FIELDS
    geometry = _point_geometry(lon, lat)

    base_params = {
        "geometry": geometry,
        "geometryType": "esriGeometryPoint",
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
