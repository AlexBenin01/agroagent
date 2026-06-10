"""Smoke test del server MCP: auth, lista tool, chiamata get_field_state.

Eseguito dentro il container mcp_server (o agent_service):
    docker compose exec mcp_server python /app/scripts_mcp_smoke_test.py
"""
import asyncio
import json
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_TEST_URL", "http://localhost:8001/mcp")
TOKEN = os.environ["MCP_AUTH_TOKEN"]


async def main() -> None:
    # 1) senza token -> 401
    async with httpx.AsyncClient() as client:
        resp = await client.post(MCP_URL, json={})
        assert resp.status_code == 401, f"atteso 401 senza token, ottenuto {resp.status_code}"
        print("[ok] /mcp senza token -> 401")

    # 2) con token: initialize, list tools, call get_field_state
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"[ok] tool registrati ({len(names)}): {names}")

            async with httpx.AsyncClient() as client:
                fields = (await client.get("http://localhost:8001/api/fields")).json()
            field_id = fields[0]["id"]

            result = await session.call_tool("get_field_state", {"field_id": field_id})
            payload = json.loads(result.content[0].text)
            assert len(payload["cells"]) == 100, "attese 100 celle"
            print(f"[ok] get_field_state: {len(payload['cells'])} celle, "
                  f"sim_time={payload['field']['sim_time']}")

            result = await session.call_tool(
                "get_cell_detail", {"field_id": field_id, "x": 2, "y": 2}
            )
            detail = json.loads(result.content[0].text)
            print(f"[ok] get_cell_detail(2,2): status={detail['cell']['status']}, "
                  f"malattia={detail['cell']['active_disease']}")

            # 3) validazione bounds: coordinate fuori griglia -> errore esplicito
            result = await session.call_tool(
                "get_cell_detail", {"field_id": field_id, "x": 99, "y": 0}
            )
            assert result.isError, "attese coordinate rifiutate"
            print(f"[ok] bounds check: {result.content[0].text[:80]}")

    print("\nSmoke test MCP: TUTTO OK")


if __name__ == "__main__":
    asyncio.run(main())
