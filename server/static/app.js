// EXO dashboard. Onboarding + live (real-data-only) dashboard.
"use strict";

const $ = (id) => document.getElementById(id);

function money(v, signed = false) {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const sign = v < 0 ? "-" : (signed ? "+" : "");
  return sign + "$" + Math.abs(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function cls(v) { if (v === null || v === undefined || isNaN(v)) return "flat"; return v > 0 ? "pos" : v < 0 ? "neg" : "flat"; }
function num(v, d = 2) { return (v === null || v === undefined || isNaN(v)) ? "—" : Number(v).toFixed(d); }
function fmtTime(ts) { return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
function fmtDur(s) { s = Math.floor(s || 0); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60); return (h ? h + "h " : "") + (m ? m + "m " : "") + (s % 60) + "s"; }

// ---------------------------------------------------------------- bootstrap
async function init() {
  let status;
  try { status = await (await fetch("/api/status")).json(); }
  catch { setTimeout(init, 1500); return; }

  loadUpdateStatus();   // version badge + update banner (independent of connection)

  if (status.connected) {
    showDashboard();
    connectWS();
  } else {
    await showOnboarding();
  }
}

// ---------------------------------------------------------------- updates
async function loadUpdateStatus() {
  try {
    const u = await (await fetch("/api/update/status")).json();
    $("appVersion").textContent = u.current ? "v" + u.current : "";
    if (u.available) showUpdateBanner(u);
  } catch { /* ignore */ }
}
function showUpdateBanner(u) {
  $("ubVersion").textContent = `Update available — v${u.latest_version}`;
  const notes = (u.notes || "").trim();
  $("ubNotes").textContent = notes ? "  ·  " + notes.split("\n")[0].slice(0, 120) : "";
  $("updateBanner").hidden = false;
}
async function applyUpdate() {
  if (!confirm("Update now? The app will close and reopen automatically. Your login and data are kept.")) return;
  $("updateOverlay").hidden = false;
  try {
    const res = await fetch("/api/update/apply", { method: "POST" });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      $("updateOverlay").hidden = true;
      alert("Update failed: " + (d.error || "unknown error"));
    }
    // On success the app exits and the new version relaunches itself.
  } catch {
    // Connection dropped because the app is restarting — expected on success.
  }
}

function showOnboarding() {
  $("onboarding").hidden = false;
  $("dashboard").hidden = true;
  $("topBadges").hidden = true;
  $("statusDot").className = "dot";
  $("status").textContent = "not connected";
  return loadProviders();
}
function showDashboard() {
  $("onboarding").hidden = true;
  $("dashboard").hidden = false;
  $("topBadges").hidden = false;
}

// ---------------------------------------------------------------- onboarding
let PROVIDERS = [];
async function loadProviders() {
  PROVIDERS = await (await fetch("/api/providers")).json();
  const root = $("providerCards");
  root.innerHTML = "";
  for (const p of PROVIDERS) {
    const card = document.createElement("div");
    card.className = "provider-card";
    const caps = [];
    if (p.account_sync) caps.push("Real account data");
    else caps.push("Execution only");
    if (p.realtime) caps.push("Real-time");
    card.innerHTML = `
      <div class="pc-name">${p.name}</div>
      <div class="pc-desc">${p.description}</div>
      <div class="pc-caps">${caps.map(c => `<span class="cap">${c}</span>`).join("")}</div>`;
    card.addEventListener("click", () => showLogin(p.id));
    root.appendChild(card);
  }
}

function showLogin(providerId) {
  const p = PROVIDERS.find(x => x.id === providerId);
  if (!p) return;
  $("providerCards").hidden = true;
  $("loginForm").hidden = false;
  $("loginForm").dataset.provider = providerId;
  $("loginTitle").textContent = "Log in — " + p.name;
  $("loginDesc").textContent = p.description;
  $("loginNote").textContent = p.notes || "";

  const caps = $("capBadges");
  caps.innerHTML = "";
  const add = (txt, ok) => { const s = document.createElement("span"); s.className = "cap " + (ok ? "ok" : "no"); s.textContent = txt; caps.appendChild(s); };
  add(p.account_sync ? "Real account data" : "No account readback", p.account_sync);
  add(p.realtime ? "Real-time sync" : "Polled", p.realtime);
  add(p.feed_type ? "Market data" : "Account only", !!p.feed_type);

  const ff = $("formFields");
  ff.innerHTML = "";
  for (const f of p.fields) {
    const wrap = document.createElement("label");
    wrap.className = "field";
    wrap.innerHTML = `<span class="field-label">${f.label}${f.required ? "" : " <i class='opt'>(optional)</i>"}</span>
      <input type="${f.type === "password" ? "password" : "text"}" name="${f.key}"
        placeholder="${f.placeholder || ""}" value="${f.default || ""}" autocomplete="off"
        ${f.required ? "required" : ""} />
      ${f.help ? `<span class="field-help">${f.help}</span>` : ""}`;
    ff.appendChild(wrap);
  }
  $("connectMsg").textContent = "";
}

function backToProviders() {
  $("loginForm").hidden = true;
  $("providerCards").hidden = false;
  $("connectMsg").textContent = "";
}

async function submitLogin(e) {
  e.preventDefault();
  const provider = $("loginForm").dataset.provider;
  const fields = {};
  $("formFields").querySelectorAll("input").forEach(i => { if (i.value !== "") fields[i.name] = i.value; });
  const btn = $("connectBtn");
  const msg = $("connectMsg");
  btn.disabled = true; btn.textContent = "Connecting…"; msg.className = "connect-msg"; msg.textContent = "";
  try {
    const res = await fetch("/api/connect", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, fields }),
    });
    const data = await res.json();
    if (res.ok && data.ok) {
      msg.className = "connect-msg ok"; msg.textContent = (data.message || "Connected") + " — loading…";
      setTimeout(() => location.reload(), 800);
    } else {
      msg.className = "connect-msg err"; msg.textContent = "Connection failed: " + (data.error || "unknown error");
      btn.disabled = false; btn.textContent = "Connect";
    }
  } catch (err) {
    msg.className = "connect-msg err"; msg.textContent = "Connection failed: " + err;
    btn.disabled = false; btn.textContent = "Connect";
  }
}

// ---------------------------------------------------------------- websocket
let ws;
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { $("statusDot").className = "dot live"; $("status").textContent = "live"; };
  ws.onclose = () => { $("statusDot").className = "dot dead"; $("status").textContent = "reconnecting…"; setTimeout(connectWS, 2000); };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.type === "state") {
      if (!m.data.connected) { location.reload(); return; }
      render(m.data);
    } else if (m.type === "trade") toastTrade(m.data);
    else if (m.type === "risk") toastRisk(m.data);
    else if (m.type === "update") showUpdateBanner(m.data);
  };
}

// ---------------------------------------------------------------- render
function render(s) {
  const a = s.account || {}, r = s.risk || {};
  $("provider").textContent = s.provider || "—";
  $("mode").textContent = s.mode || "—";
  $("uptime").textContent = fmtDur(s.uptime_s);

  const note = $("modeNote");
  if (s.mode === "monitor") {
    note.hidden = false;
    note.textContent = "Monitor mode: showing live account data. Strategies trade only when a market-data feed is connected.";
  } else { note.hidden = true; }

  if (!a.synced) {
    ["balance", "equity", "openPnl", "dayPnl", "openContracts"].forEach(id => { $(id).textContent = "—"; $(id).className = "value"; });
    $("status").textContent = "connected — awaiting account data";
  } else {
    $("balance").textContent = money(a.balance);
    $("equity").textContent = money(a.equity);
    setVal($("openPnl"), a.open_pnl, true);
    setVal($("dayPnl"), a.day_pnl, true);
    $("openContracts").textContent = a.open_contracts ?? "—";
  }

  setBar($("dailyBar"), $("dailyNum"), r.daily_loss_used_pct, money(a.day_pnl != null && a.day_pnl < 0 ? a.day_pnl : 0) + " / " + money(-(r.daily_loss_limit || 0)));
  setBar($("ddBar"), $("ddNum"), r.drawdown_used_pct, money(a.drawdown) + " / " + money(-(r.trailing_drawdown || 0)));
  $("peakEquity").textContent = money(a.peak_equity);
  $("maxContracts").textContent = r.max_contracts_account ?? "—";
  const hb = $("haltBadge");
  hb.textContent = r.permanently_halted ? "HALTED — drawdown breached" : r.day_halted ? "Day halted — daily loss hit" : "active";
  hb.className = "small " + (r.permanently_halted || r.day_halted ? "warn" : "muted");

  renderPositions(s.live_positions || []);
  renderStrategies(s.strategies || []);
  renderTrades(s.recent_trades || []);
  drawEquity(s.equity_curve || []);
  $("stratCount").textContent = `${(s.strategies || []).filter(x => x.enabled).length}/${(s.strategies || []).length} active`;
}

function setVal(el, v, signed) { el.textContent = money(v, signed); el.className = "value " + cls(v); }
function setBar(bar, numEl, pct, text) {
  pct = Math.max(0, Math.min(100, pct || 0));
  bar.style.width = pct + "%";
  bar.style.background = pct >= 80 ? "var(--red)" : pct >= 50 ? "var(--yellow)" : "var(--fill)";
  numEl.textContent = text;
}

function renderPositions(positions) {
  const body = $("positionsBody");
  body.innerHTML = "";
  if (!positions.length) { body.innerHTML = `<tr><td colspan="5" class="muted">No open positions.</td></tr>`; return; }
  for (const p of positions) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.symbol}</td>
      <td class="${p.side === "LONG" ? "pos" : p.side === "SHORT" ? "neg" : "flat"}">${p.side}</td>
      <td class="r">${Math.abs(p.qty)}</td>
      <td class="r">${num(p.avg_price)}</td>
      <td class="r ${cls(p.open_pnl)}">${money(p.open_pnl, true)}</td>`;
    body.appendChild(tr);
  }
}

function renderStrategies(list) {
  const root = $("strategies");
  root.innerHTML = "";
  for (const st of list) {
    const div = document.createElement("div");
    div.className = "strat" + (st.enabled ? "" : " off");
    const posCls = st.qty > 0 ? "pos" : st.qty < 0 ? "neg" : "flat";
    const posTxt = st.position === "FLAT" ? "flat" : `${st.position} ${Math.abs(st.qty)} @ ${num(st.avg_price)}`;
    div.innerHTML = `
      <div class="strat-top">
        <div><div class="strat-name">${st.name}</div><div class="strat-sym">${st.symbol} · ${st.key}</div></div>
        <label class="switch"><input type="checkbox" ${st.enabled ? "checked" : ""} data-id="${st.id}"><span class="slider"></span></label>
      </div>
      <div class="strat-desc">${st.description || ""}</div>
      <div class="strat-stats">
        <div class="strat-stat"><span>Position</span><b class="${posCls}">${posTxt}</b></div>
        <div class="strat-stat"><span>Unreal.</span><b class="${cls(st.unrealized)}">${money(st.unrealized, true)}</b></div>
        <div class="strat-stat"><span>Day P/L</span><b class="${cls(st.day_pnl)}">${money(st.day_pnl, true)}</b></div>
        <div class="strat-stat"><span>Total</span><b class="${cls(st.total_pnl)}">${money(st.total_pnl, true)}</b></div>
        <div class="strat-stat"><span>Trades</span><b>${st.trades}</b></div>
        <div class="strat-stat"><span>Win%</span><b>${num(st.win_rate, 1)}</b></div>
      </div>`;
    root.appendChild(div);
  }
  root.querySelectorAll("input[type=checkbox]").forEach((cb) => {
    cb.addEventListener("change", () => fetch(`/api/strategy/${encodeURIComponent(cb.dataset.id)}/toggle`, { method: "POST" }));
  });
}

function renderTrades(trades) {
  const body = $("tradesBody");
  body.innerHTML = "";
  if (!trades.length) { body.innerHTML = `<tr><td colspan="9" class="muted">No bot trades yet this session.</td></tr>`; return; }
  for (const t of trades) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="muted">${fmtTime(t.exit_ts)}</td><td>${t.strategy}</td><td>${t.symbol}</td>
      <td class="${t.direction === "LONG" ? "pos" : "neg"}">${t.direction}</td>
      <td class="r">${t.qty}</td><td class="r">${num(t.entry)}</td><td class="r">${num(t.exit)}</td>
      <td class="r ${cls(t.ticks)}">${t.ticks >= 0 ? "+" : ""}${num(t.ticks, 0)}</td>
      <td class="r ${cls(t.pnl)}">${money(t.pnl, true)}</td>`;
    body.appendChild(tr);
  }
}

// ---------------------------------------------------------------- equity canvas (FIXED: no growth)
const CURVE_H = 220;
function drawEquity(curve) {
  const cv = $("equityCanvas");
  if (!cv) return;
  const ctx = cv.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssW = cv.clientWidth || cv.parentElement.clientWidth || 600;
  // Resize the backing buffer ONLY when needed — never feed the rendered height
  // back into itself (that was the unbounded-growth bug).
  const bw = Math.round(cssW * dpr), bh = Math.round(CURVE_H * dpr);
  if (cv.width !== bw || cv.height !== bh) { cv.width = bw; cv.height = bh; }
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, cssW, CURVE_H);
  if (!curve || curve.length < 2) {
    ctx.fillStyle = "#6a6a6a"; ctx.font = "13px -apple-system, sans-serif";
    ctx.fillText("Waiting for account equity…", 12, CURVE_H / 2);
    $("curveMeta").textContent = "";
    return;
  }
  const vals = curve.map(p => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.1; lo -= pad; hi += pad;
  const x = (i) => (i / (curve.length - 1)) * (cssW - 8) + 4;
  const y = (v) => CURVE_H - 6 - ((v - lo) / (hi - lo)) * (CURVE_H - 12);

  ctx.strokeStyle = "#3a3a3a"; ctx.lineWidth = 1; ctx.setLineDash([4, 4]);
  ctx.beginPath(); ctx.moveTo(0, y(vals[0])); ctx.lineTo(cssW, y(vals[0])); ctx.stroke();
  ctx.setLineDash([]);

  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? "#4caf78" : "#e0584e";
  const grad = ctx.createLinearGradient(0, 0, 0, CURVE_H);
  grad.addColorStop(0, up ? "rgba(76,175,120,0.16)" : "rgba(224,88,78,0.16)");
  grad.addColorStop(1, "rgba(0,0,0,0)");
  ctx.beginPath(); ctx.moveTo(x(0), y(vals[0]));
  vals.forEach((v, i) => ctx.lineTo(x(i), y(v)));
  ctx.lineTo(x(vals.length - 1), CURVE_H); ctx.lineTo(x(0), CURVE_H); ctx.closePath();
  ctx.fillStyle = grad; ctx.fill();

  ctx.beginPath(); ctx.moveTo(x(0), y(vals[0]));
  vals.forEach((v, i) => ctx.lineTo(x(i), y(v)));
  ctx.strokeStyle = color; ctx.lineWidth = 1.6; ctx.stroke();
  $("curveMeta").textContent = `${money(vals[vals.length - 1])} · ${vals.length} pts`;
}

// ---------------------------------------------------------------- toasts + controls
function toast(html, kind) {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.innerHTML = html;
  $("toasts").appendChild(t); setTimeout(() => t.remove(), 6000);
}
function toastTrade(d) {
  toast(`<b>${d.strategy}</b> ${d.symbol} ${d.direction}<br><span class="${cls(d.pnl)}">${money(d.pnl, true)} (${d.ticks >= 0 ? "+" : ""}${Number(d.ticks).toFixed(0)} ticks)</span>`, d.pnl >= 0 ? "win" : "loss");
}
function toastRisk(d) { toast(`<b class="warn">⚠ Risk</b><br>${d.message}`, "risk"); }

$("loginForm").addEventListener("submit", submitLogin);
$("backBtn").addEventListener("click", backToProviders);
$("updateBtn").addEventListener("click", applyUpdate);
$("flattenBtn").addEventListener("click", () => { if (confirm("Flatten ALL positions now?")) fetch("/api/flatten", { method: "POST" }); });
$("disconnectBtn").addEventListener("click", async () => {
  if (!confirm("Disconnect from this account?")) return;
  await fetch("/api/disconnect", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  location.reload();
});
window.addEventListener("resize", () => { /* canvas redraws on next state push */ });

init();
