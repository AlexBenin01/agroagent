"""AgroAgent MCP Server: FastAPI + FastMCP (Streamable HTTP) + REST per il frontend."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field as PydField

import config
import queries
import tools  # noqa: F401 — l'import registra i tool MCP
from auth import MCPBearerAuthMiddleware
from db.session import SessionLocal
from field_factory import create_field
from mcp_app import mcp

mcp_asgi = mcp.streamable_http_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


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
        from sqlalchemy import select

        from models import Field

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


# Immagini del dataset: StaticFiles gestisce già la protezione path-traversal
app.mount(
    "/images",
    StaticFiles(directory=config.IMAGE_BASE_PATH, check_dir=False),
    name="images",
)

# L'app FastMCP (route interna /mcp) è montata per ultima: cattura solo ciò
# che non corrisponde alle route precedenti. Protetta dal bearer middleware.
app.mount("/", mcp_asgi)
