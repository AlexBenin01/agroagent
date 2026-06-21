// Pannello inventario: stock prodotti + consegne in arrivo (ETA in ore simulate)
import { MCP_BASE } from "./config.js";

let fieldId = null;

export function initInventory(fid) {
  fieldId = fid;
  refreshInventory();
}

export async function refreshInventory() {
  if (!fieldId) return;
  const body = document.getElementById("inventory-body");
  try {
    const resp = await fetch(`${MCP_BASE}/api/fields/${fieldId}/inventory`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    render(await resp.json());
  } catch (err) {
    body.innerHTML = `<span class="muted">Inventario non disponibile: ${err.message}</span>`;
  }
}

function render(data) {
  const body = document.getElementById("inventory-body");
  let html = "<ul class='inventory-list'>";
  for (const p of data.products) {
    const tag = p.product_type === "biological" ? "🌿" : "⚗️";
    const stockClass = p.in_stock > 0 ? "in-stock" : "out-stock";
    html += `<li>
      <span class="inv-name">${tag} ${p.name}</span>
      <span class="inv-meta">eff. ${Math.round(p.efficacy * 100)}% · consegna ${p.delivery_min_h}-${p.delivery_max_h}h</span>
      <span class="inv-qty ${stockClass}">${p.in_stock} pz</span>
    </li>`;
  }
  html += "</ul>";

  if (data.pending_orders.length) {
    html += "<h3>🚚 In consegna</h3><ul class='inventory-list pending'>";
    for (const o of data.pending_orders) {
      html += `<li>
        <span class="inv-name">${o.product_name}</span>
        <span class="inv-qty">${o.quantity} pz · ETA ~${o.eta_hours}h</span>
      </li>`;
    }
    html += "</ul>";
  }
  body.innerHTML = html;
}
