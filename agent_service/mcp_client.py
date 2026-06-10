"""Client MCP (Streamable HTTP + bearer token) → tool LangChain.

langchain-mcp-adapters apre una sessione MCP per ogni invocazione di tool:
corretto per un server stateless come il nostro.
"""
from langchain_mcp_adapters.client import MultiServerMCPClient

import config

_client: MultiServerMCPClient | None = None
_tools: list | None = None


def get_client() -> MultiServerMCPClient:
    global _client
    if _client is None:
        _client = MultiServerMCPClient(
            {
                "agroagent": {
                    "transport": "streamable_http",
                    "url": config.MCP_SERVER_URL,
                    "headers": {"Authorization": f"Bearer {config.MCP_AUTH_TOKEN}"},
                }
            }
        )
    return _client


async def get_mcp_tools(force_refresh: bool = False) -> list:
    """Scopre i tool dal server MCP (cache di processo)."""
    global _tools
    if _tools is None or force_refresh:
        _tools = await get_client().get_tools()
    return _tools
