"""Agent Service: endpoint /chat che orchestra l'agente LangGraph."""
import logging
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm.attributes import flag_modified

import config
from agent import run_agent
from db import ChatSession, SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent_service")

app = FastAPI(title="AgroAgent Agent Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[config.FRONTEND_ORIGIN],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    field_id: str | None = None
    session_id: str | None = None


def _parse_uuid(value: str, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail=f"{name} non valido: {value!r}")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/chat")
async def chat(body: ChatRequest) -> dict:
    async with SessionLocal() as session:
        chat_session = None
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

        history = list(chat_session.messages)
        try:
            result = await run_agent(str(chat_session.field_id), history, body.message)
        except Exception as err:  # endpoint LLM giù/non configurato, tunnel scaduto…
            logger.exception("Esecuzione agente fallita")
            raise HTTPException(
                status_code=502,
                detail=(
                    "L'agente non è raggiungibile o l'endpoint LLM non risponde. "
                    f"Verifica OPENAI_BASE_URL nel .env. Errore: {type(err).__name__}: {err}"
                ),
            )

        history.append({"role": "user", "content": body.message})
        history.append({"role": "assistant", "content": result["reply"]})
        chat_session.messages = history[-config.HISTORY_MAX_MESSAGES:]
        flag_modified(chat_session, "messages")
        session_id = str(chat_session.id)
        await session.commit()

    return {
        "session_id": session_id,
        "reply": result["reply"],
        "tool_calls": result["tool_calls"],
    }


@app.get("/chat/{session_id}/history")
async def history(session_id: str) -> dict:
    async with SessionLocal() as session:
        chat_session = await session.get(
            ChatSession, _parse_uuid(session_id, "session_id")
        )
        if chat_session is None:
            raise HTTPException(status_code=404, detail="Sessione chat inesistente")
        return {
            "session_id": session_id,
            "field_id": str(chat_session.field_id),
            "messages": chat_session.messages,
        }
