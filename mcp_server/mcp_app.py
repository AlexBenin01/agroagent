"""Istanza FastMCP condivisa. I moduli in tools/ vi registrano i tool."""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="agroagent",
    instructions=(
        "Server MCP di AgroAgent: espone osservazione e azioni su un vigneto "
        "simulato (griglia di celle, sensori, meteo, malattie, trattamenti)."
    ),
    stateless_http=True,
    json_response=True,
)
