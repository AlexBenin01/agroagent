"""Tool MCP di osservazione del campo."""
import queries
from db.session import SessionLocal
from mcp_app import mcp


@mcp.tool()
async def get_field_state(field_id: str) -> dict:
    """Restituisce lo stato completo del campo: griglia celle (sensori, salute,
    rischio malattia, stato), meteo corrente con previsione 7 giorni, task
    attivi e checkpoint aperti."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        return await queries.field_state(session, field)


@mcp.tool()
async def get_cell_detail(field_id: str, x: int, y: int) -> dict:
    """Restituisce il dettaglio completo di una singola cella (x,y): sensori,
    malattia attiva con sintomi e protocollo, storico eventi recenti, foto
    più recente, task in corso e checkpoint aperti."""
    async with SessionLocal() as session:
        field = await queries.get_field_or_error(session, field_id)
        return await queries.cell_detail(session, field, x, y)
