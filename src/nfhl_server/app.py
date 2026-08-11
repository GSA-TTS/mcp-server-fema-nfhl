import os

from dotenv import load_dotenv
from fastmcp import FastMCP

from nfhl_server.tools import register_tools
from nfhl_server.routes import register_routes

load_dotenv()  # loads .env before any code reads env vars

# Initialize FastMCP server
mcp = FastMCP(
    "nfhl_mcp",
    instructions=(
        "Wraps the FEMA National Flood Hazard Layer (NFHL) ArcGIS REST API so an LLM "
        "can query official FEMA flood hazard data for permitting screening and site analysis.\n\n"
        "TOOL SELECTION GUIDE:\n"
        "- Flood zone for an address or lat/lon → nfhl_screen_flood_zone\n"
        "- Check how many flood features overlap a point (size guardrail) → nfhl_count_flood_features\n"
        "- Discover all available NFHL layers (floodways, FIRM panels, LOMRs, etc.) → nfhl_list_layers\n\n"
        "CONVENTIONS:\n"
        "- All coordinates are WGS84 decimal degrees (lat, lon). Convert addresses to coordinates first.\n"
        "- BFE / DEPTH of -9999 means 'not applicable or not mapped' for that zone.\n"
        "- Results include provenance (source agency, service URL, layer, CRS, citation, retrieval time).\n"
        "- No authentication required — the NFHL service is publicly accessible."
    ),
)

# Register custom tools
register_tools(mcp)

# Register custom routes
register_routes(mcp)

if __name__ == "__main__":
    port_env = os.getenv("DATABRICKS_APP_PORT") or os.getenv("PORT")
    if port_env:
        mcp.run(transport="http", host="0.0.0.0", port=int(port_env), path="/mcp")
    else:
        mcp.run(transport="stdio")
