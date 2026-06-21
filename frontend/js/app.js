// Bootstrap dell'app: schermata modalità, poi canvas, SSE, chat, timeline, inventario
import { MCP_BASE } from "./config.js";
import { state, applyFullState, onChange, notify } from "./state.js";
import { initCanvas } from "./field_canvas.js";
import { initSSE } from "./sse_client.js";
import { initSensorsPanel } from "./sensors_panel.js";
import { initTimeline, refreshTimeline } from "./timeline.js";
import { initChat } from "./chat.js";
import { initInventory, refreshInventory } from "./inventory_panel.js";
import { initMetricsPanel } from "./metrics_panel.js";

const DIFFICULTY_LABELS = {
  normal: "🌱 Normale",
  hard: "🔥 Difficile",
  apocalypse: "☠️ Apocalisse",
};

function renderHeader() {
  if (!state.field) return;
  const simTime = new Date(state.field.sim_time).toLocaleString("it-IT", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
  });
  document.getElementById("sim-time").textContent = `⏱ ${simTime} (sim)`;

  const badge = document.getElementById("difficulty-badge");
  if (badge) badge.textContent = DIFFICULTY_LABELS[state.field.difficulty] || "";

  highlightSpeed(state.field.time_speed);

  const w = state.weather?.current;
  if (w) {
    const icon = w.rainfall_mm > 0.5 ? "🌧️" : "☀️";
    document.getElementById("weather-now").textContent =
      `${icon} ${w.temp_min.toFixed(0)}–${w.temp_max.toFixed(0)}°C · ` +
      `${w.humidity_pct.toFixed(0)}% UR · ${w.rainfall_mm.toFixed(1)}mm`;
  }
}

function highlightSpeed(speed) {
  document.querySelectorAll("#speed-controls button").forEach((btn) => {
    btn.classList.toggle("active", Number(btn.dataset.speed) === speed);
  });
}

function initSpeedControls(fieldId) {
  document.querySelectorAll("#speed-controls button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const speed = Number(btn.dataset.speed);
      highlightSpeed(speed);
      try {
        await fetch(`${MCP_BASE}/api/fields/${fieldId}/speed`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ speed }),
        });
        if (state.field) state.field.time_speed = speed;
      } catch (err) {
        console.error("set speed", err);
      }
    });
  });
}

async function fetchFullState(fieldId) {
  const resp = await fetch(`${MCP_BASE}/api/fields/${fieldId}`);
  if (!resp.ok) throw new Error(`stato campo: HTTP ${resp.status}`);
  applyFullState(await resp.json());
}

async function startGame(fieldId) {
  document.getElementById("start-screen").classList.add("hidden");

  initCanvas(() => notify());          // click cella -> re-render pannelli
  initSensorsPanel();
  initInventory(fieldId);
  initMetricsPanel();
  onChange(renderHeader);
  initSpeedControls(fieldId);

  await fetchFullState(fieldId);
  state.selected = { x: state.field.focus.x, y: state.field.focus.y };
  notify();

  initTimeline(fieldId);
  initChat(fieldId);
  initSSE(fieldId, {
    refetch: () => fetchFullState(fieldId).catch(console.error),
    timelineDirty: refreshTimeline,
    inventoryDirty: refreshInventory,
  });
}

async function createField(difficulty) {
  const names = { normal: "Vigneto Normale", hard: "Vigneto Difficile", apocalypse: "Vigneto Apocalisse" };
  const resp = await fetch(`${MCP_BASE}/api/fields`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: names[difficulty] || "Nuovo Vigneto", difficulty }),
  });
  if (!resp.ok) throw new Error(`creazione campo: HTTP ${resp.status}`);
  return (await resp.json()).id;
}

function showStartScreen(existingFields) {
  const screen = document.getElementById("start-screen");
  screen.classList.remove("hidden");

  document.querySelectorAll(".mode-btn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      try {
        const fieldId = await createField(btn.dataset.difficulty);
        startGame(fieldId);
      } catch (err) {
        btn.disabled = false;
        console.error(err);
      }
    });
  });

  const container = document.getElementById("existing-fields");
  if (existingFields.length) {
    container.innerHTML = "<h2>Riprendi un campo</h2>";
    for (const f of existingFields) {
      const b = document.createElement("button");
      b.className = "field-resume";
      b.textContent = `${f.name} · ${DIFFICULTY_LABELS[f.difficulty] || f.difficulty}`;
      b.addEventListener("click", () => startGame(f.id));
      container.appendChild(b);
    }
  }
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
  showStartScreen(fields);
}

main();
