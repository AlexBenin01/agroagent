"""Agent Service: endpoint /chat (+ /chat/stream) con memoria LangGraph.

La memoria di conversazione è gestita dal checkpointer Postgres (thread_id =
sessione); lo Store Postgres tiene la memoria a lungo termine cross-sessione.
Entrambi sono aperti nel lifespan e iniettati in agent.py.
"""
import json
import logging
import uuid
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from langchain_openai import OpenAIEmbeddings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from pydantic import BaseModel, Field

import agent
import config
from agent import run_agent, run_agent_stream
from db import ChatSession, SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Apre checkpointer e store Postgres per la durata dell'app."""
    index = None
    if config.EMBEDDINGS_BASE_URL and config.EMBEDDINGS_MODEL:
        embeddings = OpenAIEmbeddings(
            base_url=config.EMBEDDINGS_BASE_URL,
            api_key=config.EMBEDDINGS_API_KEY or "not-needed",
            model=config.EMBEDDINGS_MODEL,
        )
        index = {"embed": embeddings, "dims": config.EMBEDDINGS_DIMS, "fields": ["$"]}

    async with AsyncExitStack() as stack:
        saver = await stack.enter_async_context(
            AsyncPostgresSaver.from_conn_string(config.PG_DSN)
        )
        store = await stack.enter_async_context(
            AsyncPostgresStore.from_conn_string(config.PG_DSN, index=index)
        )
        await saver.setup()
        await store.setup()
        agent.set_memory(saver, store)
        logger.info("Memoria LangGraph pronta (ricerca semantica=%s)", bool(index))
        yield


app = FastAPI(title="AgroAgent Agent Service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class CellRef(BaseModel):
    x: int
    y: int


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    field_id: str | None = None
    session_id: str | None = None
    # foto reale allegata (data URL base64) e cella bersaglio per la diagnosi
    image: str | None = None
    cell: CellRef | None = None


def _parse_uuid(value: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"{name} non valido: {value!r}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


async def _resolve_session(body: ChatRequest) -> tuple[str, str]:
    """Carica o crea la sessione chat. Restituisce (session_id, field_id).
    La cronologia dei messaggi è gestita dal checkpointer, non qui."""
    async with SessionLocal() as session:
        if body.session_id:
            chat_session = await session.get(
                ChatSession, _parse_uuid(body.session_id, "session_id")
            )
            if chat_session is None:
                raise HTTPException(status_code=404, detail="Sessione chat inesistente")
        else:
            if not body.field_id:
                raise HTTPException(
                    status_code=400,
                    detail="field_id obbligatorio per aprire una nuova sessione",
                )
            chat_session = ChatSession(
                field_id=_parse_uuid(body.field_id, "field_id"), messages=[]
            )
            session.add(chat_session)
            await session.flush()
        session_id = str(chat_session.id)
        field_id = str(chat_session.field_id)
        await session.commit()
    return session_id, field_id


@app.post("/chat")
async def chat(body: ChatRequest) -> dict:
    session_id, field_id = await _resolve_session(body)
    cell = body.cell.model_dump() if body.cell else None
    try:
        result = await run_agent(field_id, session_id, body.message, body.image, cell)
    except Exception as err:  # endpoint LLM giù/non configurato, tunnel scaduto…
        logger.exception("Esecuzione agente fallita")
        raise HTTPException(
            status_code=502,
            detail=(
                "L'agente non è raggiungibile o l'endpoint LLM non risponde. "
                f"Verifica OPENAI_BASE_URL nel .env. Errore: {type(err).__name__}: {err}"
            ),
        )
    return {
        "session_id": session_id,
        "reply": result["reply"],
        "tool_calls": result["tool_calls"],
    }


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
async def chat_stream(body: ChatRequest) -> StreamingResponse:
    """Variante streaming di /chat: emette i token dell'agente man mano (SSE),
    gli eventi di tool e, alla fine, le metriche (TTFToken/TTFtool)."""
    session_id, field_id = await _resolve_session(body)
    cell = body.cell.model_dump() if body.cell else None

    async def event_stream():
        yield _sse("session", {"session_id": session_id})
        async for ev in run_agent_stream(field_id, session_id, body.message, body.image, cell):
            yield _sse(ev["type"], ev)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/chat/{session_id}/history")
async def history(session_id: str) -> dict:
    async with SessionLocal() as session:
        chat_session = await session.get(
            ChatSession, _parse_uuid(session_id, "session_id")
        )
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Sessione chat inesistente")
        field_id = str(chat_session.field_id)
    messages = await agent.history_messages(field_id, session_id)
    return {"session_id": session_id, "field_id": field_id, "messages": messages}
