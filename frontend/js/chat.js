// Pannello chat: dialogo con l'agente in streaming (token-by-token), foto inline,
// upload di foto reali per la diagnosi (multimodale), link alle celle, metriche.
import { AGENT_BASE, MCP_BASE } from "./config.js";
import { state } from "./state.js";
import { selectCell } from "./field_canvas.js";
import { recordMetrics } from "./metrics_panel.js";

let fieldId = null;
let sessionId = null;
let attachedImage = null; // data URL della foto allegata (già ridimensionata)

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function enrich(text) {
  let html = escapeHtml(text);
  // path/URL di foto (dataset /images o caricate /uploads) -> immagine inline
  html = html.replace(
    /(?:https?:\/\/[^\s"]+)?(\/(?:images|uploads)\/[\w\-/]+\.(?:jpg|jpeg|png))/gi,
    (_m, path) => `<img src="${MCP_BASE}${path}" alt="foto">`,
  );
  // coordinate (x,y) -> link che seleziona la cella sul canvas
  html = html.replace(
    /\((\d),\s*(\d)\)/g,
    (_m, x, y) => `<span class="cell-link" data-x="${x}" data-y="${y}">(${x},${y})</span>`,
  );
  return html;
}

function attachCellLinks(div) {
  div.querySelectorAll(".cell-link").forEach((el) => {
    el.addEventListener("click", () => selectCell(+el.dataset.x, +el.dataset.y));
  });
}

function addMessage(role, text, toolCalls = [], imageUrl = null) {
  const wrap = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.innerHTML = enrich(text);
  if (imageUrl) {
    const img = document.createElement("img");
    img.src = imageUrl;
    img.className = "msg-photo";
    div.appendChild(img);
  }
  if (toolCalls.length) {
    const tools = document.createElement("span");
    tools.className = "tools-used";
    tools.textContent = `🔧 ${toolCalls.join(" → ")}`;
    div.appendChild(tools);
  }
  attachCellLinks(div);
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
  return div;
}

function streamingBubble() {
  const wrap = document.getElementById("chat-messages");
  const div = document.createElement("div");
  div.className = "msg agent streaming";
  const textEl = document.createElement("span");
  textEl.className = "msg-text";
  const toolsEl = document.createElement("span");
  toolsEl.className = "tools-used hidden";
  const metricsEl = document.createElement("span");
  metricsEl.className = "msg-metrics hidden";
  div.append(textEl, toolsEl, metricsEl);
  wrap.appendChild(div);

  const tools = [];
  return {
    setText(text) {
      textEl.innerHTML = enrich(text);
      wrap.scrollTop = wrap.scrollHeight;
    },
    addTool(name) {
      tools.push(name);
      toolsEl.classList.remove("hidden");
      toolsEl.textContent = `🔧 ${tools.join(" → ")}`;
    },
    finalize(text, metrics) {
      div.classList.remove("streaming");
      textEl.innerHTML = enrich(text);
      attachCellLinks(div);
      if (metrics && metrics.ttft_ms != null) {
        metricsEl.classList.remove("hidden");
        const ttftool = metrics.ttftool_ms != null ? ` · TTFtool ${Math.round(metrics.ttftool_ms)}ms` : "";
        metricsEl.textContent = `⏱ TTFT ${Math.round(metrics.ttft_ms)}ms${ttftool} · tot ${Math.round(metrics.total_ms)}ms`;
      }
      wrap.scrollTop = wrap.scrollHeight;
    },
    error(detail) {
      div.classList.remove("streaming");
      textEl.innerHTML = `⚠️ ${escapeHtml(detail)}`;
    },
  };
}

async function* sseStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const block = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (data) yield { event, data: JSON.parse(data) };
    }
  }
}

// Ridimensiona un file immagine a lato max 1024px e lo codifica in JPEG base64.
function resizeImage(file, maxSide = 1024) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const scale = Math.min(1, maxSide / Math.max(img.width, img.height));
      const w = Math.round(img.width * scale);
      const h = Math.round(img.height * scale);
      const canvas = document.createElement("canvas");
      canvas.width = w; canvas.height = h;
      canvas.getContext("2d").drawImage(img, 0, 0, w, h);
      resolve(canvas.toDataURL("image/jpeg", 0.85));
      URL.revokeObjectURL(img.src);
    };
    img.onerror = reject;
    img.src = URL.createObjectURL(file);
  });
}

function dataUrlToBlob(dataUrl) {
  const [head, b64] = dataUrl.split(",");
  const mime = head.match(/:(.*?);/)[1];
  const bin = atob(b64);
  const arr = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

function showPreview(dataUrl, name) {
  document.getElementById("photo-preview-img").src = dataUrl;
  document.getElementById("photo-preview-name").textContent = name;
  document.getElementById("photo-preview").classList.remove("hidden");
}

function clearPhoto() {
  attachedImage = null;
  document.getElementById("photo-input").value = "";
  document.getElementById("photo-preview").classList.add("hidden");
}

async function send(message) {
  const typing = document.getElementById("chat-typing");
  const button = document.getElementById("chat-send");

  const image = attachedImage;
  const cell = image ? state.selected : null;
  if (image && !cell) {
    addMessage("agent", "⚠️ Seleziona prima una cella sulla mappa a cui associare la foto.");
    return;
  }

  typing.classList.remove("hidden");
  button.disabled = true;

  // upload durevole della foto sulla cella (non blocca la chat se fallisce)
  if (image && cell) {
    try {
      const blob = dataUrlToBlob(image);
      const fd = new FormData();
      fd.append("file", blob, "foto.jpg");
      await fetch(`${MCP_BASE}/api/fields/${fieldId}/cells/${cell.x}/${cell.y}/photo`, {
        method: "POST", body: fd,
      });
    } catch (err) {
      console.error("upload foto", err);
    }
  }

  const bubble = streamingBubble();
  let acc = "";
  let firstToken = true;
  try {
    const resp = await fetch(`${AGENT_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message, field_id: fieldId, session_id: sessionId,
        image, cell: cell ? { x: cell.x, y: cell.y } : null,
      }),
    });
    if (!resp.ok || !resp.body) {
      let detail = `Errore dell'agente (HTTP ${resp.status})`;
      try { detail = (await resp.json()).detail || detail; } catch { /* corpo non JSON */ }
      bubble.error(detail);
      return;
    }
    for await (const { event, data } of sseStream(resp)) {
      if (event === "session") {
        sessionId = data.session_id;
        localStorage.setItem(`agroagent_session_${fieldId}`, sessionId);
      } else if (event === "token") {
        if (firstToken) { typing.classList.add("hidden"); firstToken = false; }
        acc += data.text;
        bubble.setText(acc);
      } else if (event === "tool") {
        bubble.addTool(data.name);
      } else if (event === "done") {
        bubble.finalize(data.reply, data.metrics);
        recordMetrics(data.metrics);
      } else if (event === "error") {
        bubble.error(data.detail || "Errore dell'agente");
      }
    }
  } catch (err) {
    bubble.error(`Agent service non raggiungibile: ${err.message}`);
  } finally {
    typing.classList.add("hidden");
    button.disabled = false;
    clearPhoto();
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
    "diagnosticare malattie (anche da una foto che carichi con 📷), ordinare prodotti, " +
    "avviare trattamenti e far avanzare il tempo simulato. Prova: «com'è la situazione del campo?»",
  );

  document.getElementById("photo-input").addEventListener("change", async (evt) => {
    const file = evt.target.files[0];
    if (!file) return;
    try {
      attachedImage = await resizeImage(file);
      showPreview(attachedImage, file.name);
    } catch {
      addMessage("agent", "⚠️ Impossibile leggere l'immagine selezionata.");
      clearPhoto();
    }
  });
  document.getElementById("photo-remove").addEventListener("click", clearPhoto);

  document.getElementById("chat-form").addEventListener("submit", (evt) => {
    evt.preventDefault();
    const input = document.getElementById("chat-input");
    const message = input.value.trim();
    if (!message && !attachedImage) return;
    const text = message || "Che malattia è? Diagnostica dalla foto.";
    input.value = "";
    addMessage("user", text, [], attachedImage);
    send(text);
  });
}
