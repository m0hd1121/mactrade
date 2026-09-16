const SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCHF", "USDCAD", "NZDUSD", "XAUUSD"];

function fmtMoney(v) { return v === null || v === undefined ? "--" : "$" + Number(v).toFixed(2); }
function fmtPct(v) { return v === null || v === undefined ? "--" : Number(v).toFixed(2) + "%"; }
function pnlClass(v) { return v > 0 ? "pos" : v < 0 ? "neg" : ""; }

function toast(msg) {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.style.display = "block";
  clearTimeout(toast._t);
  toast._t = setTimeout(() => (el.style.display = "none"), 4000);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status}: ${body}`);
  }
  return res.status === 204 ? null : res.json();
}

// ---------------------------------------------------------------- tabs
document.querySelectorAll("nav.tabs button").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav.tabs button").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById("tab-" + btn.dataset.tab).classList.add("active");
  });
});

// ---------------------------------------------------------------- header/status
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    document.getElementById("connDot").className = "dot " + (s.bridge_connected ? "ok" : "bad");
    const pill = document.getElementById("modePill");
    pill.textContent = s.mode + (s.kill_switch_active ? " · KILL SWITCH" : s.running ? " · RUNNING" : " · PAUSED");
    pill.className = "status-pill " + s.mode.toLowerCase();
  } catch (e) { /* server still starting */ }
}

document.getElementById("btnStart").onclick = async () => {
  try { await api("/api/safety/start", { method: "POST" }); toast("Trading started"); } catch (e) { toast(e.message); }
};
document.getElementById("btnPause").onclick = async () => {
  await api("/api/safety/pause", { method: "POST" }); toast("Paused -- no new trades");
};
document.getElementById("btnKill").onclick = async () => {
  if (!confirm("Activate the KILL SWITCH? This stops all new trades and closes open positions.")) return;
  await api("/api/safety/kill", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason: "Manual kill switch from UI" }) });
  toast("Kill switch activated");
};
document.getElementById("btnCloseAll").onclick = async () => {
  if (!confirm("Close ALL open positions now?")) return;
  await api("/api/safety/close-all", { method: "POST" });
  toast("Close-all requested");
};

// ---------------------------------------------------------------- dashboard
async function refreshDashboard() {
  let d;
  try { d = await api("/api/dashboard"); } catch (e) { return; }
  document.getElementById("dBalance").textContent = fmtMoney(d.balance);
  document.getElementById("dEquity").textContent = fmtMoney(d.equity);
  const fl = document.getElementById("dFloating"); fl.textContent = fmtMoney(d.floating_pl); fl.className = "metric-value " + pnlClass(d.floating_pl);
  const dp = document.getElementById("dDaily"); dp.textContent = fmtMoney(d.daily_pl); dp.className = "metric-value " + pnlClass(d.daily_pl);
  const wp = document.getElementById("dWeekly"); wp.textContent = fmtMoney(d.weekly_pl); wp.className = "metric-value " + pnlClass(d.weekly_pl);
  document.getElementById("dRisk").textContent = fmtPct(d.risk_per_trade_pct);
  document.getElementById("dBroker").textContent = d.broker || "--";
  document.getElementById("dStrategyStatus").textContent = d.kill_switch_active ? "KILL SWITCH" : d.running ? "ACTIVE" : "PAUSED";

  const tbody = document.querySelector("#dPositionsTable tbody");
  tbody.innerHTML = "";
  (d.open_positions || []).forEach((p) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.symbol}</td><td>${p.direction}</td><td>${p.volume}</td><td>${p.entry_price}</td><td>${p.stop_loss}</td><td>${p.take_profit}</td>
      <td class="${pnlClass(p.profit)}">${fmtMoney(p.profit)}</td><td>${new Date(p.open_time).toLocaleString()}</td>`;
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------- market monitor
async function refreshMarket() {
  let rows;
  try { rows = await api("/api/market-monitor"); } catch (e) { return; }
  const tbody = document.querySelector("#marketTable tbody");
  tbody.innerHTML = "";
  rows.forEach((r) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${r.symbol}</td><td>${r.price ?? "--"}</td><td>${r.spread_points ?? "--"}</td>
      <td><span class="badge ${r.structure || ""}">${r.structure || "--"}</span></td>
      <td>${r.unswept_liquidity_pools ?? "--"}</td>
      <td><span class="badge ${r.setup_status}">${r.setup_status}</span></td>
      <td>${r.entry ?? "--"}</td><td>${r.stop_loss ?? "--"}</td><td>${r.take_profit ?? "--"}</td>
      <td>${r.reward_risk_ratio ? "1:" + Number(r.reward_risk_ratio).toFixed(1) : "--"}</td>`;
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------- trade setup detail
async function refreshSetups() {
  let setups;
  try { setups = await api("/api/setups"); } catch (e) { return; }
  const container = document.getElementById("setupDetails");
  container.innerHTML = "";
  setups.forEach((s) => {
    const div = document.createElement("div");
    div.className = "setup-detail";
    let reasoning = [];
    try { reasoning = JSON.parse(s.reasoning_json || "[]"); } catch (e) {}
    div.innerHTML = `<h4>${s.symbol} <span class="badge ${s.status}">${s.status}</span></h4>
      <div class="metric-sub">Structure: ${s.structure || "--"} | Liquidity: ${s.liquidity || "--"}</div>
      ${s.entry ? `<div style="margin-top:6px;">Entry: ${s.entry} &nbsp; SL: ${s.stop_loss} &nbsp; TP: ${s.take_profit} &nbsp; R:R 1:${Number(s.reward_risk_ratio).toFixed(1)}</div>` : ""}
      <ul>${reasoning.map((r) => `<li>${r}</li>`).join("")}</ul>`;
    container.appendChild(div);
  });
}

// ---------------------------------------------------------------- risk monitor
async function refreshRisk() {
  let r;
  try { r = await api("/api/risk"); } catch (e) { return; }
  document.getElementById("rBalance").textContent = fmtMoney(r.balance);
  document.getElementById("rEquity").textContent = fmtMoney(r.equity);
  document.getElementById("rDaily").textContent = `${fmtMoney(r.daily_pnl)} / ${fmtPct(-r.max_daily_loss_pct)}`;
  document.getElementById("rWeekly").textContent = `${fmtMoney(r.weekly_pnl)} / ${fmtPct(-r.max_weekly_loss_pct)}`;
  document.getElementById("rTrades").textContent = `${r.trades_today} / ${r.max_trades_per_day}`;
  document.getElementById("rPositions").textContent = `${r.open_exposure_positions} / ${r.max_concurrent_positions}`;
  document.getElementById("rConsec").textContent = `${r.consecutive_losses} / ${r.max_consecutive_losses_pause}`;

  let viability;
  try { viability = await api("/api/account-viability"); } catch (e) { viability = []; }
  const tbody = document.querySelector("#viabilityTable tbody");
  tbody.innerHTML = "";
  viability.forEach((v) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${v.symbol}</td><td class="${v.tradable ? "pos" : "neg"}">${v.tradable ? "YES" : "NO"}</td>
      <td>${v.reason || "--"}</td><td>${v.minimum_practical_balance ? fmtMoney(v.minimum_practical_balance) : "--"}</td>`;
    tbody.appendChild(tr);
  });
}

// ---------------------------------------------------------------- backtesting
function populateSymbolSelect() {
  const sel = document.getElementById("btSymbol");
  SYMBOLS.forEach((s) => { const o = document.createElement("option"); o.value = s; o.textContent = s; sel.appendChild(o); });
}

document.getElementById("btnRunBacktest").onclick = async () => {
  const btn = document.getElementById("btnRunBacktest");
  btn.disabled = true; btn.textContent = "Running...";
  try {
    const payload = {
      symbol: document.getElementById("btSymbol").value,
      starting_balance: Number(document.getElementById("btBalance").value),
      risk_pct: Number(document.getElementById("btRisk").value),
      bar_count: Number(document.getElementById("btBars").value),
      run_small_account_sweep: document.getElementById("btSweep").checked,
      run_walk_forward: document.getElementById("btWF").checked,
      run_monte_carlo: document.getElementById("btMC").checked,
    };
    const result = await api("/api/backtest", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    renderBacktestResult(result);
  } catch (e) {
    toast("Backtest failed: " + e.message);
  } finally {
    btn.disabled = false; btn.textContent = "Run Backtest";
  }
};

function renderBacktestResult(result) {
  const m = result.metrics;
  const container = document.getElementById("backtestResults");
  container.innerHTML = "";

  const summary = document.createElement("div");
  summary.className = "card";
  summary.style.marginTop = "14px";
  summary.innerHTML = `<h3>Results (${result.data_source})</h3>
    <div class="grid cols-4">
      <div><div class="metric-sub">Total Trades</div><div class="metric-value">${m.total_trades}</div></div>
      <div><div class="metric-sub">Win Rate</div><div class="metric-value">${fmtPct(m.win_rate)}</div></div>
      <div><div class="metric-sub">Profit Factor</div><div class="metric-value">${m.profit_factor ?? "--"}</div></div>
      <div><div class="metric-sub">Expectancy</div><div class="metric-value">${fmtMoney(m.expectancy)}</div></div>
      <div><div class="metric-sub">Max Drawdown</div><div class="metric-value">${fmtPct(m.max_drawdown_pct)}</div></div>
      <div><div class="metric-sub">Max Consecutive Losses</div><div class="metric-value">${m.max_consecutive_losses}</div></div>
      <div><div class="metric-sub">Total Return</div><div class="metric-value ${pnlClass(m.total_return_pct)}">${fmtPct(m.total_return_pct)}</div></div>
      <div><div class="metric-sub">Sharpe Ratio</div><div class="metric-value">${m.sharpe_ratio}</div></div>
      <div><div class="metric-sub">Recovery Factor</div><div class="metric-value">${m.recovery_factor ?? "--"}</div></div>
      <div><div class="metric-sub">Avg R:R</div><div class="metric-value">1:${m.avg_reward_risk_ratio}</div></div>
      <div><div class="metric-sub">Ending Balance</div><div class="metric-value">${fmtMoney(m.ending_balance)}</div></div>
      <div><div class="metric-sub">Net Profit</div><div class="metric-value ${pnlClass(m.net_profit)}">${fmtMoney(m.net_profit)}</div></div>
    </div>
    <canvas id="equityChart" style="margin-top:14px;"></canvas>`;
  container.appendChild(summary);
  drawEquityCurve(result.equity_curve);

  if (result.small_account_sweep) {
    const c = document.createElement("div");
    c.className = "card"; c.style.marginTop = "14px";
    c.innerHTML = `<h3>Small-Account Sweep</h3><table><thead><tr><th>Balance</th><th>Trades</th><th>Rejected (size)</th><th>Return</th><th>Max DD</th><th>Viable</th></tr></thead><tbody>${
      result.small_account_sweep.map((s) => `<tr><td>${fmtMoney(s.starting_balance)}</td><td>${s.total_trades}</td><td>${s.trades_rejected_for_account_size}</td>
        <td class="${pnlClass(s.total_return_pct)}">${fmtPct(s.total_return_pct)}</td><td>${fmtPct(s.max_drawdown_pct)}</td>
        <td class="${s.viable ? "pos" : "neg"}">${s.viable ? "YES" : "NO"}</td></tr>`).join("")
    }</tbody></table>`;
    container.appendChild(c);
  }

  if (result.walk_forward) {
    const c = document.createElement("div");
    c.className = "card"; c.style.marginTop = "14px";
    c.innerHTML = `<h3>Walk-Forward</h3><table><thead><tr><th>Segment</th><th>Bars</th><th>Trades</th><th>Win Rate</th><th>Return</th><th>Max DD</th></tr></thead><tbody>${
      result.walk_forward.map((w) => `<tr><td>${w.name}</td><td>${w.bar_count}</td><td>${w.metrics.total_trades}</td>
        <td>${fmtPct(w.metrics.win_rate)}</td><td class="${pnlClass(w.metrics.total_return_pct)}">${fmtPct(w.metrics.total_return_pct)}</td><td>${fmtPct(w.metrics.max_drawdown_pct)}</td></tr>`).join("")
    }</tbody></table>`;
    container.appendChild(c);
  }

  if (result.monte_carlo) {
    const mc = result.monte_carlo;
    const c = document.createElement("div");
    c.className = "card"; c.style.marginTop = "14px";
    c.innerHTML = `<h3>Monte Carlo (${mc.iterations} runs)</h3>
      <div class="grid cols-4">
        <div><div class="metric-sub">Final Balance P5</div><div class="metric-value">${fmtMoney(mc.final_balance_p5)}</div></div>
        <div><div class="metric-sub">Final Balance P50</div><div class="metric-value">${fmtMoney(mc.final_balance_p50)}</div></div>
        <div><div class="metric-sub">Final Balance P95</div><div class="metric-value">${fmtMoney(mc.final_balance_p95)}</div></div>
        <div><div class="metric-sub">Probability of Ruin</div><div class="metric-value">${fmtPct(mc.probability_of_ruin * 100)}</div></div>
      </div>`;
    container.appendChild(c);
  }
}

function drawEquityCurve(points) {
  const canvas = document.getElementById("equityChart");
  if (!canvas || !points || !points.length) return;
  const ctx = canvas.getContext("2d");
  const rect = canvas.getBoundingClientRect();
  canvas.width = rect.width * devicePixelRatio; canvas.height = 220 * devicePixelRatio;
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const w = rect.width, h = 220;
  const values = points.map((p) => p[1]);
  const min = Math.min(...values), max = Math.max(...values);
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "#6c5ce7"; ctx.lineWidth = 1.5; ctx.beginPath();
  points.forEach((p, i) => {
    const x = (i / (points.length - 1)) * (w - 10) + 5;
    const y = h - 10 - ((p[1] - min) / (max - min || 1)) * (h - 20);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}

// ---------------------------------------------------------------- settings
async function loadSettings() {
  const c = await api("/api/settings");
  document.getElementById("sMode").value = c.mode;
  document.getElementById("sLiveConfirm").value = String(c.live_trading_confirmed);
  document.getElementById("sRiskPct").value = c.risk.risk_per_trade_pct;
  document.getElementById("sMaxDaily").value = c.risk.max_daily_loss_pct;
  document.getElementById("sMaxWeekly").value = c.risk.max_weekly_loss_pct;
  document.getElementById("sMaxTrades").value = c.risk.max_trades_per_day;
  document.getElementById("sMaxPositions").value = c.risk.max_concurrent_positions;
  document.getElementById("sMaxSpread").value = c.risk.max_spread_points;
  document.getElementById("sBridgeKind").value = c.bridge.kind;
  document.getElementById("sBridgeDir").value = c.bridge.files_dir || "";
}

document.getElementById("btnSaveSettings").onclick = async () => {
  const payload = {
    mode: document.getElementById("sMode").value,
    live_trading_confirmed: document.getElementById("sLiveConfirm").value === "true",
    risk: {
      risk_per_trade_pct: Number(document.getElementById("sRiskPct").value),
      max_daily_loss_pct: Number(document.getElementById("sMaxDaily").value),
      max_weekly_loss_pct: Number(document.getElementById("sMaxWeekly").value),
      max_trades_per_day: Number(document.getElementById("sMaxTrades").value),
      max_concurrent_positions: Number(document.getElementById("sMaxPositions").value),
      max_spread_points: Number(document.getElementById("sMaxSpread").value),
      min_reward_risk: 3.0,
    },
    bridge: {
      kind: document.getElementById("sBridgeKind").value,
      files_dir: document.getElementById("sBridgeDir").value || null,
    },
  };
  try {
    await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    toast("Settings saved");
  } catch (e) { toast("Save failed: " + e.message); }
};

document.getElementById("btnTestConnection").onclick = async () => {
  const el = document.getElementById("testConnResult");
  el.textContent = "Testing...";
  try {
    const r = await api("/api/test-connection", { method: "POST" });
    el.textContent = r.connected ? `Connected: ${r.broker} (login ${r.login}, balance ${r.balance} ${r.currency})` : `Not connected: ${r.message}`;
  } catch (e) { el.textContent = "Error: " + e.message; }
};

// ---------------------------------------------------------------- boot
populateSymbolSelect();
loadSettings().catch(() => {});
refreshStatus();
refreshDashboard();
refreshMarket();
refreshSetups();
refreshRisk();

setInterval(refreshStatus, 4000);
setInterval(refreshDashboard, 5000);
setInterval(refreshMarket, 5000);
setInterval(refreshSetups, 6000);
setInterval(refreshRisk, 8000);

// ---------------------------------------------------------------- first-run setup wizard
let wizardStep = 1;
function setWizardSteps() {
  for (let i = 1; i <= 4; i++) document.getElementById("wstep" + i).className = i <= wizardStep ? "done" : "";
}

async function renderWizard() {
  const content = document.getElementById("wizardContent");
  setWizardSteps();

  if (wizardStep === 1) {
    content.innerHTML = `<h2>Welcome</h2><p>Forex Trading System -- Version 1.0</p>
      <p class="metric-sub">A small-account-aware, price-action-only MT5 trading system. Let's get you connected.</p>
      <button class="btn" id="wNext">Continue</button>`;
    document.getElementById("wNext").onclick = () => { wizardStep = 2; renderWizard(); };
  }

  if (wizardStep === 2) {
    content.innerHTML = `<h2>MT5 Connection</h2><div id="wEnv">Checking environment...</div>
      <button class="btn secondary" id="wTest" style="margin-top:10px;">Test Connection</button>
      <div id="wTestResult" class="metric-sub" style="margin-top:8px;"></div>
      <div style="margin-top:16px;"><button class="btn" id="wNext">Continue</button></div>`;
    try {
      const env = await api("/api/environment");
      document.getElementById("wEnv").innerHTML = `
        <div>MT5 Installation: <b class="${env.mt5_app_found ? "pos" : "neg"}">${env.mt5_app_found ? "Detected" : "Not found"}</b></div>
        <div>Bridge EA Heartbeat: <b class="${env.ea_heartbeat_detected ? "pos" : "neg"}">${env.ea_heartbeat_detected ? "Detected" : "Not detected"}</b></div>
        ${env.notes.map((n) => `<div class="metric-sub" style="margin-top:4px;">${n}</div>`).join("")}`;
    } catch (e) { document.getElementById("wEnv").textContent = "Could not read environment."; }
    document.getElementById("wTest").onclick = async () => {
      const el = document.getElementById("wTestResult");
      el.textContent = "Testing...";
      try {
        const r = await api("/api/test-connection", { method: "POST" });
        el.textContent = r.connected ? `Connected: ${r.broker}, account ${r.login}, balance ${r.balance} ${r.currency}` : `Not connected: ${r.message}`;
      } catch (e) { el.textContent = "Error: " + e.message; }
    };
    document.getElementById("wNext").onclick = () => { wizardStep = 3; renderWizard(); };
  }

  if (wizardStep === 3) {
    content.innerHTML = `<h2>Risk Management</h2>
      <label>Risk per trade</label>
      <select id="wRisk"><option value="0.25">0.25%</option><option value="0.5" selected>0.5%</option><option value="0.75">0.75%</option><option value="1.0">1%</option></select>
      <label>Daily loss limit</label>
      <select id="wDaily"><option value="1">1%</option><option value="2" selected>2%</option><option value="3">3%</option></select>
      <div style="margin-top:16px;"><button class="btn" id="wNext">Continue</button></div>`;
    document.getElementById("wNext").onclick = async () => {
      try {
        const cfg = await api("/api/settings");
        await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
          risk: { ...cfg.risk, risk_per_trade_pct: Number(document.getElementById("wRisk").value), max_daily_loss_pct: Number(document.getElementById("wDaily").value) },
        }) });
      } catch (e) { toast(e.message); }
      wizardStep = 4; renderWizard();
    };
  }

  if (wizardStep === 4) {
    content.innerHTML = `<h2>Trading Mode</h2>
      <p class="metric-sub">Live trading is never activated automatically. Start in Paper Trading.</p>
      <label><input type="radio" name="wmode" value="BACKTEST" /> Backtest</label>
      <label><input type="radio" name="wmode" value="PAPER" checked /> Paper Trading (recommended)</label>
      <label><input type="radio" name="wmode" value="LIVE" /> Live Trading (requires explicit confirmation later)</label>
      <div style="margin-top:16px;"><button class="btn" id="wFinish">Open Dashboard</button></div>`;
    document.getElementById("wFinish").onclick = async () => {
      const mode = document.querySelector('input[name=wmode]:checked').value;
      try { await api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode, live_trading_confirmed: false }) }); }
      catch (e) { toast(e.message); }
      localStorage.setItem("fts_setup_complete", "1");
      document.getElementById("wizardOverlay").style.display = "none";
      loadSettings().catch(() => {});
    };
  }
}

if (!localStorage.getItem("fts_setup_complete")) {
  document.getElementById("wizardOverlay").style.display = "flex";
  renderWizard();
}
