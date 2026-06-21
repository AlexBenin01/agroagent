"""Agente LangGraph ReAct con memoria LangGraph nativa.

- Memoria di thread (breve termine): checkpointer Postgres, thread_id = sessione.
- Controllo del contesto: SummarizationNode (langmem) come pre_model_hook.
- Memoria a lungo termine (cross-sessione): Store Postgres con namespace per
  campo, esposto all'agente come memory-tool (manage/search).
"""
import logging
import re
import time
from pathlib import Path
from typing import AsyncIterator

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.messages.utils import count_tokens_approximately
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.chat_agent_executor import AgentState
from langmem import create_manage_memory_tool, create_search_memory_tool
from langmem.short_term import RunningSummary, SummarizationNode

import config
from mcp_client import get_mcp_tools

logger = logging.getLogger("agent")

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

SYSTEM_PROMPT_TEMPLATE = (
    Path(__file__).parent / "prompts" / "system_prompt.txt"
).read_text(encoding="utf-8")

# Qwen3/vLLM: disattiva il ragionamento <think> via chat_template_kwargs.
# (modelli che non lo supportano ignorano l'extra_body)
_extra_body = (
    None if config.LLM_ENABLE_THINKING
    else {"chat_template_kwargs": {"enable_thinking": False}}
)

llm = ChatOpenAI(
    base_url=config.OPENAI_BASE_URL,
    api_key=config.OPENAI_API_KEY,
    model=config.LLM_MODEL,
    temperature=0.2,
    timeout=config.LLM_TIMEOUT_SECONDS,
    extra_body=_extra_body,
)


class MemoryAgentState(AgentState):
    # spazio dove SummarizationNode conserva il riassunto progressivo
    context: dict[str, RunningSummary]


_summarization_node = SummarizationNode(
    token_counter=count_tokens_approximately,
    model=llm,
    max_tokens=config.CONTEXT_MAX_TOKENS,
    max_tokens_before_summary=config.CONTEXT_MAX_TOKENS,
    max_summary_tokens=512,
    output_messages_key="llm_input_messages",
)

# Saver e Store sono creati e tenuti aperti dal lifespan di main.py
_saver = None
_store = None
_graphs: dict[str, object] = {}


def set_memory(saver, store) -> None:
    global _saver, _store
    _saver, _store = saver, store


def _visible_text(raw: str) -> str:
    """Rimuove i blocchi <think>…</think> (anche se ancora aperti) dal testo
    accumulato, così i token di ragionamento non vengono mostrati all'utente."""
    text = _THINK_RE.sub("", raw)
    open_idx = text.find("<think>")
    if open_idx != -1:
        text = text[:open_idx]
    return text


def _chunk_text(content) -> str:
    """Estrae il testo da un chunk di messaggio (str o lista di parti)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    return ""


async def get_graph(field_id: str):
    """Costruisce (e mette in cache) il grafo ReAct per un campo. Tool MCP +
    memory-tool con namespace dedicato; checkpointer e store condivisi."""
    if field_id in _graphs:
        return _graphs[field_id]

    namespace = ("agroagent", field_id, "memories")
    tools = list(await get_mcp_tools()) + [
        create_manage_memory_tool(namespace=namespace),
        create_search_memory_tool(namespace=namespace),
    ]
    system_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{field_id}", field_id)
    graph = create_react_agent(
        llm,
        tools,
        prompt=system_prompt,
        pre_model_hook=_summarization_node,
        state_schema=MemoryAgentState,
        checkpointer=_saver,
        store=_store,
    )
    _graphs[field_id] = graph
    return graph


def _run_config(session_id: str) -> dict:
    return {
        "configurable": {"thread_id": session_id},
        "recursion_limit": 2 * config.MAX_AGENT_ITERATIONS + 1,
    }


def _user_message(
    text: str, image: str | None = None, cell: dict | None = None
) -> HumanMessage:
    """Costruisce il messaggio dell'utente; se c'è una foto allegata produce un
    messaggio MULTIMODALE (testo + immagine) per il modello vision."""
    if not image:
        return HumanMessage(content=text)
    target = (
        f" La foto si riferisce alla cella ({cell['x']},{cell['y']}): "
        "riconosci la malattia della vite e applica la diagnosi su quella cella."
        if cell else ""
    )
    return HumanMessage(content=[
        {"type": "text", "text": text + target},
        {"type": "image_url", "image_url": {"url": image}},
    ])


async def run_agent(
    field_id: str, session_id: str, user_message: str,
    image: str | None = None, cell: dict | None = None,
) -> dict:
    """Esegue il loop ReAct (non-streaming). La history la fornisce il
    checkpointer in base al thread_id; qui si passa solo il nuovo messaggio."""
    graph = await get_graph(field_id)
    result = await graph.ainvoke(
        {"messages": [_user_message(user_message, image, cell)]},
        config=_run_config(session_id),
    )

    tool_calls = []
    reply = ""
    for message in result["messages"]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls or []:
                tool_calls.append(call["name"])
            if message.content:
                reply = (
                    message.content
                    if isinstance(message.content, str)
                    else " ".join(
                        part.get("text", "")
                        for part in message.content
                        if isinstance(part, dict)
                    )
                )
    reply = _THINK_RE.sub("", reply).strip()
    if not reply:
        reply = "(L'agente non ha prodotto una risposta testuale.)"
    return {"reply": reply, "tool_calls": tool_calls}


async def run_agent_stream(
    field_id: str, session_id: str, user_message: str,
    image: str | None = None, cell: dict | None = None,
) -> AsyncIterator[dict]:
    """Esegue il loop ReAct in streaming. Produce eventi:
      {"type": "token", "text": ...}   token visibili man mano
      {"type": "tool", "name": ...}    inizio chiamata a un tool
      {"type": "done", "reply": ..., "tool_calls": [...], "metrics": {...}}
    Le metriche includono TTFToken e TTFtool in millisecondi.
    """
    graph = await get_graph(field_id)

    start = time.perf_counter()
    ttft_ms: float | None = None
    ttftool_ms: float | None = None
    tool_calls: list[str] = []
    raw = ""
    emitted = ""
    tokens = 0  # chunk di testo visibili ≈ token in uscita

    try:
        async for event in graph.astream_events(
            {"messages": [_user_message(user_message, image, cell)]},
            version="v2",
            config=_run_config(session_id),
        ):
            kind = event["event"]
            if kind == "on_chat_model_stream":
                delta = _chunk_text(event["data"]["chunk"].content)
                if not delta:
                    continue
                if ttft_ms is None:
                    ttft_ms = round((time.perf_counter() - start) * 1000, 1)
                tokens += 1
                raw += delta
                visible = _visible_text(raw)
                if len(visible) > len(emitted):
                    yield {"type": "token", "text": visible[len(emitted):]}
                    emitted = visible
            elif kind == "on_tool_start":
                if ttftool_ms is None:
                    ttftool_ms = round((time.perf_counter() - start) * 1000, 1)
                tool_calls.append(event["name"])
                yield {"type": "tool", "name": event["name"]}
    except Exception as err:
        logger.exception("Streaming agente fallito")
        detail = f"{type(err).__name__}: {err}"
        if "context" in detail.lower() and "exceed" in detail.lower():
            detail = (
                "Finestra di contesto del modello esaurita. Riprova: la history "
                "viene riassunta automaticamente, ma il modello di test ha un "
                "contesto molto piccolo."
            )
        yield {"type": "error", "detail": detail}
        return

    total_ms = round((time.perf_counter() - start) * 1000, 1)
    reply = emitted.strip() or "(L'agente non ha prodotto una risposta testuale.)"
    tok_per_s = round(tokens / (total_ms / 1000), 1) if total_ms > 0 and tokens else None
    metrics = {
        "ttft_ms": ttft_ms,
        "ttftool_ms": ttftool_ms,
        "total_ms": total_ms,
        "tool_calls": len(tool_calls),
        "chars": len(reply),
        "output_tokens": tokens,
        "tok_per_s": tok_per_s,
    }
    logger.info(
        "agent_run field=%s ttft_ms=%s ttftool_ms=%s total_ms=%s tools=%d tokens=%d tok_per_s=%s",
        field_id, ttft_ms, ttftool_ms, total_ms, len(tool_calls), tokens, tok_per_s,
    )
    yield {"type": "done", "reply": reply, "tool_calls": tool_calls, "metrics": metrics}


async def history_messages(field_id: str, session_id: str) -> list[dict]:
    """Ricostruisce la cronologia chat dal checkpointer (per il frontend)."""
    graph = await get_graph(field_id)
    state = await graph.aget_state(_run_config(session_id))
    out = []
    for msg in state.values.get("messages", []):
        if isinstance(msg, HumanMessage):
            out.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage) and msg.content:
            text = _THINK_RE.sub(
                "", msg.content if isinstance(msg.content, str) else ""
            ).strip()
            if text:
                out.append({"role": "assistant", "content": text})
    return out
