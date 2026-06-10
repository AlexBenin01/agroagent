// Bootstrap dell'app: carica il campo, avvia canvas, SSE, chat, timeline
import { MCP_BASE } from "./config.js";
import { state, applyFullState, onChange, notify } from "./state.js";
import { initCanvas } from "./field_canvas.js";
import { initSSE } from "./sse_client.js";
import { initSensorsPanel } from "./sensors_panel.js";
import { initTimeline, refreshTimeline } from "./timeline.js";
import { initChat } from "./chat.js";

function renderHeader() {
  if (!state.field) return;
  const simTime = new Date(state.field.sim_time).toLocaleString("it-IT", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
  document.getElementById("sim-time").textContent = `⏱ ${simTime} (sim)`;
  const w = state.weather?.current;
  if (w) {
    const icon = w.rainfall_mm > 0.5 ? "🌧️" : "☀️";
    document.getElementById("weather-now").textContent =
      `${icon} ${w.temp_min.toFixed(0)}–${w.temp_max.toFixed(0)}°C · ` +
      `${w.humidity_pct.toFixed(0)}% UR · ${w.rainfall_mm.toFixed(1)}mm`;
  }
}

async function fetchFullState(fieldId) {
  const resp = await fetch(`${MCP_BASE}/api/fields/${fieldId}`);
  if (!resp.ok) throw new Error(`stato campo: HTTP ${resp.status}`);
  applyFullState(await resp.json());
}

async function main() {
  let fields;
  try {
    fields = await (await fetch(`${MCP_BASE}/api/fields`)).json();
  } catch (err) {
    document.body.insertAdjacentHTML(
      "afterbegin",
      `<div style="background:#5c2120;padding:10px 16px">⚠️ MCP Server non
       raggiungibile su ${MCP_BASE} — avvia lo stack con <code>docker compose up</code></div>`,
    );
    throw err;
  }
  if (!fields.length) {
    const resp = await fetch(`${MCP_BASE}/api/fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Vigneto Demo" }),
    });
    fields = [await resp.json()];
  }
  const fieldId = fields[0].id;

  initCanvas(() => notify());          // click cella -> re-render pannelli
  initSensorsPanel();
  onChange(renderHeader);

  await fetchFullState(fieldId);
  state.selected = { x: state.field.focus.x, y: state.field.focus.y };
  notify();

  initTimeline(fieldId);
  initChat(fieldId);
  initSSE(fieldId, {
    refetch: () => fetchFullState(fieldId).catch(console.error),
    timelineDirty: refreshTimeline,
  });
}

main();
