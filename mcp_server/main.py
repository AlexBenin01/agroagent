"""AgroAgent MCP Server: FastAPI + FastMCP (Streamable HTTP) + SSE + REST."""
import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydField
from sqlalchemy import select

from models import FieldEvent

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

# Su server stateless langchain-mcp-adapters apre e chiude una sessione MCP per
# ogni invocazione di tool: la chiusura genera ClosedResourceError / "Error in
# message router" / "Terminating session" — rumore benigno. Lo silenziamo.
logging.getLogger("mcp.server.streamable_http").setLevel(logging.CRITICAL)

mcp_asgi = mcp.streamable_http_app()

SSE_HEARTBEAT_SECONDS = 15


async def background_tick() -> None:
    """Avanza la simulazione in tempo reale: a ×1, 1 giorno simulato dura
    SIM_DAY_REAL_MINUTES minuti reali. Ogni tick avanza `time_speed *
    SIM_HOURS_PER_TICK` ore per campo (0 = in pausa); l'intervallo reale fra i
    tick è derivato così che 24 ore simulate coprano un giorno reale a ×1."""
    while True:
        await asyncio.sleep(config.TICK_INTERVAL_SECONDS)
        try:
            async with SessionLocal() as session:
                fields = (
                    await session.execute(select(Field.id, Field.time_speed))
                ).all()
            for fid, speed in fields:
                if speed and speed > 0:
                    await advance_field_and_publish(
                        str(fid), int(speed) * config.SIM_HOURS_PER_TICK
                    )
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
    difficulty: str = PydField(default="normal", pattern="^(normal|hard|apocalypse)$")


class SpeedUpdate(BaseModel):
    speed: int = PydField(ge=0, le=4)


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
        field = await create_field(
            session, name=body.name, rows=body.rows, cols=body.cols,
            difficulty=body.difficulty,
        )
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


@app.get("/api/fields/{field_id}/inventory")
async def get_inventory(field_id: str) -> dict:
    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
        except ValueError as err:
            raise _handle(err)
        return await queries.inventory_state(session, field)


@app.post("/api/fields/{field_id}/speed")
async def set_speed(field_id: str, body: SpeedUpdate) -> dict:
    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
        except ValueError as err:
            raise _handle(err)
        field.time_speed = body.speed
        await session.commit()
        serialized = queries.serialize_field(field)
    broker.publish(field_id, "speed_changed", {"time_speed": body.speed})
    return serialized


ALLOWED_PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png"}
MAX_PHOTO_BYTES = 6 * 1024 * 1024


@app.post("/api/fields/{field_id}/cells/{x}/{y}/photo", status_code=201)
async def upload_cell_photo(
    field_id: str, x: int, y: int, file: UploadFile = File(...)
) -> dict:
    """Carica una foto REALE della pianta sulla cella (x,y). Il file è salvato
    in modo DURATURO (bind su host) con nome univoco a timestamp (nessuna
    sovrascrittura) e diventa l'ultima foto della cella."""
    ext = ALLOWED_PHOTO_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(status_code=400, detail="Formato non supportato: usa JPG o PNG")
    data = await file.read()
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=400, detail="Immagine troppo grande (max 6 MB)")
    if not data:
        raise HTTPException(status_code=400, detail="File vuoto")

    async with SessionLocal() as session:
        try:
            field = await queries.get_field_or_error(session, field_id)
            cell = await queries.get_cell_or_error(session, field, x, y)
        except ValueError as err:
            raise _handle(err)

        rel = f"{field.id}/{x}_{y}_{int(time.time() * 1000)}{ext}"
        dest = Path(config.UPLOAD_BASE_PATH) / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

        # le foto caricate sono servite da /uploads (path assoluto con leading '/'),
        # quelle del dataset da /images: serialize_cell distingue dal prefisso
        cell.last_photo_path = f"/uploads/{rel}"
        cell.last_inspected_at = field.simulation_time
        session.add(
            FieldEvent(
                field_id=field.id,
                event_type="photo_uploaded",
                cell_x=x,
                cell_y=y,
                description=f"Foto reale caricata sulla cella ({x},{y}): /uploads/{rel}",
                sim_time=field.simulation_time,
            )
        )
        names = await queries.disease_names_map(session)
        images = await queries.disease_image_map(session)
        snapshot = queries.serialize_cell(cell, names, images)
        sim_time = queries.iso(field.simulation_time)
        await session.commit()

    broker.publish(field_id, "field_update", {"cells": [snapshot], "sim_time": sim_time})
    return {"photo_url": cell.last_photo_path, "cell": snapshot}


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

# Foto reali caricate dal contadino (storage durevole su host)
Path(config.UPLOAD_BASE_PATH).mkdir(parents=True, exist_ok=True)
app.mount(
    "/uploads",
    StaticFiles(directory=config.UPLOAD_BASE_PATH, check_dir=False),
    name="uploads",
)

# L'app FastMCP (route interna /mcp) è montata per ultima: cattura solo ciò
# che non corrisponde alle route precedenti. Protetta dal bearer middleware.
app.mount("/", mcp_asgi)
