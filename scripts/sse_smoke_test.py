"""Smoke test SSE: sottoscrive /events/{field_id}, avanza il tempo via MCP
e verifica di ricevere time_advanced + field_update.

    docker compose exec mcp_server python /app/sse_smoke_test.py
"""
import asyncio
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_TEST_URL", "http://localhost:8001/mcp")
TOKEN = os.environ["MCP_AUTH_TOKEN"]


async def listen(field_id: str, received: list, ready: asyncio.Event) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        async with client.stream("GET", f"http://localhost:8001/events/{field_id}") as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line == ": connected":
                    ready.set()
                if line.startswith("event:"):
                    received.append(line.split(":", 1)[1].strip())
                if "time_advanced" in received and "field_update" in received:
                    return


async def main() -> None:
    async with httpx.AsyncClient() as client:
        fields = (await client.get("http://localhost:8001/api/fields")).json()
    field_id = fields[0]["id"]

    received: list[str] = []
    ready = asyncio.Event()
    listener = asyncio.create_task(listen(field_id, received, ready))
    await asyncio.wait_for(ready.wait(), timeout=10)

    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            await session.call_tool(
                "advance_simulation_time", {"field_id": field_id, "hours": 6}
            )

    await asyncio.wait_for(listener, timeout=10)
    print(f"[ok] eventi SSE ricevuti: {received}")
    assert "time_advanced" in received and "field_update" in received
    print("\nSmoke test SSE: TUTTO OK")


if __name__ == "__main__":
    asyncio.run(main())
