// Timeline degli ultimi eventi del campo
import { MCP_BASE } from "./config.js";
import { selectCell } from "./field_canvas.js";

const ICONS = {
  rain: "🌧️",
  disease_detected: "🦠",
  treatment_started: "💊",
  treatment_completed: "✅",
  checkpoint: "📍",
  inspection: "🔍",
  time_advance: "⏭️",
  field_created: "🌿",
};

let fieldId = null;
let pending = false;

export async function refreshTimeline() {
  if (!fieldId || pending) return;
  pending = true;
  try {
    const resp = await fetch(`${MCP_BASE}/api/fields/${fieldId}/events?limit=20`);
    const events = await resp.json();
    const list = document.getElementById("timeline-list");
    list.innerHTML = "";
    for (const ev of events) {
      const li = document.createElement("li");
      const icon = ICONS[ev.event_type] || "•";
      const time = new Date(ev.sim_time).toLocaleString("it-IT", {
        day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
      });
      li.innerHTML = `<span class="ev-time">${time}</span>${icon} ${ev.description}`;
      if (ev.x !== null && ev.y !== null) {
        li.title = `Vai alla cella (${ev.x},${ev.y})`;
        li.addEventListener("click", () => selectCell(ev.x, ev.y));
      }
      list.appendChild(li);
    }
  } finally {
    pending = false;
  }
}

export function initTimeline(fid) {
  fieldId = fid;
  refreshTimeline();
}
