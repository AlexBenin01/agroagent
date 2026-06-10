"""AgroAgent MCP Server: FastAPI + FastMCP (Streamable HTTP) + SSE + REST."""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydField
from sqlalchemy import select

import config
import queries
import tools  # noqa: F401 — l'import registra i tool MCP
from auth import MCPBearerAuthMiddleware
from db.session import SessionLocal
from field_engine import advance_field_and_publish
from field_factory import create_field
from mcp_app import mcp
from models import Field
from sse import broker

logger = logging.getLogger("mcp_server")

mcp_asgi = mcp.streamable_http_app()

SSE_HEARTBEAT_SECONDS = 15


async def background_tick() -> None:
    """Ogni N minuti reali avanza la simulazione di 1 ora per ogni campo."""
    while True:
        await asyncio.sleep(config.FIELD_TICK_INTERVAL_MINUTES * 60)
        try:
            async with SessionLocal() as session:
                field_ids = (await session.execute(select(Field.id))).scalars().all()
            for fid in field_ids:
                await advance_field_and_publish(str(fid), 1)
        except Exception:
            logger.exception("Tick di background fallito")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        tick_task = asyncio.create_task(background_tick())
        try:
            yield
        finally:
            tick_task.cancel()


app = FastAPI(title="AgroAgent MCP Server", lifespan=lifespan)

# CORS: allowlist esplicita del solo frontend (mai "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(MCPBearerAuthMiddleware, token=config.MCP_AUTH_TOKEN)


def _handle(err: ValueError) -> HTTPException:
    msg = str(err)
    status = 404 if "inesistente" in msg else 400
    return HTTPException(status_code=status, detail=msg)


class FieldCreate(BaseModel):
    name: str = PydField(default="Nuovo campo", min_length=1, max_length=100)
    rows: int | None = PydField(default=None, ge=2, le=20)
    cols: int | None = PydField(default=None, ge=2, le=20)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/api/fields")
async def list_fields() -> list[dict]:
    async with SessionLocal() as session:
        result = await session.execute(select(Field).order_by(Field.created_at))
        return [queries.serialize_field(f) for f in result.scalars()]


@app.post("/api/fields", status_code=201)
async def create_field_endpoint(body: FieldCreate) -> dict:
    async with SessionLocal() as session:
        field = await create_field(session, name=body.name, rows=body.rows, cols=body.cols)
        await session.commit()
        return queries.serialize_field(field)


@app.get("/api/fields/{field_id}")
async def get_field(field_id: str) -> dict:
    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
        except ValueError as err:
            raise _handle(err)
        return await queries.field_state(session, field)


@app.get("/api/fields/{field_id}/cells")
async def get_cells(field_id: str) -> list[dict]:
    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
        except ValueError as err:
            raise _handle(err)
        state = await queries.field_state(session, field)
        return state["cells"]


@app.get("/api/fields/{field_id}/events")
async def get_events(field_id: str, limit: int = 20) -> list[dict]:
    limit = max(1, min(limit, 100))
    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
        except ValueError as err:
            raise _handle(err)
        return await queries.recent_events(session, field, limit)


@app.get("/events/{field_id}")
async def sse_events(field_id: str) -> StreamingResponse:
    """Stream SSE degli aggiornamenti campo. Heartbeat ogni 15s; alla
    riconnessione il client rifà il fetch completo via GET /api/fields/{id}."""
    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
        except ValueError as err:
            raise _handle(err)
    fid = str(field.id)

    async def stream():
        queue = broker.subscribe(fid)
        try:
            yield ": connected\n\n"
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            broker.unsubscribe(fid, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Immagini del dataset: StaticFiles gestisce già la protezione path-traversal
app.mount(
    "/images",
    StaticFiles(directory=config.IMAGE_BASE_PATH, check_dir=False),
    name="images",
)

# L'app FastMCP (route interna /mcp) è montata per ultima: cattura solo ciò
# che non corrisponde alle route precedenti. Protetta dal bearer middleware.
app.mount("/", mcp_asgi)
