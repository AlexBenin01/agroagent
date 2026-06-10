// Pannello chat: dialogo con l'agente, foto inline, link alle celle
import { AGENT_BASE, MCP_BASE } from "./config.js";
import { selectCell } from "./field_canvas.js";

let fieldId = null;
let sessionId = null;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function enrich(text) {
  let html = escapeHtml(text);
  // path/URL di foto simulate -> immagine inline
  html = html.replace(
    /(?:https?:\/\/[^\s"]+)?\/images\/([\w\-/]+\.(?:jpg|jpeg|png))/gi,
    (_m, rel) => `<img src="${MCP_BASE}/images/${rel}" alt="foto simulata">`,
  );
  // coordinate (x,y) -> link che seleziona la cella sul canvas
  html = html.replace(
    /\((\d),\s*(\d)\)/g,
    (_m, x, y) => `<span class="cell-link" data-x="${x}" data-y="${y}">(${x},${y})</span>`,
  );
  return html;
}

function addMessage(role, text, toolCalls = []) {
  const wrap = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = enrich(text);
  if (toolCalls.length) {
    const tools = document.createElement("span");
    tools.className = "tools-used";
    tools.textContent = `🔧 ${toolCalls.join(" → ")}`;
    div.appendChild(tools);
  }
  div.querySelectorAll(".cell-link").forEach((el) => {
    el.addEventListener("click", () => selectCell(+el.dataset.x, +el.dataset.y));
  });
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
}

async function send(message) {
  const typing = document.getElementById("chat-typing");
  const button = document.getElementById("chat-send");
  typing.classList.remove("hidden");
  button.disabled = true;
  try {
    const resp = await fetch(`${AGENT_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, field_id: fieldId, session_id: sessionId }),
    });
    const data = await resp.json();
    if (!resp.ok) {
      addMessage("agent", `⚠️ ${data.detail || "Errore dell'agente"}`);
      return;
    }
    sessionId = data.session_id;
    localStorage.setItem(`agroagent_session_${fieldId}`, sessionId);
    addMessage("agent", data.reply, data.tool_calls);
  } catch (err) {
    addMessage("agent", `⚠️ Agent service non raggiungibile: ${err.message}`);
  } finally {
    typing.classList.add("hidden");
    button.disabled = false;
  }
}

async function restoreHistory() {
  sessionId = localStorage.getItem(`agroagent_session_${fieldId}`);
  if (!sessionId) return;
  try {
    const resp = await fetch(`${AGENT_BASE}/chat/${sessionId}/history`);
    if (!resp.ok) { sessionId = null; return; }
    const data = await resp.json();
    for (const msg of data.messages) {
      addMessage(msg.role === "user" ? "user" : "agent", msg.content);
    }
  } catch {
    sessionId = null;
  }
}

export function initChat(fid) {
  fieldId = fid;
  restoreHistory();
  addMessage(
    "agent",
    "Ciao! Sono AgroAgent, il tuo agronomo AI. Posso ispezionare il vigneto, " +
    "diagnosticare malattie, avviare trattamenti e far avanzare il tempo simulato. " +
    "Prova: «com'è la situazione del campo?»",
  );

  document.getElementById("chat-form").addEventListener("submit", (evt) => {
    evt.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message) return;
    input.value = "";
    addMessage("user", message);
    send(message);
  });
}
