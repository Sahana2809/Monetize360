const API = "/api";

const state = {
  domain: null,
  config: null,
  activeTab: "config",
};

const BANKING_SAMPLE = {
  "domain": "banking",
  "version": 1,
  "description": "Risk-based personal loan interest-rate pricing: credit score tier, LTV, DTI, term, segment, delinquency, collateral.",
  "currency": "APR_PCT",
  "entity": {"name": "loan_quote", "description": "Annual percentage rate quoted for one loan offer"},
  "attributes": [
    {"name": "base_rate", "type": "number", "description": "Benchmark/prime rate before risk adjustments"},
    {"name": "credit_score", "type": "number", "description": "FICO-style credit score, 300-850"},
    {"name": "loan_to_value_ratio", "type": "number", "description": "Loan amount / collateral value"},
    {"name": "debt_to_income_ratio", "type": "number", "description": "Borrower's total debt / income"},
    {"name": "loan_term_months", "type": "number"},
    {"name": "customer_segment", "type": "string", "enum": ["retail", "existing_customer", "private_banking"]},
    {"name": "collateral_type", "type": "string", "enum": ["unsecured", "secured"]},
    {"name": "delinquency_history_count", "type": "number", "description": "Number of past delinquencies on record"}
  ],
  "base_price": {"mode": "attribute", "attribute": "base_rate"},
  "combination_mode": "sequential",
  "rules": [
    {"id": "credit_tier_subprime", "description": "Subprime credit score risk premium", "priority": 10,
     "condition": {"attr": "credit_score", "op": "between", "value": [300, 579]}, "adjustment": {"type": "add", "value": 4.0}, "tags": ["risk", "credit"]},
    {"id": "credit_tier_subpar", "description": "Subpar credit score risk premium", "priority": 11,
     "condition": {"attr": "credit_score", "op": "between", "value": [580, 669]}, "adjustment": {"type": "add", "value": 2.0}, "tags": ["risk", "credit"]},
    {"id": "credit_tier_fair", "description": "Fair credit score small risk premium", "priority": 12,
     "condition": {"attr": "credit_score", "op": "between", "value": [670, 739]}, "adjustment": {"type": "add", "value": 0.75}, "tags": ["risk", "credit"]},
    {"id": "credit_tier_prime_discount", "description": "Prime credit score discount", "priority": 13,
     "condition": {"attr": "credit_score", "op": "between", "value": [740, 850]}, "adjustment": {"type": "add", "value": -0.25}, "tags": ["risk", "credit"]},
    {"id": "high_ltv_addon", "description": "Loan-to-value above 90% risk add-on", "priority": 20,
     "condition": {"attr": "loan_to_value_ratio", "op": ">", "value": 0.9}, "adjustment": {"type": "add", "value": 0.5}, "tags": ["risk", "collateral"]},
    {"id": "high_dti_addon", "description": "Debt-to-income above 43% risk add-on", "priority": 21,
     "condition": {"attr": "debt_to_income_ratio", "op": ">", "value": 0.43}, "adjustment": {"type": "add", "value": 0.75}, "tags": ["risk", "affordability"]},
    {"id": "long_term_premium", "description": "Premium for terms of 30 years (360 months) or more", "priority": 30,
     "condition": {"attr": "loan_term_months", "op": ">=", "value": 360}, "adjustment": {"type": "add", "value": 0.25}, "tags": ["term"]},
    {"id": "existing_customer_discount", "description": "Relationship discount for existing customers", "priority": 40,
     "condition": {"attr": "customer_segment", "op": "==", "value": "existing_customer"}, "adjustment": {"type": "add", "value": -0.25}, "tags": ["segment"]},
    {"id": "private_banking_discount", "description": "Private banking relationship discount", "priority": 40,
     "condition": {"attr": "customer_segment", "op": "==", "value": "private_banking"}, "adjustment": {"type": "add", "value": -0.5}, "tags": ["segment"]},
    {"id": "delinquency_penalty", "description": "Risk penalty scaled by number of past delinquencies", "priority": 50,
     "condition": {"attr": "delinquency_history_count", "op": ">=", "value": 1}, "adjustment": {"type": "formula", "formula": "price + delinquency_history_count * 0.5"}, "tags": ["risk", "history"]},
    {"id": "collateral_secured_discount", "description": "Discount when the loan is secured by collateral", "priority": 60,
     "condition": {"attr": "collateral_type", "op": "==", "value": "secured"}, "adjustment": {"type": "add", "value": -0.3}, "tags": ["collateral"]}
  ],
  "constraints": [
    {"type": "min_price", "value": 2.0},
    {"type": "max_price", "value": 29.99},
    {"type": "round", "value": 0.125, "rounding": "nearest"}
  ]
};

function $(sel) { return document.querySelector(sel); }
function $all(sel) { return Array.from(document.querySelectorAll(sel)); }

async function api(path, opts) {
  const res = await fetch(API + path, Object.assign({ headers: { "Content-Type": "application/json" } }, opts));
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch (e) { data = text; }
  if (!res.ok) throw new Error((data && data.detail) ? JSON.stringify(data.detail) : res.statusText);
  return data;
}

function toast(msg, isError) {
  const t = $("#toast");
  t.textContent = msg;
  t.style.borderColor = isError ? "var(--bad)" : "var(--border)";
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 3200);
}

function fmtCond(cond) {
  if (!cond) return "always";
  if (cond.always) return "always";
  if (cond.all) return "ALL(" + cond.all.map(fmtCond).join(" AND ") + ")";
  if (cond.any) return "ANY(" + cond.any.map(fmtCond).join(" OR ") + ")";
  if (cond.not) return "NOT(" + fmtCond(cond.not) + ")";
  if (cond.attr) return `${cond.attr} ${cond.op} ${JSON.stringify(cond.value)}`;
  return JSON.stringify(cond);
}

function fmtAdj(adj) {
  if (adj.type === "percent") return `${adj.value >= 0 ? "+" : ""}${adj.value}%`;
  if (adj.type === "multiply") return `×${adj.value}`;
  if (adj.type === "add") return `${adj.value >= 0 ? "+" : ""}${adj.value} flat`;
  if (adj.type === "set") return `= ${adj.value}`;
  if (adj.type === "formula") return `ƒ ${adj.formula}`;
  return JSON.stringify(adj);
}

/* ---------------- Tabs ---------------- */
function initTabs() {
  $all("nav.tabs button").forEach(btn => {
    btn.addEventListener("click", () => {
      $all("nav.tabs button").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.tab;
      state.activeTab = tab;
      ["config", "simulate", "price", "audit", "copilot"].forEach(t => {
        $("#tab-" + t).classList.toggle("hidden", t !== tab);
      });
      if (tab === "audit") loadAudit();
    });
  });
}

/* ---------------- Domain loading ---------------- */
async function loadDomains(selectDomain) {
  const { domains } = await api("/domains");
  const sel = $("#domainSelect");
  sel.innerHTML = "";
  domains.forEach(d => {
    const opt = document.createElement("option");
    opt.value = d; opt.textContent = d;
    sel.appendChild(opt);
  });
  const chosen = selectDomain && domains.includes(selectDomain) ? selectDomain : domains[0];
  sel.value = chosen;
  await setDomain(chosen);
}

async function setDomain(domain) {
  state.domain = domain;
  const config = await api(`/domains/${domain}/config`);
  state.config = config;
  renderConfigTab();
  renderPriceTemplate();
  $("#simTable tbody").innerHTML = "";
  $("#simKpis").innerHTML = "";
  $("#simExplainPanel").style.display = "none";
}

/* ---------------- Config tab ---------------- */
function renderConfigTab() {
  const c = state.config;
  $("#configMeta").innerHTML = `<p><strong>${c.entity.name || c.domain}</strong> — ${c.description}</p>
    <p class="muted">Currency/unit: ${c.currency} · Base price: ${c.base_price.mode} (${c.base_price.attribute || c.base_price.formula || c.base_price.value})</p>`;

  $("#attrTable tbody").innerHTML = c.attributes.map(a =>
    `<tr><td>${a.name}${a.enum ? ` <span class="muted">(${a.enum.join("/")})</span>` : ""}</td><td>${a.type}</td><td class="muted">${a.description || ""}</td></tr>`
  ).join("");

  $("#rulesTable tbody").innerHTML = [...c.rules].sort((a, b) => a.priority - b.priority).map(r =>
    `<tr${r.enabled ? "" : ' style="opacity:.4"'}>
      <td>${r.priority}</td>
      <td><strong>${r.id}</strong><div class="muted">${r.description || ""}</div></td>
      <td class="muted">${fmtCond(r.condition)}</td>
      <td>${fmtAdj(r.adjustment)}</td>
      <td>${(r.tags || []).map(t => `<span class="badge tag">${t}</span>`).join("")}</td>
    </tr>`
  ).join("");

  $("#constraintsTable tbody").innerHTML = (c.constraints || []).map(ct =>
    `<tr><td>${ct.type}</td><td>${ct.value}${ct.rounding ? " (" + ct.rounding + ")" : ""}</td></tr>`
  ).join("");

  $("#rawConfig").textContent = JSON.stringify(c, null, 2);

  loadVersions();
  loadConflicts();
}

async function loadVersions() {
  const { versions } = await api(`/domains/${state.domain}/versions`);
  $("#versionTable tbody").innerHTML = versions.map(v => `
    <tr class="${v.is_active ? "active-row" : ""}">
      <td>v${v.version}</td>
      <td>${v.is_active ? '<span class="badge ok">active</span>' : ""}</td>
      <td class="muted">${new Date(v.created_at).toLocaleString()}</td>
      <td class="muted">${v.note || ""}</td>
      <td>${v.is_active ? "" : `<button data-rollback="${v.version}">Activate</button>`}</td>
    </tr>`).join("");
  $all("[data-rollback]").forEach(btn => btn.addEventListener("click", async () => {
    await api(`/domains/${state.domain}/rollback/${btn.dataset.rollback}`, { method: "POST" });
    toast(`Rolled back to v${btn.dataset.rollback}`);
    const config = await api(`/domains/${state.domain}/config`);
    state.config = config;
    renderConfigTab();
  }));
}

async function loadConflicts() {
  const { conflicts } = await api(`/domains/${state.domain}/conflicts`);
  const panel = $("#conflictsPanel");
  if (!conflicts.length) {
    panel.innerHTML = '<span class="muted">No conflicts detected.</span>';
    return;
  }
  panel.innerHTML = conflicts.map(c => `
    <div class="conflict-card">
      <div class="kind">${c.kind}</div>
      <div>${c.rule_ids.join("  ↔  ")}</div>
      <div class="muted">${c.detail}</div>
    </div>`).join("");
}

/* ---------------- Explanation renderer (shared) ---------------- */
function renderExplanation(container, explanation) {
  const steps = [];
  steps.push({ label: "Base price", before: explanation.base_price, after: explanation.base_price, kind: "base" });
  explanation.applied_rules.forEach(r => {
    steps.push({ label: r.id, before: r.price_before, after: r.price_after, kind: "rule", detail: r.adjustment_summary, description: r.description });
  });
  explanation.constraints_applied.forEach(c => {
    steps.push({ label: `constraint: ${c.type}`, before: c.price_before, after: c.price_after, kind: "constraint", detail: c.detail });
  });

  const maxPrice = Math.max(...steps.map(s => Math.max(s.before, s.after)), 1);
  const waterfall = steps.map(s => {
    const delta = s.after - s.before;
    const barClass = delta > 0 ? "up" : (delta < 0 ? "down" : "");
    const widthPct = Math.max(2, (Math.max(s.before, s.after) / maxPrice) * 100);
    const deltaStr = s.kind === "base" ? "" : (delta >= 0 ? "+" : "") + delta.toFixed(2);
    return `<div class="trace-step">
      <div class="label">${s.label}${s.detail ? `<div class="muted">${s.detail}</div>` : ""}</div>
      <div class="bar-wrap"><div class="bar ${barClass}" style="width:${widthPct}%"></div></div>
      <div class="delta">${s.after.toFixed(2)} <span class="muted">${deltaStr}</span></div>
    </div>`;
  }).join("");

  const skipped = explanation.skipped_rules.length
    ? `<p class="muted">Skipped: ${explanation.skipped_rules.map(s => `${s.id} (${s.reason})`).join(", ")}</p>`
    : "";

  const conflicts = explanation.conflicts_detected && explanation.conflicts_detected.length
    ? explanation.conflicts_detected.map(c => `<div class="conflict-card"><div class="kind">${c.kind}</div><div>${c.rule_ids.join(" ↔ ")}</div><div class="muted">${c.detail}</div></div>`).join("")
    : "";

  const signals = explanation.signals && Object.keys(explanation.signals).length
    ? `<h3 style="font-size:13px;color:var(--text-dim)">ML-Assist Signals</h3><pre class="json">${JSON.stringify(explanation.signals, null, 2)}</pre>`
    : "";

  container.innerHTML = `
    <div class="kpi-row">
      <div class="kpi"><div class="num">${explanation.base_price.toFixed(2)}</div><div class="lbl">Base Price</div></div>
      <div class="kpi"><div class="num">${explanation.final_price.toFixed(2)}</div><div class="lbl">Final Price (${explanation.currency})</div></div>
      <div class="kpi"><div class="num">${explanation.applied_rules.length}</div><div class="lbl">Rules Applied</div></div>
      <div class="kpi"><div class="num">${explanation.conflicts_detected ? explanation.conflicts_detected.length : 0}</div><div class="lbl">Conflicts</div></div>
    </div>
    <div class="panel" style="background:var(--panel-2)">${waterfall}</div>
    ${skipped}
    ${conflicts}
    ${signals}
    <h3 style="font-size:13px;color:var(--text-dim)">Context Used</h3>
    <pre class="json">${JSON.stringify(explanation.context_used, null, 2)}</pre>
  `;
}

/* ---------------- Simulation tab ---------------- */
async function runSimulation() {
  try {
    const report = await api(`/simulate/${state.domain}`, { method: "POST", body: JSON.stringify({}) });
    $("#simKpis").innerHTML = `
      <div class="kpi"><div class="num">${report.total_cases}</div><div class="lbl">Cases</div></div>
      <div class="kpi"><div class="num" style="color:var(--good)">${report.passed}</div><div class="lbl">Passed</div></div>
      <div class="kpi"><div class="num" style="color:var(--bad)">${report.failed}</div><div class="lbl">Failed</div></div>
      <div class="kpi"><div class="num">${report.accuracy_pct}%</div><div class="lbl">Accuracy</div></div>
    `;
    $("#simTable tbody").innerHTML = report.results.map((r, i) => `
      <tr>
        <td>${r.case_name}</td>
        <td>${r.expected_price ?? "—"}</td>
        <td>${r.actual_price ?? "error"}</td>
        <td>${r.pass ? '<span class="badge ok">pass</span>' : '<span class="badge fail">fail</span>'}</td>
        <td><button data-explain="${i}">Explain</button></td>
      </tr>`).join("");
    $all("[data-explain]").forEach(btn => btn.addEventListener("click", () => {
      const r = report.results[btn.dataset.explain];
      $("#simExplainPanel").style.display = "block";
      if (r.explanation) renderExplanation($("#simExplainBody"), r.explanation);
      else $("#simExplainBody").innerHTML = `<p class="muted">Error: ${r.error}</p>`;
      $("#simExplainPanel").scrollIntoView({ behavior: "smooth" });
    }));
    toast(`Simulation complete: ${report.accuracy_pct}% accuracy`);
  } catch (e) {
    toast("Simulation failed: " + e.message, true);
  }
}

/* ---------------- Price explainer tab ---------------- */
function exampleValueFor(attr) {
  if (attr.enum) return attr.enum[0];
  const name = attr.name.toLowerCase();
  if (attr.type === "number") {
    if (name.includes("rate") || name.includes("ratio") || name.includes("index")) return 0.6;
    if (name.includes("price") || name.includes("fare")) return 100;
    if (name.includes("days") || name.includes("term")) return 14;
    if (name.includes("count") || name.includes("quantity")) return 3;
    if (name.includes("score")) return 700;
    return 10;
  }
  if (attr.type === "boolean") return false;
  return "";
}

function renderPriceTemplate() {
  const ctx = {};
  state.config.attributes.forEach(a => { ctx[a.name] = exampleValueFor(a); });
  $("#priceContext").value = JSON.stringify(ctx, null, 2);
  $("#priceResultSummary").innerHTML = "";
  $("#priceExplainBody").innerHTML = "";
}

async function computePrice() {
  let context;
  try { context = JSON.parse($("#priceContext").value); }
  catch (e) { toast("Invalid JSON context", true); return; }
  try {
    const result = await api(`/price/${state.domain}`, { method: "POST", body: JSON.stringify({ context }) });
    renderExplanation($("#priceExplainBody"), result);
    $("#priceResultSummary").innerHTML = "";
    toast(`Priced at ${result.final_price} ${result.currency}`);
  } catch (e) {
    toast("Pricing failed: " + e.message, true);
  }
}

/* ---------------- Audit tab ---------------- */
async function loadAudit() {
  const { entries } = await api(`/audit?limit=50`);
  $("#auditTable tbody").innerHTML = entries.map((e, i) => `
    <tr>
      <td class="muted">${new Date(e.created_at).toLocaleString()}</td>
      <td>${e.domain}</td>
      <td>v${e.config_version}</td>
      <td>${e.final_price}</td>
      <td><button data-audit-explain="${i}">Explain</button></td>
    </tr>`).join("");
  $all("[data-audit-explain]").forEach(btn => btn.addEventListener("click", () => {
    const e = entries[btn.dataset.auditExplain];
    $("#tab-audit").insertAdjacentHTML("beforeend", "");
    const panel = document.createElement("div");
    panel.className = "panel";
    panel.innerHTML = "<h2>Explanation</h2>";
    const body = document.createElement("div");
    panel.appendChild(body);
    renderExplanation(body, e.response);
    const old = $("#audit-explain-panel");
    if (old) old.remove();
    panel.id = "audit-explain-panel";
    $("#tab-audit").appendChild(panel);
    panel.scrollIntoView({ behavior: "smooth" });
  }));
}

/* ---------------- Copilot tab ---------------- */
let lastNlResult = null;
async function generateNlRule() {
  const text = $("#nlInput").value.trim();
  if (!text) return;
  try {
    const result = await api(`/copilot/nl-to-rule?domain=${state.domain}`, { method: "POST", body: JSON.stringify({ text }) });
    lastNlResult = result;
    $("#nlResultPanel").style.display = "block";
    const confColor = result.confidence >= 0.8 ? "var(--good)" : (result.confidence >= 0.5 ? "var(--warn)" : "var(--bad)");
    $("#nlResultBody").innerHTML = `
      <p>Confidence: <strong style="color:${confColor}">${(result.confidence * 100).toFixed(0)}%</strong></p>
      ${result.warnings.length ? `<div class="conflict-card"><div class="kind">Review</div>${result.warnings.map(w => `<div>${w}</div>`).join("")}</div>` : ""}
      <pre class="json">${JSON.stringify(result.rule, null, 2)}</pre>
    `;
  } catch (e) {
    toast("Copilot failed: " + e.message, true);
  }
}

async function addNlRuleAsDraft() {
  if (!lastNlResult) return;
  const config = JSON.parse(JSON.stringify(state.config));
  config.rules.push(lastNlResult.rule);
  try {
    const res = await api(`/domains/${state.domain}/config`, {
      method: "POST",
      body: JSON.stringify({ config, note: "NL copilot: " + lastNlResult.source_text, activate: false }),
    });
    toast(`Draft v${res.version} created (not activated). Conflicts: ${res.conflicts_detected.length}`);
    loadVersions();
  } catch (e) {
    toast("Failed to save draft: " + e.message, true);
  }
}

/* ---------------- Add domain modal ---------------- */
function initAddDomainModal() {
  const modal = $("#addDomainModal");
  $("#addDomainBtn").addEventListener("click", () => { modal.classList.remove("hidden"); });
  $("#cancelAddDomainBtn").addEventListener("click", () => { modal.classList.add("hidden"); });
  $("#loadBankingSampleBtn").addEventListener("click", () => {
    $("#newDomainJson").value = JSON.stringify(BANKING_SAMPLE, null, 2);
  });
  $("#confirmAddDomainBtn").addEventListener("click", async () => {
    let config;
    try { config = JSON.parse($("#newDomainJson").value); }
    catch (e) { toast("Invalid JSON", true); return; }
    const domain = config.domain;
    if (!domain) { toast("Config must include a 'domain' field", true); return; }
    try {
      const res = await api(`/domains/${domain}/config`, {
        method: "POST",
        body: JSON.stringify({ config, note: "added live via UI", activate: true, created_by: "demo-user" }),
      });
      toast(`Domain '${domain}' added and activated (v${res.version}) — no engine changes.`);
      modal.classList.add("hidden");
      await loadDomains(domain);
    } catch (e) {
      toast("Failed to add domain: " + e.message, true);
    }
  });
}

/* ---------------- Wiring ---------------- */
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initAddDomainModal();
  $("#domainSelect").addEventListener("change", (e) => setDomain(e.target.value));
  $("#runSimBtn").addEventListener("click", runSimulation);
  $("#computePriceBtn").addEventListener("click", computePrice);
  $("#refreshAuditBtn").addEventListener("click", loadAudit);
  $("#nlGenerateBtn").addEventListener("click", generateNlRule);
  $("#nlAddBtn").addEventListener("click", addNlRuleAsDraft);
  loadDomains();
});
