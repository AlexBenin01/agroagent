// Stato condiviso del client + mini event-bus per i re-render
export const state = {
  field: null,          // {id, name, rows, cols, sim_time, focus:{x,y}}
  cells: new Map(),     // "x,y" -> cell
  checkpoints: [],
  tasks: [],
  weather: null,
  selected: null,       // {x, y} cella selezionata dall'utente
};

const listeners = new Set();

export function onChange(fn) { listeners.add(fn); }

export function notify() { listeners.forEach((fn) => fn()); }

export function cellKey(x, y) { return `${x},${y}`; }

export function getCell(x, y) { return state.cells.get(cellKey(x, y)); }

export function applyFullState(payload) {
  state.field = payload.field;
  state.cells = new Map(payload.cells.map((c) => [cellKey(c.x, c.y), c]));
  state.checkpoints = payload.open_checkpoints || [];
  state.tasks = payload.active_tasks || [];
  state.weather = payload.weather || null;
  notify();
}

export function mergeCells(cells, simTime) {
  for (const c of cells) state.cells.set(cellKey(c.x, c.y), c);
  if (simTime && state.field) state.field.sim_time = simTime;
  notify();
}
