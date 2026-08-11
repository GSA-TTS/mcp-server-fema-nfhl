"""
list_layers tool
-----------------
Registers the nfhl_list_layers tool on the MCP server.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..models import Provenance
from ..utils import NFHLError, _now_utc, list_layers as _list_layers


def register(mcp: FastMCP) -> None:
    """Register the list_layers tool with the MCP server."""

    @mcp.tool(
        name="nfhl_list_layers",
        annotations={
            "title": "List NFHL Service Layers",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    def list_nfhl_layers() -> dict[str, Any]:
        """List the layers available in the NFHL service (id, name, geometry type).

        Use when: You need to discover available NFHL layers, find floodways,
        FIRM panels, LOMRs, or other layers beyond the default flood-hazard-zones layer.

        Returns:
        {
            "layers": [{"id": int, "name": str, "geometry_type": str}, ...],
            "provenance": { source agency, service URL, retrieved_utc }
        }

        Error responses:
        - "Error: NFHL request failed: ..." — network or service error
        """
        try:
            return {
                "layers": _list_layers(),
                "provenance": Provenance(retrieved_utc=_now_utc()).to_dict(),
            }
        except NFHLError as exc:
            return {"error": f"Error: NFHL request failed: {exc}"}
