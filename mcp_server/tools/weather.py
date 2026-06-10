"""Tool MCP: meteo e avanzamento del tempo simulato."""
import queries
from db.session import SessionLocal
from field_engine import advance_field_and_publish
from mcp_app import mcp

MAX_ADVANCE_HOURS = 720


@mcp.tool()
async def get_weather_summary(field_id: str, days_back: int = 7) -> dict:
    """Riassunto meteo: pioggia cumulata e umidità media degli ultimi N giorni
    simulati, range temperature e previsione per i prossimi 7 giorni."""
    if not 1 <= days_back <= 30:
        raise ValueError("days_back deve essere tra 1 e 30")
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        return await queries.weather_summary(session, field, days_back)


@mcp.tool()
async def advance_simulation_time(field_id: str, hours: int) -> dict:
    """Avanza l'orologio SIMULATO del campo di N ore (1-720). Ricalcola meteo,
    umidità del suolo e rischio malattie, completa i task il cui ends_at_sim
    viene raggiunto e genera gli eventi di campo. Notifica il client via SSE."""
    if not 1 <= hours <= MAX_ADVANCE_HOURS:
        raise ValueError(f"hours deve essere tra 1 e {MAX_ADVANCE_HOURS}")
    # valida il field_id prima di delegare al motore
    async with SessionLocal() as session:
        await queries.get_field_or_error(session, field_id)
    return await advance_field_and_publish(field_id, hours)
