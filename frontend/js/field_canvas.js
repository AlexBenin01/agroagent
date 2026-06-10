// Rendering della griglia 10x10: stato celle, checkpoint, focus box animato
import { state, getCell, onChange } from "./state.js";

const STATUS_COLORS = {
  healthy: "#4CAF50",
  at_risk: "#FFC107",
  diseased: "#F44336",
  under_treatment: "#2196F3",
  treated: "#8BC34A",
};

let canvas, ctx, tooltip;
let hover = null; // {x, y} cella sotto il mouse
let onCellClick = null;

function cellSize() {
  return state.field ? canvas.width / state.field.cols : 60;
}

function cellFromMouse(evt) {
  const rect = canvas.getBoundingClientRect();
  const size = cellSize();
  const x = Math.floor((evt.clientX - rect.left) / size);
  const y = Math.floor((evt.clientY - rect.top) / size);
  if (!state.field) return null;
  if (x < 0 || y < 0 || x >= state.field.cols || y >= state.field.rows) return null;
  return { x, y };
}

function draw(timestamp) {
  requestAnimationFrame(draw);
  if (!state.field) return;
  const size = cellSize();
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (const cell of state.cells.values()) {
    const px = cell.x * size;
    const py = cell.y * size;
    let color = STATUS_COLORS[cell.status] || "#555";
    ctx.fillStyle = color;
    ctx.globalAlpha = cell.status === "under_treatment"
      ? 0.55 + 0.35 * Math.sin(timestamp / 300)  // blu pulsante
      : 1.0;
    ctx.fillRect(px + 1, py + 1, size - 2, size - 2);
    ctx.globalAlpha = 1.0;

    // barra salute in basso nella cella
    ctx.fillStyle = "rgba(0,0,0,0.45)";
    ctx.fillRect(px + 4, py + size - 9, size - 8, 5);
    ctx.fillStyle = "#fff";
    ctx.fillRect(px + 4, py + size - 9, (size - 8) * cell.health_score, 5);
  }

  // checkpoint
  ctx.font = `${Math.round(cellSize() * 0.32)}px serif`;
  for (const cp of state.checkpoints) {
    ctx.fillText("📍", cp.x * size + size - 22, cp.y * size + 20);
  }

  // cella selezionata
  if (state.selected) {
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 2;
    ctx.strokeRect(state.selected.x * size + 1.5, state.selected.y * size + 1.5, size - 3, size - 3);
  }

  // focus box dell'agente (bordo pulsante)
  const focus = state.field.focus;
  if (focus) {
    const pulse = 2 + 1.5 * (0.5 + 0.5 * Math.sin(timestamp / 250));
    ctx.strokeStyle = "#FF5722";
    ctx.lineWidth = pulse;
    ctx.strokeRect(focus.x * size + 2, focus.y * size + 2, size - 4, size - 4);
  }
}

function showTooltip(evt, cellPos) {
  const cell = getCell(cellPos.x, cellPos.y);
  if (!cell) return;
  tooltip.innerHTML =
    `<strong>Cella (${cell.x},${cell.y})</strong> — ${cell.status}<br>` +
    `salute: ${(cell.health_score * 100).toFixed(0)}% · rischio: ${(cell.disease_risk_score * 100).toFixed(0)}%<br>` +
    `umidità suolo: ${(cell.soil_moisture * 100).toFixed(0)}% · ${cell.soil_temperature.toFixed(1)}°C` +
    (cell.active_disease ? `<br>🦠 ${cell.active_disease}` : "");
  tooltip.classList.remove("hidden");
  const rect = canvas.getBoundingClientRect();
  tooltip.style.left = `${evt.clientX - rect.left + 14}px`;
  tooltip.style.top = `${evt.clientY - rect.top + 14}px`;
}

export function selectCell(x, y) {
  state.selected = { x, y };
  if (onCellClick) onCellClick(x, y);
}

export function initCanvas(clickHandler) {
  onCellClick = clickHandler;
  canvas = document.getElementById("field-canvas");
  ctx = canvas.getContext("2d");
  tooltip = document.getElementById("cell-tooltip");

  canvas.addEventListener("mousemove", (evt) => {
    hover = cellFromMouse(evt);
    if (hover) showTooltip(evt, hover);
    else tooltip.classList.add("hidden");
  });
  canvas.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
  canvas.addEventListener("click", (evt) => {
    const pos = cellFromMouse(evt);
    if (pos) selectCell(pos.x, pos.y);
  });

  onChange(() => {}); // il render è continuo via rAF
  requestAnimationFrame(draw);
}
