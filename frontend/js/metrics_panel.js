// Pannello osservabilità LLM: latenza e throughput dell'agente per turno.
// Alimentato da chat.js (evento "done" dello stream): TTFToken, TTFtool,
// durata totale, token/s, n. tool. Tiene lo storico degli ultimi turni.
const MAX = 20;
let history = [];

function fmtMs(v) {
  if (v == null) return "—";
  return v >= 1000 ? `${(v / 1000).toFixed(1)}s` : `${Math.round(v)}ms`;
}

function avg(key) {
  const xs = history.map((h) => h[key]).filter((v) => v != null);
  return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
}

function render() {
  const body = document.getElementById("metrics-body");
  if (!body) return;
  if (!history.length) {
    body.innerHTML = '<span class="muted">Invia un messaggio per vedere le metriche…</span>';
    return;
  }
  const last = history[history.length - 1];
  const max = Math.max(...history.map((h) => h.total_ms || 0)) || 1;
  const bars = history
    .map((h) => {
      const px = Math.max(3, Math.round(((h.total_ms || 0) / max) * 28));
      return `<span class="mbar" style="height:${px}px" title="${fmtMs(h.total_ms)}"></span>`;
    })
    .join("");

  body.innerHTML = `
    <div class="metric-grid">
      <div><span class="mlabel" title="Time to first token">TTFToken</span><span class="mval">${fmtMs(last.ttft_ms)}</span></div>
      <div><span class="mlabel" title="Time to first tool call">TTFtool</span><span class="mval">${fmtMs(last.ttftool_ms)}</span></div>
      <div><span class="mlabel">Totale</span><span class="mval">${fmtMs(last.total_ms)}</span></div>
      <div><span class="mlabel">Token/s</span><span class="mval">${last.tok_per_s ?? "—"}</span></div>
      <div><span class="mlabel">Tool</span><span class="mval">${last.tool_calls ?? 0}</span></div>
      <div><span class="mlabel">Token out</span><span class="mval">${last.output_tokens ?? 0}</span></div>
    </div>
    <div class="metric-hist">
      <div class="mbars">${bars}</div>
      <span class="muted">durata ultimi ${history.length} turni</span>
    </div>
    <div class="muted metric-avg">Medie: TTFT ${fmtMs(avg("ttft_ms"))} · totale ${fmtMs(avg("total_ms"))} · ${
      avg("tok_per_s") != null ? avg("tok_per_s").toFixed(1) : "—"
    } tok/s</div>`;
}

export function recordMetrics(m) {
  if (!m) return;
  history.push(m);
  if (history.length > MAX) history.shift();
  render();
}

export function initMetricsPanel() {
  render();
}
