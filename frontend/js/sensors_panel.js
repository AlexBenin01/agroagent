// Pannello sensori della cella selezionata (o del focus agente)
import { MCP_BASE } from "./config.js";
import { state, getCell, onChange } from "./state.js";

function gauge(label, value, color, text) {
  return `
    <div class="gauge">${label}: <strong>${text}</strong>
      <div class="bar"><div class="fill" style="width:${Math.round(value * 100)}%;background:${color}"></div></div>
    </div>`;
}

function simHoursLeft(endsAtSim) {
  if (!state.field?.sim_time) return null;
  const ms = new Date(endsAtSim) - new Date(state.field.sim_time);
  return Math.max(0, Math.round(ms / 3600000));
}

function render() {
  const body = document.getElementById("sensors-body");
  const label = document.getElementById("sensors-cell-label");
  const sel = state.selected;
  if (!sel) { label.textContent = ""; return; }
  const cell = getCell(sel.x, sel.y);
  if (!cell) return;

  label.textContent = `— cella (${cell.x},${cell.y})`;

  const healthColor = cell.health_score > 0.7 ? "#4CAF50" : cell.health_score > 0.4 ? "#FFC107" : "#F44336";
  let html = "";
  html += gauge("💧 Umidità suolo", cell.soil_moisture, "#42A5F5", `${(cell.soil_moisture * 100).toFixed(0)}%`);
  html += `<div class="gauge">🌡 Temperatura suolo: <strong>${cell.soil_temperature.toFixed(1)}°C</strong></div>`;
  html += gauge("🌱 Salute", cell.health_score, healthColor, `${(cell.health_score * 100).toFixed(0)}%`);
  html += gauge("⚠️ Rischio malattia", cell.disease_risk_score, "#FF7043", `${(cell.disease_risk_score * 100).toFixed(0)}%`);
  html += `<div class="gauge">🧪 Nutrienti: <strong>${(cell.nutrient_index * 100).toFixed(0)}%</strong> · stato: <strong>${cell.status}</strong></div>`;

  if (cell.active_disease) {
    html += `<div class="gauge">🦠 <strong>${cell.active_disease}</strong><span class="badge">malattia attiva</span></div>`;
  }

  const tasks = state.tasks.filter((t) => t.x === cell.x && t.y === cell.y);
  for (const t of tasks) {
    const left = simHoursLeft(t.ends_at_sim);
    html += `<div class="task-row">⏳ ${t.task_type} in corso — restano <strong>${left}h simulate</strong>
      (fine: ${new Date(t.ends_at_sim).toLocaleString("it-IT")})</div>`;
  }

  const cps = state.checkpoints.filter((c) => c.x === cell.x && c.y === cell.y);
  for (const c of cps) {
    html += `<div class="cp-row">📍 <em>${c.type}</em>: ${c.note || ""}</div>`;
  }

  if (cell.last_photo_path) {
    html += `<img class="sensor-photo" src="${MCP_BASE}/images/${cell.last_photo_path}"
             alt="ultima foto cella (${cell.x},${cell.y})">`;
  }

  body.innerHTML = html;
  body.classList.remove("muted");
}

export function initSensorsPanel() {
  onChange(render);
}
