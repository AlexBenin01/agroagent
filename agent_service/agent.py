"""Agente LangGraph ReAct collegato ai tool MCP."""
import logging
import re
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

import config
from mcp_client import get_mcp_tools

logger = logging.getLogger("agent")

SYSTEM_PROMPT_TEMPLATE = (
    Path(__file__).parent / "prompts" / "system_prompt.txt"
).read_text(encoding="utf-8")

llm = ChatOpenAI(
    base_url=config.OPENAI_BASE_URL,
    api_key=config.OPENAI_API_KEY,
    model=config.LLM_MODEL,
    temperature=0.2,
    timeout=config.LLM_TIMEOUT_SECONDS,
)


def _to_langchain_messages(history: list[dict]) -> list:
    out = []
    for msg in history:
        if msg.get("role") == "user":
            out.append(HumanMessage(content=msg["content"]))
        elif msg.get("role") == "assistant":
            out.append(AIMessage(content=msg["content"]))
    return out


async def run_agent(field_id: str, history: list[dict], user_message: str) -> dict:
    """Esegue il loop ReAct. Restituisce la risposta finale e i tool invocati."""
    tools = await get_mcp_tools()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{field_id}", field_id)
    graph = create_react_agent(llm, tools, prompt=system_prompt)

    messages = _to_langchain_messages(history) + [HumanMessage(content=user_message)]
    result = await graph.ainvoke(
        {"messages": messages},
        # ogni iterazione ReAct = nodo agente + nodo tool
        config={"recursion_limit": 2 * config.MAX_AGENT_ITERATIONS + 1},
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
    # i modelli "thinking" (es. Qwen3) possono emettere blocchi <think>…</think>
    reply = re.sub(r"<think>.*?</think>", "", reply, flags=re.DOTALL).strip()
    if not reply:
        reply = "(L'agente non ha prodotto una risposta testuale.)"
    return {"reply": reply, "tool_calls": tool_calls}
