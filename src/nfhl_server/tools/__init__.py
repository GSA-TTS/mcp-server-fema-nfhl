from . import count_flood_features, list_layers, screen_flood_zone


def register_tools(mcp):
    """Register all tools with the MCP server."""
    screen_flood_zone.register(mcp)
    count_flood_features.register(mcp)
    list_layers.register(mcp)
