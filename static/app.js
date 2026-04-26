// Trading Signal Admin Dashboard
const API = "/api";
let currentPage = "dashboard";
let refreshTimer = null;

// ── Navigation ──
document.querySelectorAll(".nav-item").forEach(el => {
  el.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(e => e.classList.remove("active"));
    el.classList.add("active");
    const page = el.dataset.page;
    showPage(page);
  });
});

function showPage(page) {
  document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
  const target = document.getElementById("page-" + page);
  if (target) { target.classList.add("active"); currentPage = page; }
  if (page === "dashboard") loadDashboard();
  if (page === "users") loadUsers();
  if (page === "alerts") loadAlerts();
  if (page === "markets") loadMarkets();
}

// ── API helpers ──
async function get(path) { const r = await fetch(API + path); return r.json(); }
async function post(path, data) { const r = await fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }); return r.json(); }
async function del(path) { const r = await fetch(API + path, { method: "DELETE" }); return r.json(); }
async function patch(path, data) { const r = await fetch(API + path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) }); return r.json(); }

function fmt(n) { return n ? new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(n) : "—"; }

// ── Toast ──
function toast(msg, type = "success") {
  const t = document.createElement("div");
  t.className = "toast " + type; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
}

// ── DASHBOARD ──
async function loadDashboard() {
  try {
    const status = await get("/status");
    document.getElementById("stat-users").textContent = status.total_users || 0;
    document.getElementById("stat-active").textContent = status.active_users || 0;
    document.getElementById("stat-alerts").textContent = status.total_alerts || 0;

    // Price chart
    const symbol = "CFI:US100";
    try {
      const priceResp = await post("/chart-data", { symbol, timeframe: "1D", bars: 30 });
      if (priceResp && priceResp.length > 5) {
        drawChart("priceChart", priceResp.reverse(), symbol);
        const last = priceResp[priceResp.length - 1];
        document.getElementById("ticker-price").textContent = fmt(last.close);
        const prev = priceResp[priceResp.length - 2];
        const chg = prev ? ((last.close - prev.close) / prev.close * 100) : 0;
        document.getElementById("ticker-change").textContent = (chg > 0 ? "+" : "") + chg.toFixed(2) + "%";
        document.getElementById("ticker-change").className = chg >= 0 ? "ticker-change up" : "ticker-change down";
      }
    } catch (e) { /* chart may fail on closed market */ }

    // Recent alerts
    const alerts = await get("/alerts?limit=10");
    const tbody = document.getElementById("dash-alerts");
    tbody.innerHTML = alerts.map(a => `
      <tr>
        <td style="font-size:11px">${(a.sent_at || "").slice(5, 19).replace("T", " ")}</td>
        <td>${a.telegram_name || "—"}</td>
        <td><span class="tag ${a.direction==='LONG'?'tag-buy':'tag-sell'}">${a.direction}</span></td>
        <td><span class="tag ${a.strategy==='SMC'?'tag-smc':'tag-scalp'}">${a.strategy || 'scalp'}</span></td>
        <td>${a.setup}</td>
        <td><code>${a.symbol}</code></td>
        <td>${fmt(a.entry)}</td>
        <td>${fmt(a.sl)} / ${fmt(a.tp)}</td>
        <td>${Math.round((a.confidence||0)*100)}%</td>
      </tr>`).join("") || '<tr><td colspan="9" style="text-align:center;color:var(--text2)">No alerts yet</td></tr>';
  } catch (e) { console.error(e); }
}

function drawChart(canvasId, data, symbol) {
  const ctx = document.getElementById(canvasId)?.getContext("2d");
  if (!ctx) return;
  // destroy old chart if exists
  if (window._chart) window._chart.destroy();
  const labels = data.map(d => new Date(d.time * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" }));
  const closes = data.map(d => d.close);
  const isUp = closes[closes.length - 1] >= closes[0];
  const color = isUp ? "#0ecb81" : "#f6465d";

  window._chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: symbol,
        data: closes,
        borderColor: color,
        backgroundColor: color + "15",
        fill: true,
        tension: 0.3,
        pointRadius: 0,
        borderWidth: 2,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#848e9c", font: { size: 10 } } },
        y: { grid: { color: "rgba(255,255,255,0.04)" }, ticks: { color: "#848e9c", font: { size: 10 }, callback: v => fmt(v) } },
      },
      interaction: { intersect: false, mode: "index" },
    },
  });
}

// ── USERS ──
async function loadUsers() {
  const users = await get("/users");
  const tbody = document.getElementById("users-tbody");
  tbody.innerHTML = users.map(u => `
    <tr>
      <td><code>${u.chat_id}</code></td>
      <td><strong>${u.telegram_name || u.first_name || "—"}</strong></td>
      <td>${u.phone || "—"}</td>
      <td>${(u.symbols || []).map(s => `<span class="symbol-chip">${s.symbol}</span>`).join("") || '<span style="color:var(--text2)">—</span>'}</td>
      <td>${u.alerts_received || 0}</td>
      <td>${u.active ? '<span class="badge-active">Active</span>' : '<span class="badge-paused">Paused</span>'}</td>
      <td>
        <button class="btn btn-sm btn-primary" onclick="openUserModal(${u.chat_id},'${u.telegram_name||''}')">⚙</button>
        <button class="btn btn-sm ${u.active?'btn-ghost':'btn-success'}" onclick="toggleUser(${u.chat_id},${!u.active})">${u.active?'Pause':'Start'}</button>
        <button class="btn btn-sm btn-danger" onclick="deleteUser(${u.chat_id})">×</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="7" style="text-align:center;color:var(--text2)">No users</td></tr>';
}

async function addUserQuick() {
  const chatId = document.getElementById("quick-add-chatid").value;
  const name = document.getElementById("quick-add-name").value;
  if (!chatId) return toast("Enter Chat ID", "error");
  await post("/users", { chat_id: parseInt(chatId), first_name: name });
  toast("User added");
  loadUsers();
}

async function toggleUser(chatId, active) {
  await patch("/users/" + chatId, { active });
  toast(active ? "User activated" : "User paused");
  loadUsers();
}

async function deleteUser(chatId) {
  if (!confirm("Delete user " + chatId + " and all their data?")) return;
  await del("/users/" + chatId);
  toast("User deleted");
  loadUsers();
}

// ── User Modal ──
let userModalId = null;

async function openUserModal(chatId, name) {
  userModalId = chatId;
  document.getElementById("modal-user-title").textContent = "Manage: " + (name || chatId);
  const u = await get("/users/" + chatId);
  if (!u) return;
  document.getElementById("modal-phone").value = u.phone || "";
  // Load symbols
  const syms = await get("/users/" + chatId + "/symbols");
  document.getElementById("modal-symbols").innerHTML = syms.map(s =>
    `<span class="symbol-chip">${s.symbol}<button onclick="removeSymbol('${chatId}','${s.symbol}')">×</button></span>`
  ).join("") || '<span style="color:var(--text2);font-size:12px">No markets assigned</span>';
  document.getElementById("userModal").classList.add("show");
}

function closeUserModal() { document.getElementById("userModal").classList.remove("show"); }

async function addSymbolToUser() {
  const sym = document.getElementById("modal-new-symbol").value.trim();
  if (!sym) return;
  await post("/users/" + userModalId + "/symbols", { symbol: sym, symbol_name: sym });
  toast("Market added");
  openUserModal(userModalId, "");
}

async function removeSymbol(chatId, sym) {
  await del("/users/" + chatId + "/symbols/" + encodeURIComponent(sym));
  toast("Market removed");
  openUserModal(chatId, "");
}

async function savePhone() {
  await post("/users/" + userModalId + "/phone", { phone: document.getElementById("modal-phone").value });
  toast("Phone saved");
}

// ── ALERTS ──
async function loadAlerts() {
  const alerts = await get("/alerts?limit=100");
  const tbody = document.getElementById("alerts-tbody");
  tbody.innerHTML = alerts.map(a => `
    <tr>
      <td style="font-size:11px">${(a.sent_at || "").slice(0, 19).replace("T", " ")}</td>
      <td>${a.telegram_name || a.chat_id || "—"}</td>
      <td><code>${a.symbol}</code></td>
      <td><span class="tag ${a.direction==='LONG'?'tag-buy':'tag-sell'}">${a.direction}</span></td>
      <td><span class="tag ${a.strategy==='SMC'?'tag-smc':'tag-scalp'}">${a.strategy||'scalp'}</span></td>
      <td>${a.setup}</td>
      <td>${fmt(a.entry)}</td>
      <td>${fmt(a.sl)}</td>
      <td>${fmt(a.tp)}</td>
      <td>${Math.round((a.confidence||0)*100)}%</td>
    </tr>`).join("") || '<tr><td colspan="10" style="text-align:center;color:var(--text2)">No alerts yet</td></tr>';
}

// ── MARKETS ──
async function loadMarkets() {
  const syms = await get("/symbols");
  const tbody = document.getElementById("markets-tbody");
  tbody.innerHTML = Object.entries(syms).map(([sym, info]) => `
    <tr>
      <td><code>${sym}</code></td>
      <td>${info.name || sym}</td>
      <td>${info.active ? '<span class="badge-active">Active</span>' : '<span class="badge-paused">Paused</span>'}</td>
      <td>${(info.added || "").slice(0, 10)}</td>
      <td>
        <button class="btn btn-sm ${info.active?'btn-ghost':'btn-success'}" onclick="toggleMarket('${sym}',${!info.active})">${info.active?'Pause':'Activate'}</button>
        <button class="btn btn-sm btn-danger" onclick="removeMarket('${sym}')">Remove</button>
      </td>
    </tr>`).join("") || '<tr><td colspan="5" style="text-align:center;color:var(--text2)">No symbols</td></tr>';
}

async function searchMarket() {
  const q = document.getElementById("market-search").value.trim();
  if (!q) return;
  const results = await post("/symbols/search", { query: q });
  const div = document.getElementById("search-results");
  div.innerHTML = results.map(r =>
    `<div style="cursor:pointer;padding:6px 10px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;transition:background .1s"
          onmouseover="this.style.background='rgba(55,114,255,0.08)'" onmouseout="this.style.background=''"
          onclick="addMarket('${r.symbol}','${r.description||''}')">
      <span><code>${r.symbol}</code> ${r.description}</span>
      <span style="color:var(--text2);font-size:11px">${r.exchange} | ${r.type}</span>
    </div>`
  ).join("") || '<span style="color:var(--text2)">No results</span>';
}

async function addMarket(sym, name) {
  await post("/symbols", { symbol: sym, name });
  toast("Market added: " + sym);
  loadMarkets();
}

async function removeMarket(sym) {
  if (!confirm("Stop monitoring " + sym + "?")) return;
  await del("/symbols/" + encodeURIComponent(sym));
  toast("Market removed");
  loadMarkets();
}

async function toggleMarket(sym, active) {
  await patch("/symbols/" + encodeURIComponent(sym), { active });
  toast(active ? "Market activated" : "Market paused");
  loadMarkets();
}

async function addManual() {
  const sym = document.getElementById("manual-symbol").value.trim();
  const name = document.getElementById("manual-name").value.trim();
  if (!sym) return toast("Enter a symbol", "error");
  await post("/symbols", { symbol: sym, name: name || sym });
  toast("Symbol added: " + sym);
  document.getElementById("manual-symbol").value = "";
  document.getElementById("manual-name").value = "";
  loadMarkets();
}

// ── Init ──
document.addEventListener("DOMContentLoaded", () => {
  showPage("dashboard");
  refreshTimer = setInterval(() => {
    if (currentPage === "dashboard") loadDashboard();
    if (currentPage === "alerts") loadAlerts();
  }, 30000);
});
