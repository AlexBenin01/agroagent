// EventSource -> aggiornamento stato. Alla (ri)connessione rifà il fetch
// completo dello stato: più robusto che gestire Last-Event-ID.
import { MCP_BASE } from "./config.js";
import { state, mergeCells, notify } from "./state.js";

let refetchFullState = null;
let onTimelineDirty = null;
let onInventoryDirty = null;

function setStatus(connected) {
  const dot = document.getElementById("sse-status");
  dot.classList.toggle("on", connected);
  dot.classList.toggle("off", !connected);
}

export function initSSE(fieldId, { refetch, timelineDirty, inventoryDirty }) {
  refetchFullState = refetch;
  onTimelineDirty = timelineDirty;
  onInventoryDirty = inventoryDirty || (() => {});

  const source = new EventSource(`${MCP_BASE}/events/${fieldId}`);

  source.onopen = () => {
    setStatus(true);
    refetchFullState();
    onTimelineDirty();
    onInventoryDirty();
  };
  source.onerror = () => setStatus(false); // EventSource riconnette da solo

  source.addEventListener("field_update", (evt) => {
    const data = JSON.parse(evt.data);
    mergeCells(data.cells, data.sim_time);
  });

  source.addEventListener("focus_moved", (evt) => {
    const data = JSON.parse(evt.data);
    if (state.field) {
      state.field.focus = { x: data.x, y: data.y };
      notify();
    }
  });

  source.addEventListener("checkpoint_created", (evt) => {
    const data = JSON.parse(evt.data);
    state.checkpoints.push(data);
    notify();
    onTimelineDirty();
  });

  source.addEventListener("task_started", () => {
    refetchFullState();
    onTimelineDirty();
  });

  source.addEventListener("task_completed", () => {
    refetchFullState();
    onTimelineDirty();
  });

  source.addEventListener("time_advanced", (evt) => {
    const data = JSON.parse(evt.data);
    if (state.field) state.field.sim_time = data.new_sim_time;
    refetchFullState(); // meteo/task/checkpoint possono essere cambiati
    onTimelineDirty();
    onInventoryDirty(); // le consegne maturano avanzando il tempo
  });

  source.addEventListener("product_ordered", () => {
    onInventoryDirty();
    onTimelineDirty();
  });

  source.addEventListener("product_delivered", () => {
    onInventoryDirty();
    onTimelineDirty();
  });

  source.addEventListener("speed_changed", (evt) => {
    const data = JSON.parse(evt.data);
    if (state.field) {
      state.field.time_speed = data.time_speed;
      notify();
    }
  });
}
