"""Smoke test Sprint 2: tool azione, foto, avanzamento tempo, chiusura task.

    docker compose exec mcp_server python /app/sprint2_smoke_test.py
"""
import asyncio
import json
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

MCP_URL = os.getenv("MCP_TEST_URL", "http://localhost:8001/mcp")
TOKEN = os.environ["MCP_AUTH_TOKEN"]


def parse(result):
    if result.isError:
        raise AssertionError(f"tool error: {result.content[0].text}")
    return json.loads(result.content[0].text)


async def main() -> None:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    # campo fresco per ogni run: il test resta idempotente
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:8001/api/fields", json={"name": "Campo Test Sprint2"}
        )
        assert resp.status_code == 201, resp.text
        field_id = resp.json()["id"]

    async with streamablehttp_client(MCP_URL, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            print(f"[ok] {len(names)} tool: {names}")
            assert len(names) == 13, "attesi 13 tool MCP"

            state = parse(await session.call_tool("get_field_state", {"field_id": field_id}))
            diseased = [c for c in state["critical_cells"] if c["status"] == "diseased"]
            assert diseased, "attesa almeno una cella malata nel campo demo"
            cx, cy = diseased[0]["x"], diseased[0]["y"]
            print(f"[ok] cella malata ({cx},{cy}): {diseased[0]['active_disease']}")

            focus = parse(await session.call_tool(
                "move_focus_area", {"field_id": field_id, "x": cx, "y": cy}))
            assert focus["focus"] == {"x": cx, "y": cy}
            print(f"[ok] move_focus_area -> ({cx},{cy})")

            photo = parse(await session.call_tool(
                "capture_field_photo", {"field_id": field_id, "x": cx, "y": cy}))
            assert photo["photo_url"].startswith("/images/diseased/")
            print(f"[ok] capture_field_photo -> {photo['photo_url']}")

            cp = parse(await session.call_tool("create_checkpoint", {
                "field_id": field_id, "x": cx, "y": cy,
                "checkpoint_type": "disease_found",
                "note": "Sintomi di Marciume nero confermati da foto"}))
            print(f"[ok] create_checkpoint -> {cp['id'][:8]}…")

            # senza prodotto a magazzino, il trattamento chimico va rifiutato
            no_stock = await session.call_tool("start_treatment", {
                "field_id": field_id, "x": cx, "y": cy, "treatment_type": "chemical"})
            assert no_stock.isError, "atteso rifiuto: trattamento chimico senza prodotto"
            print("[ok] trattamento chimico senza prodotto rifiutato")

            # inventario: ordina un prodotto adatto e attendi la consegna
            inv = parse(await session.call_tool("query_inventory", {"field_id": field_id}))
            product = next(
                p for p in inv["products"]
                if "fungus" in p["targets"] or "any" in p["targets"]
            )
            order = parse(await session.call_tool("order_product", {
                "field_id": field_id, "product_id": product["id"], "quantity": 1}))
            print(f"[ok] order_product -> {product['name']}, consegna ~{order['delivery_hours']}h")

            await session.call_tool("advance_simulation_time", {
                "field_id": field_id, "hours": order["delivery_hours"]})
            inv2 = parse(await session.call_tool("query_inventory", {"field_id": field_id}))
            stock = next(p["in_stock"] for p in inv2["products"] if p["id"] == product["id"])
            assert stock >= 1, "il prodotto ordinato doveva essere consegnato"
            print(f"[ok] consegna ricevuta -> stock {product['name']}={stock}")

            task = parse(await session.call_tool("start_treatment", {
                "field_id": field_id, "x": cx, "y": cy,
                "treatment_type": "chemical", "product_id": product["id"]}))
            print(f"[ok] start_treatment -> task {task['id'][:8]}…, "
                  f"fine prevista {task['ends_at_sim']}")

            # doppio trattamento sulla stessa cella -> rifiutato
            dup = await session.call_tool("start_treatment", {
                "field_id": field_id, "x": cx, "y": cy,
                "treatment_type": "chemical", "product_id": product["id"]})
            assert dup.isError, "atteso rifiuto del secondo task sulla stessa cella"
            print("[ok] doppio task sulla stessa cella rifiutato")

            weather = parse(await session.call_tool(
                "get_weather_summary", {"field_id": field_id, "days_back": 7}))
            print(f"[ok] get_weather_summary: pioggia 7gg={weather['total_rainfall_mm']}mm, "
                  f"forecast={len(weather['forecast'])} giorni")

            # avanza 72h: il trattamento chimico (72h) deve completarsi
            adv = parse(await session.call_tool(
                "advance_simulation_time", {"field_id": field_id, "hours": 72}))
            done = [t for t in adv["completed_tasks"] if t["id"] == task["id"]]
            assert done, "il task di trattamento doveva completarsi dopo 72h"
            print(f"[ok] advance_simulation_time 72h -> task completato, "
                  f"sim_time={adv['new_sim_time']}, eventi={len(adv['events_generated'])}")

            detail = parse(await session.call_tool(
                "get_cell_detail", {"field_id": field_id, "x": cx, "y": cy}))
            assert detail["cell"]["status"] == "treated", detail["cell"]["status"]
            assert detail["cell"]["active_disease"] is None
            print(f"[ok] cella ({cx},{cy}) ora 'treated', health={detail['cell']['health_score']}")

            # bounds: ore fuori range
            bad = await session.call_tool(
                "advance_simulation_time", {"field_id": field_id, "hours": 9999})
            assert bad.isError
            print("[ok] hours=9999 rifiutato")

            catalog = parse(await session.call_tool("query_disease_catalog", {
                "crop_type": "vite",
                "symptoms": ["macchie circolari brune sulle foglie"],
                "weather_conditions": {"temp": 22, "humidity_pct": 85}}))["matches"]
            assert catalog[0]["name"].startswith("Marciume nero"), catalog[0]["name"]
            print(f"[ok] query_disease_catalog -> top: {catalog[0]['name']} "
                  f"(score {catalog[0]['match_score']})")

            protocol = parse(await session.call_tool(
                "get_care_protocol", {"disease_id": catalog[0]["id"]}))
            print(f"[ok] get_care_protocol -> {protocol['recommended_action'][:50]}…")

    print("\nSmoke test Sprint 2: TUTTO OK")


if __name__ == "__main__":
    asyncio.run(main())
