// Ontic 参考前端（原生 JS）。
// UI 交互逻辑以 foundry_docs/design/ui-logic 下的 73 个 Foundry 原型为依据对齐：
//  - 首页架构图 86002467 · 对象类型详情(4178460/89785808) · 属性面板(45104673)
//  - 对象集过滤(72856442) · 链接辐射图(4178460) · 管道数据流(10096559/68855017)
//  - 应用列表(94936832) · AIP 分析师(38163447) · 服务日志(18802464)
//  - 通知中心(74849331) · 新建启动器(9028755)
const API = "";
let TOKEN = localStorage.getItem("of_token") || "";
let ME = null;
let CUR_TYPE = null;
let CUR_MODULE = "home";

// 顶部全局模块导航（对齐 Foundry 顶部导航 + 各模块次级导航 89785808/26175659/33314150/74849331）
const MODULES = [
  { id: "home", label: "🏠 首页" },
  { id: "ontology", label: "本体" },
  { id: "data", label: "数据" },
  { id: "pipeline", label: "管道" },
  { id: "aip", label: "AIP" },
  { id: "apps", label: "应用" },
  { id: "developer", label: "开发者" },
  { id: "admin", label: "管理", adminOnly: true },
];

async function renderModnav() {
  const nav = document.getElementById("modnav");
  nav.innerHTML = MODULES.filter(m => !(m.adminOnly && !(ME && ME.role === "admin"))).map(m =>
    `<span class="mod ${m.id === CUR_MODULE ? "on" : ""}" onclick="setModule('${m.id}')">${m.label}</span>`).join("");
}

async function setModule(id) {
  CUR_MODULE = id;
  await renderModnav();
  await loadSidebar();
  if (id === "home") await openHome();
  else if (id === "ontology") await openOntology();
  else if (id === "data") await openData();
  else if (id === "pipeline") await openPipelines();
  else if (id === "aip") await openAgent();
  else if (id === "apps") await openApps();
  else if (id === "notify") await openNotifications();
  else if (id === "developer") await openDev();
  else if (id === "admin") await openAdmin();
}

// ---- Omnibar 全局搜索（对齐 Foundry 顶部搜索） ----
let OMNI = null;
async function omnibarData() {
  if (!OMNI) OMNI = { types: await api("/api/ontology/stats"), apps: await api("/api/apps"), pls: await api("/api/pipelines") };
  return OMNI;
}
function omnibarSearch() {
  const q = document.getElementById("omnibar").value.trim().toLowerCase();
  const list = document.getElementById("omnibar-list");
  if (!q) { list.classList.add("hidden"); return; }
  omnibarData().then(d => {
    const res = [];
    d.types.filter(t => (t.name + " " + t.id).toLowerCase().includes(q)).slice(0, 5)
      .forEach(t => res.push({ icon: "🧩", label: t.name, sub: `对象类型 · ${t.count} 对象`, go: `openType('${t.id}')` }));
    d.apps.filter(a => (a.name + " " + a.id).toLowerCase().includes(q)).slice(0, 5)
      .forEach(a => res.push({ icon: "📱", label: a.name, sub: `应用 · ${a.type}`, go: `openAppView('${a.id}')` }));
    d.pls.filter(p => (p.name + " " + p.id).toLowerCase().includes(q)).slice(0, 5)
      .forEach(p => res.push({ icon: "⚙️", label: p.id, sub: "管道", go: "openPipelines()" }));
    list.innerHTML = (res.length ? res : [{ icon: "", label: "无匹配", sub: "", go: "omnibarHide()" }]).map(r =>
      `<div class="omni-item" onclick="${r.go};document.getElementById('omnibar').value='';omnibarHide()">${r.icon} <b>${esc(r.label)}</b> <span class="muted">${esc(r.sub)}</span></div>`).join("");
    list.classList.remove("hidden");
  });
}
function omnibarKey(e) {
  if (e.key === "Escape") omnibarHide();
  if (e.key === "Enter") { const f = document.querySelector("#omnibar-list .omni-item"); if (f) f.click(); }
}
function omnibarHide() { document.getElementById("omnibar-list").classList.add("hidden"); }

// 通知铃铛未读数
async function updateBell() {
  try {
    const acts = await api("/api/activity");
    const badge = document.getElementById("bellBadge");
    badge.textContent = acts.length > 99 ? "99+" : acts.length;
    badge.classList.toggle("hidden", acts.length === 0);
  } catch (e) {}
}

function authHeaders() {
  return { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}` };
}
async function api(path, opts = {}) {
  const r = await fetch(API + path, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
  if (r.status === 401) { logout(); throw new Error("未授权"); }
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.json();
}
function show(id) { document.getElementById(id).classList.remove("hidden"); }
function hide(id) { document.getElementById(id).classList.add("hidden"); }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function opOptionsHTML(sel) {
  const ops = [["eq","="],["ne","≠"],["gt",">"],["gte","≥"],["lt","<"],["lte","≤"],["contains","包含"],["isNull","为空"]];
  return ops.map(([v,t]) => `<option value="${v}" ${v===sel?"selected":""}>${t}</option>`).join("");
}
function tabBar(active, tabs) {
  return `<div class="tabs">` + tabs.map(t =>
    `<span class="tab ${t.id===active?"on":""}" data-tab="${t.id}" onclick="switchTab('${t.id}')">${t.label}</span>`).join("") + `</div>`;
}

// ---------------- 登录 / 启动 ----------------
async function login() {
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  document.getElementById("loginErr").textContent = "";
  try {
    const t = await api("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
    TOKEN = t.access_token; localStorage.setItem("of_token", TOKEN);
    await enterApp();
  } catch (e) { document.getElementById("loginErr").textContent = e.message; }
}
function logout() { TOKEN = ""; localStorage.removeItem("of_token"); show("login"); hide("app"); }

async function enterApp() {
  hide("login"); show("app");
  ME = await api("/api/me");
  document.getElementById("who").textContent = `${ME.username} · ${ME.role}`;
  await renderModnav();
  await loadSidebar();
  await updateBell();
  await openHome();
}

// 侧栏 = 当前模块的上下文导航（不再平铺全部内容）
async function loadSidebar() {
  const sb = document.getElementById("sidebar");
  if (CUR_MODULE === "ontology") {
    const stats = await api("/api/ontology/stats");
    let html = `<h3>对象类型 (${stats.length})</h3>`;
    stats.forEach(t => {
      html += `<div class="item type" onclick="openType('${t.id}')">
          <span class="tname">${esc(t.name)}</span><span class="badge">${t.count}</span></div>`;
      if (t.actions.length) {
        html += `<div class="sub">` + t.actions.map(a =>
          `<div class="item sub-i" onclick="openAction('${a.id}')">${esc(a.name)}</div>`).join("") + `</div>`;
      }
    });
    html += `<h3>开发者</h3><div class="item" onclick="openOsdk()">⬇ OSDK 代码生成</div>`;
    sb.innerHTML = html;
  } else if (CUR_MODULE === "data") {
    const conns = await api("/api/connectors");
    sb.innerHTML = `<h3>数据资产</h3><div class="item" onclick="openData()">📚 数据集列表</div>
      <div class="item" onclick="openLineage()">🧬 数据血缘</div>
      <div class="item" onclick="openSql()">🗄️ SQL 工作台</div>
      <div class="item" onclick="openGeo()">📍 空间查询</div>
      <div class="item" onclick="openMedia()">🖼️ 媒体</div>
      <h3>连接器 (${conns.length})</h3>` +
      conns.map(c => `<div class="item" onclick="openConnectors()">🔌 ${esc(c.name)}</div>`).join("");
  } else if (CUR_MODULE === "pipeline") {
    const pls = await api("/api/pipelines");
    sb.innerHTML = `<h3>管道 (${pls.length})</h3>` +
      pls.map(p => `<div class="item" onclick="openPipelines()">⚙️ ${esc(p.id)}</div>`).join("") +
      `<h3>函数库</h3><div class="item" onclick="openPipelines()">fx pb-functions</div>`;
  } else if (CUR_MODULE === "aip") {
    sb.innerHTML = `<h3>AIP</h3>
      <div class="item" onclick="openAgent()">💬 分析师</div>
      <div class="item" onclick="openUsage()">📊 模型用量</div>
      <div class="item" onclick="openModelCatalog()">🧠 模型目录</div>
      <div class="item" onclick="openEvals()">🧪 评估套件</div>
      <div class="item" onclick="openPlayground()">🆚 模型对比</div>
      <div class="item" onclick="openDocIntel()">📄 文档智能</div>`;
  } else if (CUR_MODULE === "apps") {
    const apps = await api("/api/apps");
    sb.innerHTML = `<h3>构建的应用 (${apps.length})</h3>` +
      apps.map(a => `<div class="item" onclick="openAppView('${esc(a.id)}')">📱 ${esc(a.name)}</div>`).join("") +
      `<h3>其他</h3><div class="item" onclick="openApps()">全部应用</div>`;
  } else if (CUR_MODULE === "notify") {
    const acts = await api("/api/activity");
    const kinds = ["全部", ...new Set(acts.map(a => a.kind))];
    sb.innerHTML = `<h3>通知分类</h3>` +
      kinds.map(k => `<div class="item" onclick="openNotifications('${esc(k)}')">${esc(k)}</div>`).join("");
  } else if (CUR_MODULE === "developer") {
    // 开发者模块：主区 tabs 已足够，侧栏不重复导航
    sb.innerHTML = `<h3>开发者</h3><div class="item" onclick="openDev()">🧑‍💻 控制台</div>`;
  } else if (CUR_MODULE === "admin") {
    sb.innerHTML = `<h3>管理</h3><div class="item" onclick="openAdmin()">🛡️ 用户与授权</div>
      <div class="item" onclick="openSecurity()">🔐 安全治理</div>
      <div class="item" onclick="openOps()">📈 运维监控</div>
      <div class="item" onclick="openNotifications()">📜 活动日志</div>`;
  } else {
    sb.innerHTML = `<h3>快速开始</h3>
      <div class="item" onclick="setModule('ontology')">本体</div>
      <div class="item" onclick="setModule('data')">数据</div>
      <div class="item" onclick="setModule('pipeline')">管道</div>
      <div class="item" onclick="setModule('aip')">AIP</div>
      <div class="item" onclick="setModule('apps')">应用</div>`;
  }
}

// 本体模块落地页（数据资产式列表，33314150）：对象类型 + 对象数 + 动作数
async function openOntology() {
  const stats = await api("/api/ontology/stats");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🧩 本体（Ontology）</h2>
    <p class="muted">对象类型、动作与链接的结构化定义层。点击类型进入详情。</p>
    <table><thead><tr><th>对象类型</th><th>对象数</th><th>动作</th><th>描述</th></tr></thead><tbody>` +
    stats.map(t => `<tr><td><a onclick="openType('${t.id}')" class="link">${esc(t.name)}</a></td>
      <td>${t.count}</td><td>${t.actions.length}</td><td class="muted">${esc(t.description || "")}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

// 数据模块落地页：数据资产列表（33314150 NAME/LAST UPDATED/TAGS 风格）
async function openData() {
  const stats = await api("/api/ontology/stats");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📚 数据资产</h2>
    <div class="row"><button onclick="openConnectors()">＋ 接入数据（连接器）</button></div>
    <table><thead><tr><th>NAME</th><th>对象数</th><th>动作</th><th>TAGS</th></tr></thead><tbody>` +
    stats.map(t => `<tr><td><a onclick="openType('${t.id}')" class="link">📄 ${esc(t.name)}</a></td>
      <td>${t.count}</td><td>${t.actions.length}</td><td>${t.actions.length ? '<span class="tag">CRUD</span>' : '<span class="tag">dataset</span>'}</td></tr>`).join("") +
    `</tbody></table></div>`;
}

// ---------------- 首页（工作台：统计 / 快捷入口 / 最近对象 / 最近活动） ----------------
async function openHome() {
  const [stats, apps, pls, acts] = await Promise.all([
    api("/api/ontology/stats"),
    api("/api/apps"),
    api("/api/pipelines"),
    api("/api/activity"),
  ]);
  let approvals = [];
  if (ME && ME.role === "admin") { try { approvals = await api("/api/security/approvals?status=pending"); } catch(e){} }
  const total = stats.reduce((s, t) => s + t.count, 0);
  const top = [...stats].sort((a, b) => b.count - a.count).slice(0, 6);
  const c = document.getElementById("content");
  c.innerHTML = `
    <div class="panel">
      <h2>👋 你好，${esc(ME.username)}</h2>
      <p class="muted">角色 ${esc(ME.role)} · 平台共 ${stats.length} 个对象类型 / ${total} 个对象 / ${apps.length} 个应用 / ${pls.length} 个管道</p>
      <div class="row" style="margin-top:10px;">
        <button onclick="openLauncher()">＋ 新建</button>
        <button class="ghost" onclick="openOntology()">🧩 本体</button>
        <button class="ghost" onclick="openConnectors()">🔌 接入数据</button>
        <button class="ghost" onclick="openPipelines()">⚙️ 管道</button>
        <button class="ghost" onclick="openAgent()">💬 AIP</button>
        <button class="ghost" onclick="openApps()">📱 应用</button>
      </div>
      ${approvals.length ? `<div class="warn-banner">⏳ 有 ${approvals.length} 条审批待处理 → <a class="link" onclick="openSecurity()">去处理</a></div>` : ""}
    </div>
    <div class="stat-row">
      <div class="stat"><div class="stat-n">${stats.length}</div><div class="stat-l">对象类型</div></div>
      <div class="stat"><div class="stat-n">${total}</div><div class="stat-l">对象总数</div></div>
      <div class="stat"><div class="stat-n">${apps.length}</div><div class="stat-l">应用</div></div>
      <div class="stat"><div class="stat-n">${pls.length}</div><div class="stat-l">管道</div></div>
      <div class="stat"><div class="stat-n">${approvals.length}</div><div class="stat-l">待审批</div></div>
    </div>
    <div class="home-grid">
      <div class="panel"><h3>📚 对象类型速览</h3>
        <table><thead><tr><th>对象类型</th><th>对象数</th><th>动作</th></tr></thead><tbody>` +
        top.map(t => `<tr><td><a class="link" onclick="openType('${t.id}')">${esc(t.name)}</a></td><td>${t.count}</td><td>${t.actions.length}</td></tr>`).join("") +
        `</tbody></table></div>
      <div class="panel"><h3>🔔 最近活动</h3>
        <div class="act-list">` +
        (acts.length ? acts.slice(0, 8).map(a => `<div class="act-row"><span class="tag">${esc(a.kind)}</span><span>${esc(a.message)}</span><span class="muted act-ts">${esc((a.ts||"").slice(0,16).replace("T"," "))}</span></div>`).join("")
          : `<p class="muted">暂无活动。</p>`) +
        `</div></div>
    </div>`;
}

// ---------------- 对象类型详情（4178460 / 89785808） ----------------
async function openType(id) {
  if (!id) return;
  CUR_TYPE = id;
  const ot = await api(`/api/ontology/object-types/${id}`);
  const props = JSON.parse(ot.properties);
  const c = document.getElementById("content");
  c.innerHTML = `
    <div class="panel">
      <div class="row" style="justify-content:space-between;">
        <div><h2>${esc(ot.name)}</h2><p class="muted">${esc(ot.description || "")} · 主键 ${esc(ot.primary_key)} · 表 ${esc(ot.backing_table)}</p></div>
        <span class="tag ok">Active</span>
      </div>
      ${tabBar("overview", [
        {id:"overview",label:"概览"},{id:"properties",label:"属性"},{id:"actions",label:"动作"},
        {id:"links",label:"链接"},{id:"data",label:"数据"}])}
      <div id="tab_body"></div>
    </div>`;
  await switchTab("overview");
}

async function switchTab(tab) {
  if (!CUR_TYPE) return;
  document.querySelectorAll(".tab").forEach(t => t.classList.toggle("on", t.dataset.tab === tab));
  if (tab === "overview") await renderOverview();
  else if (tab === "properties") await renderProperties();
  else if (tab === "actions") await renderActions();
  else if (tab === "links") await renderLinks();
  else if (tab === "data") await renderData();
}

async function renderOverview() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties);
  let total = 0;
  try { total = (await api(`/api/ontology/object-types/${CUR_TYPE}/count`, { method:"POST", body:"{}" })).total; } catch(e){}
  const acts = (await api("/api/ontology/actions")).filter(a => a.object_type === CUR_TYPE);
  const links = await api(`/api/ontology/object-types/${CUR_TYPE}/links`);
  const box = document.getElementById("tab_body");
  box.innerHTML = `
    <div class="stat-row">
      <div class="stat"><div class="stat-n">${total}</div><div class="stat-l">对象数</div></div>
      <div class="stat"><div class="stat-n">${props.length}</div><div class="stat-l">属性</div></div>
      <div class="stat"><div class="stat-n">${acts.length}</div><div class="stat-l">动作</div></div>
      <div class="stat"><div class="stat-n">${links.length}</div><div class="stat-l">链接类型</div></div>
    </div>
    <h3>General information</h3>
    <table><tbody>
      <tr><td>状态</td><td><span class="tag ok">Active</span></td></tr>
      <tr><td>主键</td><td>${esc(ot.primary_key)}</td></tr>
      <tr><td>Backing table</td><td>${esc(ot.backing_table)}</td></tr>
      <tr><td>聚合使用量</td><td>${total} 次读取</td></tr>
    </tbody></table>
    <h3>Usage over time</h3>
    <div class="spark">${sparkline()}</div>`;
}

// 属性面板（45104673）
async function renderProperties() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties);
  const box = document.getElementById("tab_body");
  box.innerHTML = `
    <h3>PROPERTIES</h3>
    <table><thead><tr><th>Key</th><th>标题</th><th>类型</th><th>操作</th></tr></thead><tbody id="prop_rows"></tbody></table>
    <div class="row" style="margin-top:10px;">
      <button class="ghost" onclick="addPropRow()">＋ Add property</button>
    </div>
    <div id="prop_add"></div>`;
  const tb = document.getElementById("prop_rows");
  tb.innerHTML = props.map(p => `<tr>
      <td>${esc(p.key)}</td><td>${esc(p.title)} ${p.sensitive?'<span class="tag" style="color:var(--warn)">🔒 敏感</span>':''}</td><td>${esc(p.type)}</td>
      <td>${p.key===ot.primary_key ? '<span class="muted">主键</span>' : `<button class="ghost sm" onclick="removeProp('${esc(p.key)}')">🗑 删除</button>`}</td>
    </tr>`).join("");
}
function addPropRow() {
  const box = document.getElementById("prop_add");
  box.innerHTML = `<div class="row">
    <input id="np_key" placeholder="字段key" style="width:140px;"/>
    <select id="np_type"><option value="string">string</option><option value="integer">integer</option><option value="double">double</option><option value="boolean">boolean</option></select>
    <input id="np_title" placeholder="标题" style="flex:1;"/>
    <label style="display:flex;align-items:center;gap:4px;font-size:13px;"><input id="np_sensitive" type="checkbox"/>敏感(脱敏)</label>
    <button onclick="submitProp()">保存</button></div>`;
}
async function submitProp() {
  const key = document.getElementById("np_key").value.trim();
  const type = document.getElementById("np_type").value;
  const title = document.getElementById("np_title").value.trim();
  const sensitive = document.getElementById("np_sensitive")?.checked || false;
  if (!key) { alert("字段key必填"); return; }
  try { await api(`/api/ontology/object-types/${CUR_TYPE}/properties`, { method:"POST", body: JSON.stringify({ key, type, title, sensitive }) }); }
  catch(e){ alert(e.message); return; }
  await renderProperties();
}
async function removeProp(key) {
  if (!confirm(`删除属性 ${key}？该列数据也将从 backing table 移除。`)) return;
  try { await api(`/api/ontology/object-types/${CUR_TYPE}/properties/${key}`, { method:"DELETE" }); }
  catch(e){ alert(e.message); return; }
  await renderProperties();
}

// 动作面板
async function renderActions() {
  const acts = (await api("/api/ontology/actions")).filter(a => a.object_type === CUR_TYPE);
  const box = document.getElementById("tab_body");
  if (!acts.length) { box.innerHTML = `<p class="muted">该类型暂无动作。</p>`; return; }
  box.innerHTML = `<table><thead><tr><th>动作</th><th>操作</th><th>描述</th><th></th></tr></thead><tbody>` +
    acts.map(a => `<tr><td>${esc(a.name)}</td><td><span class="tag">${esc(a.operation)}</span></td><td class="muted">${esc(a.description||"")}</td>
      <td><button class="ghost sm" onclick="openAction('${a.id}')">执行</button></td></tr>`).join("") + `</tbody></table>`;
}

// 链接面板（辐射图 4178460 + 图探索 M2）
async function renderLinks() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const links = await api(`/api/ontology/object-types/${CUR_TYPE}/links`);
  const types = await api("/api/ontology/object-types");
  const box = document.getElementById("tab_body");
  box.innerHTML = `
    <h3>LINK TYPES（辐射图）</h3>
    <div id="radial"></div>
    <details><summary>定义新链接</summary>
      <div class="row">
        <input id="lk_id" placeholder="链接ID" style="flex:1;min-width:140px;"/>
        <input id="lk_name" placeholder="显示名"/>
        <select id="lk_target">${types.map(t=>`<option value="${t.id}">${esc(t.name)} (${t.id})</option>`).join("")}</select>
        <input id="lk_fk" placeholder="源表外键列(引用目标PK)"/>
        <button onclick="createLink('${CUR_TYPE}')">创建</button>
      </div>
      <p class="muted">方向：本类型(source) 经外键列指向 目标类型(target)。</p>
    </details>
    <h3>图探索</h3>
    <div class="row">
      <input id="g_id" placeholder="起始对象ID"/>
      <input id="g_hops" placeholder="跳数(默认2)" value="2" style="width:90px;"/>
      <button onclick="exploreGraph('${CUR_TYPE}')">探索关联图</button>
    </div>
    <div id="g_out"></div>`;
  // 辐射图：中心=当前类型，周围=关联类型
  const W=680,H=300,cx=340,cy=150;
  const others = links.map(l => l.source_type===CUR_TYPE ? l.target_type : l.source_type);
  const uniq = [...new Set(others)];
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;">`;
  svg += `<circle cx="${cx}" cy="${cy}" r="34" fill="#4f8cff"/><text x="${cx}" y="${cy+4}" fill="#fff" font-size="11" text-anchor="middle">${esc(ot.name)}</text>`;
  uniq.forEach((t,i) => {
    const a = (2*Math.PI*i)/Math.max(uniq.length,1) - Math.PI/2;
    const x = cx + 120*Math.cos(a), y = cy + 100*Math.sin(a);
    svg += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#3ecf8e" stroke-width="1.5"/>`;
    svg += `<circle cx="${x}" cy="${y}" r="26" fill="#171a21" stroke="#3ecf8e"/><text x="${x}" y="${y+4}" fill="#e6e9ef" font-size="10" text-anchor="middle">${esc(t)}</text>`;
  });
  svg += `</svg><p class="muted">${uniq.length} 个关联对象类型</p>`;
  document.getElementById("radial").innerHTML = svg;
}
async function createLink(srcId) {
  const id = document.getElementById("lk_id").value.trim();
  const name = document.getElementById("lk_name").value.trim();
  const target = document.getElementById("lk_target").value;
  const fk = document.getElementById("lk_fk").value.trim();
  if (!id || !target || !fk) { alert("链接ID/目标类型/外键列必填"); return; }
  await api("/api/ontology/link-types", { method:"POST", body: JSON.stringify({ id, name:name||id, source_type:srcId, target_type:target, source_fk:fk }) });
  await renderLinks();
}
async function exploreGraph(id) {
  const oid = document.getElementById("g_id").value.trim();
  const hops = parseInt(document.getElementById("g_hops").value || "2", 10);
  if (!oid) { alert("请输入起始对象ID"); return; }
  const g = await api(`/api/ontology/object-types/${id}/${oid}/graph?hops=${hops}`);
  const nodes = g.nodes, edges = g.edges;
  const W=720,H=360,cx=W/2,cy=H/2,n=nodes.length||1;
  const pos = nodes.map((nd,i)=>{const a=(2*Math.PI*i)/n;return {x:cx+130*Math.cos(a),y:cy+120*Math.sin(a),nd};});
  const byKey={}; pos.forEach(p=>byKey[`${p.nd.type}#${p.nd.id}`]=p);
  let svg=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;">`;
  edges.forEach(e=>{const s=byKey[e.source],t=byKey[e.target];if(s&&t)svg+=`<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="#4f8cff" stroke-width="1.5" opacity="0.6"/>`;});
  pos.forEach(p=>{svg+=`<circle cx="${p.x}" cy="${p.y}" r="6" fill="#3ecf8e"/><text x="${p.x+9}" y="${p.y+4}" fill="#e6e9ef" font-size="11">${esc(p.nd.label)}</text>`;});
  svg+=`</svg><p class="muted">节点 ${nodes.length} · 边 ${edges.length} · 跳数 ${g.hops}</p>`;
  document.getElementById("g_out").innerHTML = svg;
}

// 数据面板：对象集过滤器（72856442）
async function renderData() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties);
  const box = document.getElementById("tab_body");
  box.innerHTML = `
    <h3>对象集查询（下推到数据平面）</h3>
    <div class="filter-builder">
      <p>Keep <b>${esc(ot.name)}</b> that match
        <select id="f_logic"><option value="and">all</option><option value="or">any</option></select> of:</p>
      <div id="f_rows"></div>
      <div class="row"><button class="ghost" onclick="addFilterRow()">＋ Add a filter</button>
        <button onclick="applyFilters()">Apply filters</button></div>
    </div>
    <div id="q_out"></div>`;
  addFilterRow(props);
}
function addFilterRow(props) {
  props = props || [];
  const ot = null;
  const box = document.getElementById("f_rows");
  if (!box) return;
  const row = document.createElement("div");
  row.className = "row f-row";
  row.innerHTML = `<select class="f_field">${props.map(p=>`<option value="${p.key}">${esc(p.title)}</option>`).join("")}</select>
    <select class="f_op">${opOptionsHTML("eq")}</select>
    <input class="f_val" placeholder="值"/>
    <button class="ghost sm" onclick="this.parentNode.remove()">✕</button>`;
  box.appendChild(row);
}
async function applyFilters() {
  const logic = document.getElementById("f_logic").value;
  const props = JSON.parse((await api(`/api/ontology/object-types/${CUR_TYPE}`)).properties);
  const conditions = [];
  document.querySelectorAll("#f_rows .f-row").forEach(r => {
    const field = r.querySelector(".f_field").value;
    const op = r.querySelector(".f_op").value;
    const val = r.querySelector(".f_val").value;
    if (op === "isNull" || val !== "") conditions.push({ field, op, value: val });
  });
  const where = conditions.length ? { op: logic, conditions } : { op: "and", conditions: [] };
  const [res, cnt] = await Promise.all([
    api(`/api/ontology/object-types/${CUR_TYPE}/query`, { method:"POST", body: JSON.stringify({ where, limit:100, offset:0 }) }),
    api(`/api/ontology/object-types/${CUR_TYPE}/count`, { method:"POST", body: JSON.stringify({ where }) }),
  ]);
  const rows = res.rows;
  const box = document.getElementById("q_out");
  if (!rows.length) { box.innerHTML = `<p class="muted">无结果</p>`; return; }
  const cols = Object.keys(rows[0]);
  let h = `<p class="muted">本页 ${rows.length} 行 · 共 ${cnt.total} 个对象</p><table><thead><tr>` +
    cols.map(c=>`<th>${c}</th>`).join("") + `</tr></thead><tbody>`;
  rows.forEach(r => h += "<tr>" + cols.map(c=>`<td>${esc(r[c])}</td>`).join("") + "</tr>");
  h += `</tbody></table>`;
  box.innerHTML = h;
}
function sparkline() {
  const pts = Array.from({length:12}, (_,i)=> 40 + Math.round(30*Math.abs(Math.sin(i/2))));
  const max = Math.max(...pts);
  const w=600,h=70, step=w/(pts.length-1);
  const d = pts.map((v,i)=>`${i===0?"M":"L"}${(i*step).toFixed(1)},${(h - v*(h-10)/max).toFixed(1)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:90px;"><path d="${d}" fill="none" stroke="#4f8cff" stroke-width="2"/></svg>`;
}

// ---------------- 动作执行 ----------------
async function openAction(id) {
  const acts = await api("/api/ontology/actions");
  const a = acts.find(x => x.id === id);
  const params = JSON.parse(a.parameters);
  const c = document.getElementById("content");
  c.innerHTML = `
    <div class="panel"><h2>${esc(a.name)}</h2><p class="muted">${esc(a.description||"")} · 操作: ${esc(a.operation)}</p>
      <div id="act_form">${params.map(p=>`<div class="row"><label>${esc(p.name)}${p.required?" *":""}</label><input id="p_${p.name}" placeholder="${esc(p.type)}"/></div>`).join("")}</div>
      <button onclick="runAction('${id}')">执行动作</button>
      <div id="act_out"></div></div>`;
}
async function runAction(id) {
  const acts = await api("/api/ontology/actions");
  const a = acts.find(x => x.id === id);
  const params = JSON.parse(a.parameters);
  const body = {};
  params.forEach(p => { const v = document.getElementById(`p_${p.name}`).value; if (v !== "") body[p.name] = v; });
  const res = await api(`/api/ontology/actions/${id}/execute`, { method:"POST", body: JSON.stringify({ params: body }) });
  document.getElementById("act_out").innerHTML = `<pre>${JSON.stringify(res.detail, null, 2)}</pre>`;
  await loadSidebar();
}

// ---------------- OSDK ----------------
async function openOsdk() {
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>OSDK 代码生成</h2>
    <div class="row"><button onclick="fetchOsdk('python')">Python</button><button onclick="fetchOsdk('typescript')">TypeScript</button></div>
    <pre id="osdk_out">点击上方按钮生成类型安全客户端代码。</pre></div>`;
}
async function fetchOsdk(lang) {
  const r = await api(`/api/ontology/osdk/${lang}`);
  document.getElementById("osdk_out").textContent = r.code;
}

// ---------------- 应用（94936832 应用列表 + 模板 + 版本对比 17326356） ----------------
async function openApps() {
  const [apps, types, acts] = await Promise.all([api("/api/apps"), api("/api/ontology/object-types"), api("/api/ontology/actions")]);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📱 应用（Applications）</h2>
    <div class="row" style="justify-content:space-between;"><span class="muted">构建 Form / Dashboard / View / Workflow 四类应用，或打开自动生成的 CRUD 应用。</span></div>
    <h3>推荐模板</h3>
    <div class="tpl-row">
      <div class="tpl"><div class="tpl-t">📊 Dashboard</div><div class="tpl-d">指标卡 + 分组聚合，无代码</div><button class="ghost sm" onclick="showAppBuild('dashboard')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">📝 Form</div><div class="tpl-d">动作表单，直连 Action</div><button class="ghost sm" onclick="showAppBuild('form')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">🔀 Workflow</div><div class="tpl-d">多步动作编排</div><button class="ghost sm" onclick="showAppBuild('workflow')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">🔎 View</div><div class="tpl-d">对象集只读视图</div><button class="ghost sm" onclick="showAppBuild('view')">＋ Create</button></div>
    </div>
    <div id="app_build"></div>
    <h3>构建的应用</h3>
    <table><thead><tr><th>名称</th><th>类型</th><th>对象类型</th><th>更新时间</th><th></th></tr></thead><tbody>` +
    (apps.length ? apps.map(a => `<tr><td>${esc(a.name)}</td><td><span class="tag">${esc(a.type)}</span></td><td>${esc(a.object_type)}</td><td class="muted">${esc(a.updated)}</td>
      <td><button class="ghost sm" onclick="openAppView('${esc(a.id)}')">打开</button>
          <button class="ghost sm" onclick="openAppVersions('${esc(a.id)}')">版本</button>
          <button class="ghost sm" onclick="deleteApp('${esc(a.id)}')">删除</button></td></tr>`).join("")
        : `<tr><td colspan="5" class="muted">暂无构建的应用。</td></tr>`) +
    `</tbody></table>
    <h3>自动生成的应用（每个对象类型一个 CRUD 应用）</h3>
    <div class="row">${types.map(t => `<span class="tag" onclick="openApp('${t.id}')" style="cursor:pointer;border-color:var(--accent);">📱 ${esc(t.name)}</span>`).join("")}</div>
    </div>`;
}
function showAppBuild(type) {
  const box = document.getElementById("app_build");
  box.innerHTML = `<div class="panel sm"><h3>新建 ${type} 应用</h3>
    <div class="row"><input id="ab_id" placeholder="应用ID" style="width:160px;"/><input id="ab_name" placeholder="名称" style="flex:1;"/>
      <select id="ab_ot" onchange="renderAppCfg('${type}')"></select></div>
    <div id="ab_cfg"></div>
    <div class="row"><button onclick="createBuiltApp('${type}')">创建应用</button></div></div>`;
  const sel = document.getElementById("ab_ot");
  api("/api/ontology/object-types").then(types => {
    sel.innerHTML = types.map(t => `<option value="${t.id}">${esc(t.name)} (${t.id})</option>`).join("");
    renderAppCfg(type);
  });
}
async function renderAppCfg(type) {
  const otid = document.getElementById("ab_ot").value;
  const ot = await api(`/api/ontology/object-types/${otid}`);
  const props = JSON.parse(ot.properties);
  const acts = (await api("/api/ontology/actions")).filter(a => a.object_type === otid);
  const box = document.getElementById("ab_cfg");
  let html = "";
  if (type === "dashboard") {
    html = `<div class="row"><label>指标字段</label><select id="ab_metric">${props.map(p=>`<option value="${p.key}">${esc(p.title)}</option>`).join("")}</select>
      <select id="ab_agg"><option value="count">count</option><option value="sum">sum</option><option value="avg">avg</option><option value="min">min</option><option value="max">max</option></select>
      <label>分组</label><select id="ab_gb"><option value="">无</option>${props.map(p=>`<option value="${p.key}">${esc(p.title)}</option>`).join("")}</select></div>`;
  } else if (type === "form") {
    html = `<div class="row"><label>动作</label><select id="ab_act">${acts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join("")}</select></div>`;
  } else if (type === "workflow") {
    html = `<div class="row"><label>动作步骤(JSON)</label><textarea id="ab_steps" style="flex:1;height:70px;" placeholder='[{"name":"步骤1","action_id":"...","params":{}}]'></textarea></div>`;
  } else {
    html = `<div class="row"><label>过滤器(JSON，可选)</label><textarea id="ab_where" style="flex:1;height:60px;" placeholder='{"op":"eq","field":"status","value":"active"}'></textarea></div>`;
  }
  box.innerHTML = html;
}
async function createBuiltApp(type) {
  const id = document.getElementById("ab_id").value.trim();
  const name = document.getElementById("ab_name").value.trim();
  const otid = document.getElementById("ab_ot").value;
  if (!id || !name) { alert("应用ID与名称必填"); return; }
  let config = {};
  if (type === "dashboard") {
    config = { metric: { field: document.getElementById("ab_metric").value, agg: document.getElementById("ab_agg").value },
               group_by: document.getElementById("ab_gb").value || undefined, limit: 10 };
  } else if (type === "form") {
    config = { action_id: document.getElementById("ab_act").value };
  } else if (type === "workflow") {
    try { config = { steps: JSON.parse(document.getElementById("ab_steps").value || "[]") }; }
    catch(e){ alert("步骤 JSON 解析失败"); return; }
  } else {
    let w = null;
    const raw = document.getElementById("ab_where").value.trim();
    if (raw) { try { w = JSON.parse(raw); } catch(e){ alert("过滤器 JSON 解析失败"); return; } }
    config = { where: w, limit: 200 };
  }
  await api("/api/apps", { method:"POST", body: JSON.stringify({ id, name, type, object_type: otid, config }) });
  await openApps();
}
async function deleteApp(id) {
  if (!confirm(`删除应用 ${id}？`)) return;
  await api(`/api/apps/${id}`, { method:"DELETE" });
  await openApps();
}
async function openAppView(id) {
  const html = await (await fetch(API + `/api/apps/${id}/render`, { headers: { Authorization: `Bearer ${TOKEN}` } })).text();
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><div class="row"><strong>${esc(id)} · 应用运行时</strong>
    <button class="ghost" onclick="openApps()">返回</button></div>
    <iframe id="appframe" style="width:100%;height:76vh;border:1px solid var(--line);border-radius:10px;margin-top:10px;background:#fff;"></iframe></div>`;
  document.getElementById("appframe").srcdoc = html;
}
async function openAppVersions(id) {
  const versions = await api(`/api/apps/${id}/versions`);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h3>${esc(id)} · 版本对比</h3>
    <p class="muted">每次保存生成版本快照；选择两个版本查看差异（对齐 Foundry 17326356）。</p>
    <div class="row"><select id="cv1">${versions.map(v=>`<option value="${v.version}">v${v.version} · ${esc(v.created)}</option>`).join("")}</select>
      <select id="cv2">${versions.map(v=>`<option value="${v.version}">v${v.version} · ${esc(v.created)}</option>`).join("")}</select>
      <button onclick="compareApp('${esc(id)}')">对比</button>
      <button class="ghost sm" onclick="openApps()">返回</button></div>
    <div id="cv_out"></div></div>`;
}
async function compareApp(id) {
  const v1 = document.getElementById("cv1").value, v2 = document.getElementById("cv2").value;
  const r = await api(`/api/apps/${id}/compare?v1=${v1}&v2=${v2}`);
  const box = document.getElementById("cv_out");
  if (!r.changes.length) { box.innerHTML = `<p class="muted">两个版本无差异。</p>`; return; }
  box.innerHTML = `<h3>从 v${r.from_version} 到 v${r.to_version} 的变更（${r.changes.length}）</h3><table><thead><tr><th>字段</th><th>旧值</th><th>新值</th></tr></thead><tbody>` +
    r.changes.map(c => `<tr><td>${esc(c.field)}</td><td><pre style="max-height:120px;margin:0;">${esc(JSON.stringify(c.from))}</pre></td><td><pre style="max-height:120px;margin:0;">${esc(JSON.stringify(c.to))}</pre></td></tr>`).join("") +
    `</tbody></table>`;
}
async function openApp(id) {
  const html = await (await fetch(API + `/api/ontology/object-types/${id}/app`, { headers:{Authorization:`Bearer ${TOKEN}`} })).text();
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><div class="row"><strong>${id} · 生成的应用</strong>
    <button onclick="downloadApp('${id}')">下载 HTML</button><button class="ghost" onclick="openApps()">返回</button></div>
    <iframe id="appframe" style="width:100%;height:72vh;border:1px solid var(--line);border-radius:10px;margin-top:10px;background:#fff;"></iframe></div>`;
  document.getElementById("appframe").srcdoc = html;
}
async function downloadApp(id) {
  const txt = await (await fetch(API + `/api/ontology/object-types/${id}/app`, { headers:{Authorization:`Bearer ${TOKEN}`} })).text();
  const blob = new Blob([txt], { type:"text/html" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${id}-app.html`; a.click();
  URL.revokeObjectURL(a.href);
}

// ---------------- AIP 分析师（38163447 / 18802464） ----------------
async function openAgent() {
  const c = document.getElementById("content");
  let llm = null;
  try { llm = await api("/api/aip/llm-status"); } catch(e){}
  c.innerHTML = `<div class="panel"><h2>💬 AIP Analyst</h2>
    <p class="muted">用自然语言查询/操作本体。试试：「列出对象类型」「查客户」「product 状态为 active 的」</p>
    <div class="row">${llm ? (llm.available ? `<span class="tag ok">LLM 已接入：${esc(llm.model)}</span>` : `<span class="tag">规则模式（配置 ONTIC_LLM_API_KEY 启用 LLM）</span>`) : ""}
      <button onclick="saveAnalysis()">保存分析</button><button class="ghost" onclick="listAnalyses()">已存分析</button></div>
    <div id="chatLog" style="background:#0c0e12;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:180px;max-height:50vh;overflow:auto;"></div>
    <div class="row" style="margin-top:10px;">
      <input id="chatInput" placeholder="输入消息，回车发送" style="flex:1;" onkeydown="if(event.key==='Enter')sendChat()"/>
      <button class="primary" onclick="sendChat()">发送</button></div>
    <div id="analyses"></div></div>`;
  document.getElementById("chatInput").focus();
}
async function sendChat() {
  const inp = document.getElementById("chatInput");
  const msg = inp.value.trim(); if (!msg) return; inp.value = "";
  const log = document.getElementById("chatLog");
  log.innerHTML += `<div style="margin:6px 0;"><b>你:</b> ${esc(msg)}</div>`;
  try {
    const r = await api("/api/aip/chat", { method:"POST", body: JSON.stringify({ message: msg }) });
    log.innerHTML += `<div style="margin:6px 0;color:var(--ok)"><b>Agent:</b> ${esc(r.reply)}</div>`;
    if (r.tool) {
      log.innerHTML += `<details class="svc-log"><summary>↳ 服务日志：工具 ${esc(r.tool)}</summary><pre>${esc(JSON.stringify(r.args||{}, null, 2))}</pre></details>`;
    }
  } catch(e) { log.innerHTML += `<div style="color:#ff6b6b">错误: ${esc(e.message)}</div>`; }
  log.scrollTop = log.scrollHeight;
}
function saveAnalysis() {
  const msg = document.getElementById("chatInput").value.trim() || "(空查询)";
  const list = JSON.parse(localStorage.getItem("ontic_analyses")||"[]");
  list.unshift({ name:`分析 ${new Date().toLocaleString()}`, message: msg, ts: Date.now() });
  localStorage.setItem("ontic_analyses", JSON.stringify(list.slice(0,20)));
  alert("已保存到本地「已存分析」");
}
function listAnalyses() {
  const list = JSON.parse(localStorage.getItem("ontic_analyses")||"[]");
  const box = document.getElementById("analyses");
  if (!list.length) { box.innerHTML = `<p class="muted">暂无已存分析。</p>`; return; }
  box.innerHTML = `<h3>已存分析</h3>` + list.map((a,i)=>`<div class="row"><span>${esc(a.name)}</span>
    <button class="ghost sm" onclick="rerunAnalysis(${i})">重跑</button><button class="ghost sm" onclick="delAnalysis(${i})">删除</button></div>`).join("");
}
function rerunAnalysis(i) {
  const list = JSON.parse(localStorage.getItem("ontic_analyses")||"[]");
  const a = list[i]; if (!a) return;
  document.getElementById("chatInput").value = a.message; sendChat();
}
function delAnalysis(i) {
  const list = JSON.parse(localStorage.getItem("ontic_analyses")||"[]"); list.splice(i,1);
  localStorage.setItem("ontic_analyses", JSON.stringify(list)); listAnalyses();
}

// 模型用量看板（21065415）
async function openUsage() {
  const [u, models] = await Promise.all([api("/api/aip/usage"), api("/api/aip/models")]);
  const c = document.getElementById("content");
  const s = u.summary, bm = u.by_model;
  c.innerHTML = `<div class="panel"><h2>📊 模型用量（Model usage）</h2>
    <div class="stat-row">
      <div class="stat"><div class="stat-n">${s.requests}</div><div class="stat-l">请求数</div></div>
      <div class="stat"><div class="stat-n">${s.tokens}</div><div class="stat-l">令牌估算</div></div>
      <div class="stat"><div class="stat-n">${s.success}</div><div class="stat-l">成功</div></div>
      <div class="stat"><div class="stat-n">${models.length}</div><div class="stat-l">已注册模型</div></div>
    </div>
    <h3>Model requests / Token usage</h3>${usageSeriesSVG(u.series)}
    <h3>By model</h3>
    <table><thead><tr><th>模型</th><th>请求</th><th>令牌</th><th>成功率</th></tr></thead><tbody>` +
    bm.map(m => `<tr><td>${esc(m.model)}</td><td>${m.requests}</td><td>${m.tokens}</td>
      <td>${m.requests ? Math.round(100*m.success/m.requests) : 0}%</td></tr>`).join("") +
    `</tbody></table>
    <h3>Models</h3><div class="row">` + models.map(m=>`<span class="tag">${esc(m.name)} · ${esc(m.kind)}</span>`).join("") + `</div></div>`;
}
function usageSeriesSVG(series) {
  if (!series.length) return `<p class="muted">暂无用量数据。去 AIP 分析师聊几句或跑一次模型对比。</p>`;
  const W=680,H=140,pad=30, maxR=Math.max(...series.map(d=>d.requests),1), maxT=Math.max(...series.map(d=>d.tokens),1);
  const step=(W-pad-10)/series.length;
  const pts = (key,max) => series.map((d,i)=>`${(i===0?"M":"L")}${(pad+ i*step).toFixed(1)},${(H-14 - d[key]*(H-40)/max).toFixed(1)}`).join(" ");
  const areaR = pts("requests",maxR), areaT = pts("tokens",maxT);
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;">
    <path d="${areaR}" fill="none" stroke="#4f8cff" stroke-width="2"/>
    <path d="${areaT}" fill="none" stroke="#3ecf8e" stroke-width="2"/>
    ${series.map((d,i)=>`<text x="${(pad+i*step).toFixed(0)}" y="${H-4}" fill="#8b93a7" font-size="9">${d.date.slice(5)}</text>`).join("")}
  </svg><p class="muted" style="font-size:12px;">蓝线 = 请求数 · 绿线 = 令牌估算</p>`;
}

// 评估套件（68207144 / 71082048）
let CUR_EVAL = null;
async function openEvals(sid) {
  const suites = await api("/api/aip/evalsuites");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🧪 评估套件（Evaluation suites）</h2>
    <div class="row"><input id="ev_id" placeholder="套件ID" style="width:160px;"/><input id="ev_name" placeholder="名称" style="flex:1;"/>
      <input id="ev_target" placeholder="被测对象(如 ontic-rule-planner)" style="width:220px;"/>
      <button onclick="createEvalSuite()">创建套件</button></div>
    <div id="ev_list"></div><div id="ev_detail"></div></div>`;
  const list = document.getElementById("ev_list");
  list.innerHTML = suites.length ? `<table><thead><tr><th>套件</th><th>用例数</th><th></th></tr></thead><tbody>` +
    suites.map(s => `<tr><td><a class="link" onclick="openEvals('${esc(s.id)}')">${esc(s.name)}</a></td>
        <td>${s.cases}</td>
        <td><button class="ghost sm" onclick="openEvalDetail('${esc(s.id)}')">管理</button></td></tr>`).join("") + `</tbody></table>` : `<p class="muted">暂无评估套件。</p>`;
  if (sid) await openEvalDetail(sid);
}
async function createEvalSuite() {
  const id = document.getElementById("ev_id").value.trim();
  const name = document.getElementById("ev_name").value.trim();
  const target = document.getElementById("ev_target").value.trim();
  if (!id || !name) { alert("套件ID与名称必填"); return; }
  await api("/api/aip/evalsuites", { method:"POST", body: JSON.stringify({ id, name, target }) });
  await openEvals();
}
async function openEvalDetail(sid) {
  CUR_EVAL = sid;
  const s = await api(`/api/aip/evalsuites/${sid}`);
  const box = document.getElementById("ev_detail");
  box.innerHTML = `<h3>${esc(s.name)} · 用例 ${s.cases.length}</h3>
    <div class="row"><input id="ec_name" placeholder="用例名" style="width:150px;"/>
      <input id="ec_input" placeholder="输入(自然语言)" style="flex:1;"/>
      <input id="ec_expected" placeholder="期望子串" style="width:200px;"/>
      <button onclick="addEvalCase('${esc(sid)}')">＋ 添加用例</button>
      <button class="primary" onclick="runEvalSuite('${esc(sid)}')">▶ 运行评估</button></div>
    <div id="ev_cases"></div><div id="ev_results"></div>`;
  await renderEvalCases(sid);
}
async function renderEvalCases(sid) {
  const s = await api(`/api/aip/evalsuites/${sid}`);
  const box = document.getElementById("ev_cases");
  if (!s.cases.length) { box.innerHTML = `<p class="muted">暂无用例。上方添加（输入 + 期望子串）。</p>`; return; }
  box.innerHTML = `<table><thead><tr><th>用例</th><th>输入</th><th>期望</th></tr></thead><tbody>` +
    s.cases.map(cc => `<tr><td>${esc(cc.name)}</td><td>${esc(cc.input)}</td><td>${esc(cc.expected)}</td></tr>`).join("") +
    `</tbody></table>`;
}
async function addEvalCase(sid) {
  const name = document.getElementById("ec_name").value.trim() || "case";
  const input = document.getElementById("ec_input").value.trim();
  const expected = document.getElementById("ec_expected").value.trim();
  if (!input || !expected) { alert("输入与期望必填"); return; }
  await api(`/api/aip/evalsuites/${sid}/cases`, { method:"POST", body: JSON.stringify({ name, input, expected }) });
  await renderEvalCases(sid);
}
async function runEvalSuite(sid) {
  const res = await api(`/api/aip/evalsuites/${sid}/run`, { method:"POST", body:"{}" });
  const box = document.getElementById("ev_results");
  box.innerHTML = `<h3>运行结果：${res.passed}/${res.total} 通过</h3><table><thead><tr><th>用例</th><th>输出</th><th>判定</th></tr></thead><tbody>` +
    res.results.map(r => `<tr><td>${esc(r.case)}</td><td>${esc(String(r.output).slice(0,160))}</td>
      <td>${r.pass?'<span class="tag ok">PASS</span>':'<span class="tag" style="color:var(--danger)">FAIL</span>'}</td></tr>`).join("") +
    `</tbody></table>`;
  await loadSidebar();
}

// 模型对比 Playground（84211570）
async function openPlayground() {
  const [models, llm] = await Promise.all([api("/api/aip/models"), api("/api/aip/llm-status")]);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🆚 模型对比（Playground）</h2>
    <p class="muted">两个模型并行推理同一提示词，左右对比输出。A 为本地规则规划器（真实作答），B 为 LLM（${llm.available ? `已接入 ${esc(llm.model)}` : "配置 ONTIC_LLM_API_KEY 后真实，否则占位"}）。</p>
    <div class="row"><select id="pg_a">${models.map(m=>`<option value="${m.id}" ${m.id==="ontic-rule-planner"?"selected":""}>${esc(m.name)}</option>`).join("")}</select>
      <select id="pg_b">${models.map(m=>`<option value="${m.id}" ${m.id==="gpt-4o"?"selected":""}>${esc(m.name)}</option>`).join("")}</select>
      <button onclick="runPlayground()">▶ Run</button></div>
    <textarea id="pg_prompt" placeholder="输入提示词…" style="width:100%;height:64px;">列出对象类型</textarea>
    <div id="pg_out" style="display:flex;gap:12px;margin-top:10px;"></div></div>`;
}
async function runPlayground() {
  const prompt = document.getElementById("pg_prompt").value.trim();
  const model_a = document.getElementById("pg_a").value;
  const model_b = document.getElementById("pg_b").value;
  if (!prompt) { alert("提示词必填"); return; }
  const r = await api("/api/aip/playground", { method:"POST", body: JSON.stringify({ prompt, model_a, model_b }) });
  document.getElementById("pg_out").innerHTML =
    `<div class="panel sm" style="flex:1;"><h4>${esc(r.model_a)}</h4><pre>${esc(r.output_a)}</pre></div>
     <div class="panel sm" style="flex:1;"><h4>${esc(r.model_b)}</h4><pre>${esc(r.output_b)}</pre></div>`;
}

// 文档智能（占位：文本 → 对象类型）
async function openDocIntel() {
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📄 文档智能</h2>
    <p class="muted">将文本按行抽取为结构化对象类型（真实实现可接 OCR / LLM 实体抽取）。</p>
    <div class="row"><input id="di_id" placeholder="目标对象类型ID" style="width:200px;"/>
      <button onclick="runDocIntel()">抽取并注册</button></div>
    <textarea id="di_text" placeholder="粘贴文档文本…" style="width:100%;height:180px;"></textarea>
    <div id="di_out"></div></div>`;
}
async function runDocIntel() {
  const otid = document.getElementById("di_id").value.trim();
  const text = document.getElementById("di_text").value;
  if (!otid || !text.trim()) { alert("对象类型ID与文本必填"); return; }
  const r = await api("/api/aip/doc-extract", { method:"POST", body: JSON.stringify({ object_type_id: otid, text }) });
  document.getElementById("di_out").innerHTML = `<pre>${JSON.stringify(r, null, 2)}</pre>
    <button onclick="openType('${esc(otid)}')">查看对象类型</button>`;
  await loadSidebar();
}

// ---------------- 通知中心（74849331，支持按分类过滤） ----------------
async function openNotifications(kind) {
  const acts = await api("/api/activity");
  const c = document.getElementById("content");
  const filtered = kind && kind !== "全部" ? acts.filter(a => a.kind === kind) : acts;
  const cats = [...new Set(acts.map(a=>a.kind))];
  let html = `<div class="panel"><h2>🔔 通知 / 活动</h2><div class="row">` +
    ["全部", ...cats].map(k => `<span class="tag ${k===kind?"ok":""}" style="cursor:pointer;" onclick="openNotifications('${esc(k)}')">${esc(k)}</span>`).join("") + `</div>` +
    `<table><thead><tr><th>时间</th><th>类型</th><th>内容</th></tr></thead><tbody>`;
  html += filtered.map(a=>`<tr><td class="muted">${esc(a.ts)}</td><td><span class="tag">${esc(a.kind)}</span></td><td>${esc(a.message)}</td></tr>`).join("");
  html += `</tbody></table></div>`;
  c.innerHTML = html;
  await updateBell();
}

// ---------------- 建模（M3） ----------------
async function openModeler() {
  const types = await api("/api/ontology/object-types");
  const c = document.getElementById("content");
  c.innerHTML = `
    <div class="panel"><h2>🧱 Ontology Manager（可视化建模）</h2>
      <p class="muted">无需写代码：定义对象类型（字段）、动作、链接，立即注册到本体并可查询/写回。</p>
      <h3>新建对象类型</h3>
      <div class="row"><input id="ot_id" placeholder="类型ID(如 order)" style="width:160px;"/>
        <input id="ot_name" placeholder="显示名"/><input id="ot_desc" placeholder="描述" style="flex:1;"/></div>
      <div class="row"><input id="ot_pk" placeholder="主键key(默认首字段)" style="width:160px;"/></div>
      <div id="model_fields"></div>
      <div class="row"><button class="ghost" onclick="addFieldRow()">+ 添加字段</button><button onclick="createObjectType()">创建对象类型</button></div>
      <h3>新建自定义动作</h3>
      <div class="row"><input id="ac_id" placeholder="动作ID" style="width:160px;"/>
        <select id="ac_ot">${types.map(t=>`<option value="${t.id}">${esc(t.name)} (${t.id})</option>`).join("")}</select>
        <select id="ac_op"><option value="create">create</option><option value="update">update</option><option value="delete">delete</option></select></div>
      <div class="row"><input id="ac_name" placeholder="显示名" style="flex:1;"/></div>
      <div class="row"><textarea id="ac_params" placeholder='参数(JSON数组): [{"name":"discount","type":"double","required":false}]' style="width:100%;height:54px;"></textarea></div>
      <div class="row"><button onclick="createCustomAction()">创建动作</button></div>
      <div id="model_out"></div></div>`;
  addFieldRow();
}
function addFieldRow(key="", type="string", title="") {
  const wrap = document.getElementById("model_fields");
  const row = document.createElement("div"); row.className = "row";
  row.innerHTML = `<input class="fkey" placeholder="字段key" value="${esc(key)}" style="width:150px;"/>
    <select class="ftype"><option value="string" ${type==="string"?"selected":""}>string</option>
      <option value="integer" ${type==="integer"?"selected":""}>integer</option>
      <option value="double" ${type==="double"?"selected":""}>double</option>
      <option value="boolean" ${type==="boolean"?"selected":""}>boolean</option></select>
    <input class="ftitle" placeholder="标题" value="${esc(title)}" style="flex:1;"/>
    <button class="ghost" onclick="this.parentNode.remove()">✕</button>`;
  wrap.appendChild(row);
}
async function createObjectType() {
  const id = document.getElementById("ot_id").value.trim();
  const name = document.getElementById("ot_name").value.trim();
  const description = document.getElementById("ot_desc").value.trim();
  const pk = document.getElementById("ot_pk").value.trim();
  const fields = [];
  document.querySelectorAll("#model_fields .row").forEach(r => {
    const key = r.querySelector(".fkey").value.trim(); if (!key) return;
    fields.push({ key, type: r.querySelector(".ftype").value, title: r.querySelector(".ftitle").value.trim() || key });
  });
  if (!id || !fields.length) { alert("类型ID与至少一个字段必填"); return; }
  const res = await api("/api/ontology/object-types", { method:"POST", body: JSON.stringify({ id, name, description, primary_key: pk, fields }) });
  document.getElementById("model_out").innerHTML = `<pre>${JSON.stringify(res, null, 2)}</pre>`;
  await loadSidebar();
}
async function createCustomAction() {
  const id = document.getElementById("ac_id").value.trim();
  const object_type = document.getElementById("ac_ot").value;
  const operation = document.getElementById("ac_op").value;
  const name = document.getElementById("ac_name").value.trim();
  let params = []; const raw = document.getElementById("ac_params").value.trim();
  if (raw) { try { params = JSON.parse(raw); } catch(e){ alert("参数 JSON 解析失败: "+e.message); return; } }
  const res = await api("/api/ontology/actions", { method:"POST", body: JSON.stringify({ id, name, object_type, operation, parameters: params }) });
  document.getElementById("model_out").innerHTML = `<pre>${JSON.stringify(res, null, 2)}</pre>`;
  await loadSidebar();
}

// ---------------- 连接器（M4） ----------------
let CONNECTORS = [];
async function openConnectors() {
  CONNECTORS = await api("/api/connectors");
  const sel = CONNECTORS.map(c=>`<option value="${c.id}">${esc(c.name)}</option>`).join("");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🔌 数据接入（连接器框架）</h2>
    <p class="muted">选择连接器，配置后一键接入并自动注册为 Ontology 对象类型。覆盖 CSV / JSON / Parquet / REST / PostgreSQL。</p>
    <div class="row"><select id="conn_type" onchange="renderConnForm()">${sel}</select>
      <input id="conn_otid" placeholder="对象类型ID(如 sales)" style="width:170px;"/></div>
    <div id="conn_form"></div>
    <div class="row"><button onclick="runConnector()">接入并注册</button></div>
    <div id="conn_out"></div></div>`;
  renderConnForm();
}
function renderConnForm() {
  const c = CONNECTORS.find(x => x.id === document.getElementById("conn_type").value);
  const box = document.getElementById("conn_form");
  if (c.file_based) {
    box.innerHTML = `<div class="row"><input id="conn_file" type="file"/></div>` +
      (c.id === "csv" ? `<div class="row"><input id="conn_pk" placeholder="主键(默认id)" style="width:140px;"/></div>` : "");
  } else {
    box.innerHTML = c.fields.map(f => `<div class="row"><label style="width:220px;">${esc(f.label)}</label>
       <input id="cf_${f.key}" type="${f.type==="password"?"password":"text"}" style="flex:1;"/></div>`).join("");
  }
}
async function runConnector() {
  const type = document.getElementById("conn_type").value;
  const otid = document.getElementById("conn_otid").value.trim();
  if (!otid) { alert("对象类型ID必填"); return; }
  const c = CONNECTORS.find(x => x.id === type);
  const fd = new FormData(); fd.append("connector_type", type); fd.append("object_type_id", otid);
  if (c.file_based) {
    const f = document.getElementById("conn_file").files[0]; if (!f) { alert("请选择文件"); return; }
    fd.append("file", f);
    if (type === "csv") fd.append("primary_key", document.getElementById("conn_pk").value.trim() || "id");
  } else {
    const cfg = {}; c.fields.forEach(f => { cfg[f.key] = document.getElementById("cf_"+f.key).value; });
    fd.append("config", JSON.stringify(cfg));
  }
  const r = await fetch(API + "/api/connectors/ingest", { method:"POST", headers:{Authorization:`Bearer ${TOKEN}`}, body: fd });
  const out = document.getElementById("conn_out");
  if (!r.ok) { out.innerHTML = `<pre style="color:#ff6b6b">${esc(await r.text())}</pre>`; return; }
  out.innerHTML = `<pre>${JSON.stringify(await r.json(), null, 2)}</pre>`;
  await loadSidebar();
}

// ---------------- 管道构建器（M5）+ 数据流图（10096559 / 68855017） ----------------
async function openPipelines() {
  const [fns, pls] = await Promise.all([api("/api/functions"), api("/api/pipelines")]);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>⚙️ 管道构建器（Pipeline Builder）</h2>
    <p class="muted">编排多步 SQL 转换，每步可注册为 Ontology 对象类型。步骤 SQL 可使用下方函数库。</p>
    <h3>函数库（pb-functions）</h3>
    <div class="row">${fns.map(f=>`<span class="tag" title="${esc(f.desc)}">${esc(f.signature)}</span>`).join("")}</div>
    <h3>新建管道</h3>
    <div class="row"><input id="pl_id" placeholder="管道ID" style="width:160px;"/><input id="pl_name" placeholder="显示名" style="flex:1;"/></div>
    <div id="pl_steps"></div>
    <div class="row"><button class="ghost" onclick="addStepRow()">+ 添加步骤</button><button onclick="createPipeline()">保存管道</button></div>
    <h3>已有管道</h3><div id="pl_list"></div>
    <div id="pl_out"></div></div>`;
  addStepRow();
  const list = document.getElementById("pl_list");
  list.innerHTML = pls.length ? pls.map(p => `<div class="panel sm"><div class="row" style="justify-content:space-between;">
      <strong>${esc(p.id)}</strong><span class="muted">${esc(p.name)} · ${p.steps.length} 步</span></div>
      ${pipelineFlow(p)}<div class="row"><button onclick="runPipeline('${esc(p.id)}')">运行</button>
      <button class="ghost" onclick="loadPipelineHistory('${esc(p.id)}')">运行历史 / 快照</button></div>
      <div id="ph_${esc(p.id)}"></div></div>`).join("")
    : `<p class="muted">暂无管道。</p>`;
}
// 运行历史（32266587 时间线）+ 数据快照（12378379 时间旅行）
let CUR_PL = null;
async function loadPipelineHistory(pid) {
  CUR_PL = pid;
  const [runs, snaps] = await Promise.all([api(`/api/pipelines/${pid}/runs`), api(`/api/pipelines/${pid}/snapshots`)]);
  const box = document.getElementById(`ph_${pid}`);
  let html = `<h4>运行历史</h4>` + (runs.length ? runs.map(r =>
    `<div class="act-row"><span class="tag ${r.status==='succeeded'?'ok':''}">${esc(r.status)}</span>
     <span class="muted">#${r.id} · ${esc(r.ts)}</span>
     <span>${r.detail ? r.detail.map(x=>esc(x.name)).join("，") : ""}</span></div>`).join("") : `<p class="muted">暂无运行。</p>`) +
    `<h4>数据快照（时间旅行）</h4>` + (snaps.length ? snaps.map(s =>
    `<div class="act-row"><span class="tag">${esc(s.ts)}</span><code>${esc(s.table_name)}</code>
     <button class="ghost sm" onclick="snapshotQuery('${esc(s.table_name)}')">查看</button></div>`).join("") : `<p class="muted">暂无快照（运行带 target 的管道后生成）。</p>`) +
    `<div id="snap_out"></div>`;
  box.innerHTML = html;
}
async function snapshotQuery(table) {
  const r = await api("/api/sql", { method:"POST", body: JSON.stringify({ sql: `SELECT * FROM ${table} LIMIT 50` }) });
  const box = document.getElementById("snap_out");
  const rows = r.rows;
  if (!rows.length) { box.innerHTML = `<p class="muted">空快照</p>`; return; }
  const cols = Object.keys(rows[0]);
  box.innerHTML = `<p class="muted">${table} · ${r.count} 行</p><table><thead><tr>` + cols.map(c=>`<th>${esc(c)}</th>`).join("") + `</tr></thead><tbody>` +
    rows.map(row=>"<tr>"+cols.map(c=>`<td>${esc(row[c])}</td>`).join("")+"</tr>").join("") + `</tbody></table>`;
}
function pipelineFlow(p) {
  // 数据流卡片：Source → Transform → Output（10096559 / 68855017）
  let cards = "";
  p.steps.forEach((s,i) => {
    const kind = s.target ? "OUTPUT DATASET" : "TRANSFORM";
    cards += `<div class="flow-card ${s.target?'out':'tf'}"><div class="flow-kind">${kind}</div>
      <div class="flow-name">${esc(s.name||('step'+i))}</div>${s.target?`<div class="flow-sub">→ ${esc(s.target)}</div>`:""}</div>`;
    if (i < p.steps.length-1) cards += `<span class="flow-arrow">→</span>`;
  });
  return `<div class="flow">${cards}</div>`;
}
function addStepRow() {
  const wrap = document.getElementById("pl_steps");
  const row = document.createElement("div"); row.className = "row"; row.style.flexDirection="column"; row.style.alignItems="stretch";
  row.innerHTML = `<div class="row"><input class="s_name" placeholder="步骤名" style="width:160px;"/>
    <input class="s_target" placeholder="产出对象类型ID(可选)" style="flex:1;"/></div>
    <textarea class="s_sql" placeholder="SELECT ... 可用 ont_* 函数" style="width:100%;height:48px;"></textarea>
    <button class="ghost" onclick="this.parentNode.remove()">✕ 移除</button>`;
  wrap.appendChild(row);
}
async function createPipeline() {
  const id = document.getElementById("pl_id").value.trim();
  const name = document.getElementById("pl_name").value.trim();
  const steps = [];
  document.querySelectorAll("#pl_steps .row").forEach(r => {
    const sql = r.querySelector(".s_sql").value.trim(); if (!sql) return;
    steps.push({ name: r.querySelector(".s_name").value.trim(), sql, target: r.querySelector(".s_target").value.trim() });
  });
  if (!id || !steps.length) { alert("管道ID与至少一个步骤必填"); return; }
  const res = await api("/api/pipelines", { method:"POST", body: JSON.stringify({ id, name, description:"", steps }) });
  document.getElementById("pl_out").innerHTML = `<pre>${JSON.stringify(res, null, 2)}</pre>`;
  await openPipelines();
}
async function runPipeline(pid) {
  const res = await api(`/api/pipelines/${pid}/run`, { method:"POST", body:"{}" });
  document.getElementById("pl_out").innerHTML = `<pre>${JSON.stringify(res, null, 2)}</pre>`;
  await loadSidebar();
}

// ---------------- 管理（M1） ----------------
async function openAdmin() {
  const c = document.getElementById("content");
  c.innerHTML = `
    <div class="panel"><h2>🛡️ 用户与授权管理</h2>
      <p class="muted">创建用户、分配对象类型读写权限（ABAC）。grant 的 object_type 填 <code>*</code> 表示全部。</p>
      <h3>新建用户</h3>
      <div class="row"><input id="nu_name" placeholder="用户名"/><input id="nu_pw" type="password" placeholder="密码"/>
        <select id="nu_role"><option value="analyst">analyst</option><option value="admin">admin</option></select>
        <button onclick="adminCreateUser()">创建</button></div>
      <h3>用户列表</h3><div id="user_list"></div>
      <h3>授权列表</h3>
      <div class="row"><input id="g_user" placeholder="用户名"/><input id="g_type" placeholder="对象类型 (如 product 或 *)"/>
        <select id="g_level"><option value="read">read</option><option value="write">write</option></select>
        <button onclick="adminGrant()">授权</button></div>
      <div id="grant_list"></div></div>`;
  await adminRefresh();
}
async function adminRefresh() {
  const users = await api("/api/admin/users");
  const grants = await api("/api/admin/grants");
  document.getElementById("user_list").innerHTML = "<table><thead><tr><th>用户</th><th>角色</th><th>操作</th></tr></thead><tbody>" +
    users.map(u=>`<tr><td>${esc(u.username)}</td><td>${esc(u.role)}
      <select onchange="adminSetRole('${esc(u.username)}', this.value)">
        <option value="analyst" ${u.role==="analyst"?"selected":""}>analyst</option>
        <option value="admin" ${u.role==="admin"?"selected":""}>admin</option></select></td>
      <td><button class="ghost" onclick="adminDeleteUser('${esc(u.username)}')">删除</button></td></tr>`).join("") + "</tbody></table>";
  document.getElementById("grant_list").innerHTML = "<table><thead><tr><th>用户</th><th>对象类型</th><th>级别</th><th>操作</th></tr></thead><tbody>" +
    grants.map(g=>`<tr><td>${esc(g.username)}</td><td>${esc(g.object_type)}</td><td>${esc(g.level)}</td>
      <td><button class="ghost" onclick="adminRevoke('${esc(g.username)}','${esc(g.object_type)}')">撤销</button></td></tr>`).join("") + "</tbody></table>";
}
async function adminCreateUser() {
  const username = document.getElementById("nu_name").value.trim();
  const password = document.getElementById("nu_pw").value;
  const role = document.getElementById("nu_role").value;
  if (!username || !password) { alert("用户名和密码必填"); return; }
  await api("/api/admin/users", { method:"POST", body: JSON.stringify({ username, password, role }) });
  await adminRefresh();
}
async function adminDeleteUser(username) {
  if (!confirm(`删除用户 ${username}？`)) return;
  await api(`/api/admin/users/${username}`, { method:"DELETE" });
  await adminRefresh();
}
async function adminSetRole(username, role) {
  await api(`/api/admin/users/${username}/role`, { method:"POST", body: JSON.stringify({ role }) });
  await adminRefresh();
}
async function adminGrant() {
  const username = document.getElementById("g_user").value.trim();
  const object_type = document.getElementById("g_type").value.trim();
  const level = document.getElementById("g_level").value;
  if (!username || !object_type) { alert("用户名和对象类型必填"); return; }
  await api("/api/admin/grants", { method:"POST", body: JSON.stringify({ username, object_type, level }) });
  await adminRefresh();
}
async function adminRevoke(username, object_type) {
  await api("/api/admin/grants", { method:"DELETE", body: JSON.stringify({ username, object_type }) });
  await adminRefresh();
}

// ---------------- 安全治理（M8：扫描 59324049 / 审批 69762283 / 留存 / 标记 5667552） ----------------
async function openSecurity() {
  const types = await api("/api/ontology/object-types");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🔐 安全治理</h2>
    <h3>1. 敏感数据扫描</h3>
    <div class="row"><select id="sc_type">${types.map(t=>`<option value="${t.id}">${esc(t.name)} (${t.id})</option>`).join("")}</select>
      <button onclick="runScan()">扫描</button></div>
    <div id="scan_out"></div>
    <h3>2. 审批队列</h3>
    <div id="appr_out"></div>
    <h3>3. 留存策略</h3>
    <div id="ret_out"></div>
    <h3>4. 安全标记</h3>
    <div class="row"><select id="mk_type">${types.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
      <select id="mk_name"><option>Restricted</option><option>Confidential</option><option>Public</option></select>
      <button onclick="assignMarking()">添加标记</button>
      <button class="ghost" onclick="assignMarking(true)">移除标记</button></div>
    <div id="mk_out"></div></div>`;
  await Promise.all([renderScans(), renderApprovals(), renderRetention(), renderMarkings()]);
}
async function runScan() {
  const type = document.getElementById("sc_type").value;
  const r = await api("/api/security/scan", { method:"POST", body: JSON.stringify({ object_type: type }) });
  const keys = Object.keys(r.matches);
  document.getElementById("scan_out").innerHTML =
    `<div class="panel sm"><strong>Overall matches</strong><div class="row">` +
    (keys.length ? keys.map(k=>`<span class="tag" style="color:var(--danger)">${esc(k)} ×${r.matches[k]}</span>`).join("")
      : `<span class="tag ok">No matches detected</span>`) +
    `</div><p class="muted">扫描 ${r.scanned_rows} 行 · ${new Date().toLocaleString()}</p></div>` +
    `<h4>Previous scan cycles</h4>` + (r.history.length>1 ?
      r.history.map(h=>`<div class="act-row"><span class="tag">${esc(h.ts)}</span><span>${h.summary.map(s=>`${esc(s.match)}×${s.count}`).join("，")||"无命中"}</span></div>`).join("")
      : `<p class="muted">暂无历史。</p>`);
}
async function renderScans() {}
async function renderApprovals() {
  const appr = await api("/api/security/approvals?status=pending");
  const box = document.getElementById("appr_out");
  if (!appr.length) { box.innerHTML = `<p class="muted">无待审批请求。</p>`; return; }
  box.innerHTML = `<table><thead><tr><th>#</th><th>请求人</th><th>动作</th><th>参数</th><th>备注</th><th></th></tr></thead><tbody>` +
    appr.map(a => `<tr><td>${a.id}</td><td>${esc(a.requester)}</td><td>${esc(a.action_id)}</td><td class="muted">${esc(JSON.stringify(a.params))}</td><td>${esc(a.note||"")}</td>
      <td><button class="ghost sm ok" onclick="decideApproval(${a.id},true)">批准</button>
          <button class="ghost sm" style="color:var(--danger)" onclick="decideApproval(${a.id},false)">拒绝</button></td></tr>`).join("") + `</tbody></table>`;
}
async function decideApproval(id, approve) {
  await api(`/api/security/approvals/${id}/decide`, { method:"POST", body: JSON.stringify({ approve }) });
  await renderApprovals();
  await openHome();
}
async function renderRetention() {
  const r = await api("/api/security/retention");
  const box = document.getElementById("ret_out");
  box.innerHTML = `<table><thead><tr><th>对象类型</th><th>留存天数</th><th>最后事件</th><th>状态</th><th></th></tr></thead><tbody>` +
    r.map(x => `<tr><td>${esc(x.object_type)}</td><td>
        <input id="ret_${esc(x.object_type)}" type="number" value="${x.days}" style="width:80px;"/>
      </td><td class="muted">${esc(x.last_event||"—")}</td>
      <td>${x.overdue?'<span class="tag" style="color:var(--danger)">超期</span>':'<span class="tag ok">正常</span>'}</td>
      <td><button class="ghost sm" onclick="setRetention('${esc(x.object_type)}')">保存</button></td></tr>`).join("") + `</tbody></table>`;
}
async function setRetention(type) {
  const days = parseInt(document.getElementById(`ret_${type}`).value, 10) || 90;
  await api("/api/security/retention", { method:"PUT", body: JSON.stringify({ object_type: type, days }) });
  await renderRetention();
}
async function renderMarkings() {
  const types = await api("/api/ontology/object-types");
  const m = await api("/api/security/markings");
  const box = document.getElementById("mk_out");
  box.innerHTML = `<table><thead><tr><th>对象类型</th><th>标记</th></tr></thead><tbody>` +
    types.map(t => `<tr><td>${esc(t.name)}</td><td>${(m.assigned[t.id]||[]).map(x=>`<span class="tag" style="color:var(--warn)">${esc(x)}</span>`).join("")||'<span class="muted">—</span>'}</td></tr>`).join("") + `</tbody></table>`;
}
async function assignMarking(remove) {
  const type = document.getElementById("mk_type").value;
  const marking = document.getElementById("mk_name").value;
  await api("/api/security/markings/assign", { method:"POST", body: JSON.stringify({ object_type: type, marking, remove: !!remove }) });
  await renderMarkings();
}

// ---------------- M9 模型目录（Model Catalog 36581134） ----------------
async function openModelCatalog() {
  const [models, objectives] = await Promise.all([api("/api/models"), api("/api/models/objectives")]);
  const c = document.getElementById("content");
  const kinds = ["rules", "llm"];
  c.innerHTML = `<div class="panel"><h2>🧠 模型目录（Model Catalog）</h2>
    <h3>建模目标（Modeling Objectives）</h3>
    <div class="row"><input id="mo_id" placeholder="目标ID" style="width:150px;"/><input id="mo_name" placeholder="名称" style="flex:1;"/>
      <select id="mo_model">${models.map(m=>`<option value="${m.id}">${esc(m.name)}</option>`).join("")}</select>
      <button onclick="createObjective()">创建目标</button></div>
    <div id="obj_list"></div>
    <h3>Models</h3>
    <div class="model-grid">` +
    models.map(m => `<div class="model-card">
      <div class="row" style="justify-content:space-between;"><strong>${esc(m.name)}</strong><span class="tag">${esc(m.kind)}</span></div>
      <p class="muted" style="font-size:12px;">${esc(m.provider)}</p>
      <div class="row" style="font-size:12px;">请求 ${m.requests} · 令牌 ${m.tokens} · v${m.version} · 目标 ${m.objectives}</div>
      <div class="row"><button class="ghost sm" onclick="modelVersion('${esc(m.id)}')">提交版本</button>
        <button class="ghost sm" onclick="modelTrain('${esc(m.id)}')">训练(占位)</button>
        <button class="ghost sm" onclick="modelDetail('${esc(m.id)}')">详情</button></div>
      <div id="md_${esc(m.id)}"></div></div>`).join("") +
    `</div></div>`;
  const ob = document.getElementById("obj_list");
  ob.innerHTML = objectives.length ? objectives.map(o =>
    `<div class="act-row"><span class="tag">${esc(o.status)}</span><span>${esc(o.name)}</span><span class="muted">→ ${esc(o.model_id)}</span></div>`).join("")
    : `<p class="muted">暂无建模目标。</p>`;
}
async function createObjective() {
  const id = document.getElementById("mo_id").value.trim();
  const name = document.getElementById("mo_name").value.trim();
  const model_id = document.getElementById("mo_model").value;
  if (!id || !name) { alert("目标ID与名称必填"); return; }
  await api("/api/models/objectives", { method:"POST", body: JSON.stringify({ id, name, model_id }) });
  await openModelCatalog();
}
async function modelVersion(mid) {
  const note = prompt("版本说明：") || "";
  await api(`/api/models/${mid}/versions`, { method:"POST", body: JSON.stringify({ note }) });
  await openModelCatalog();
}
async function modelTrain(mid) {
  const r = await api(`/api/models/${mid}/train`, { method:"POST", body:"{}" });
  alert(`训练任务已提交：${r.job}`);
}
async function modelDetail(mid) {
  const d = await api(`/api/models/${mid}`);
  const box = document.getElementById(`md_${mid}`);
  box.innerHTML = `<div class="panel sm"><h4>${esc(d.model.name)} · 版本历史</h4>` +
    (d.versions.length ? d.versions.map(v=>`<div class="act-row"><span class="tag">v${v.version}</span><span>${esc(v.note||"—")}</span><span class="muted">${esc(v.created)}</span></div>`).join("") : `<p class="muted">暂无版本。</p>`) +
    `<h4>关联建模目标</h4>` + (d.objectives.length ? d.objectives.map(o=>`<div class="act-row"><span>${esc(o.name)}</span><span class="muted">${esc(o.status)}</span></div>`).join("") : `<p class="muted">无。</p>`) + `</div>`;
}

// ---------------- M10 血缘图 + 运维监控 ----------------
async function openLineage() {
  const g = await api("/api/lineage");
  const c = document.getElementById("content");
  // 层级布局：按拓扑层（source→target）分列
  const names = Object.fromEntries(g.nodes.map(n=>[n.id, n.name]));
  const layer = {}; let maxLayer = 0;
  g.nodes.forEach(n => layer[n.id] = 0);
  let changed = true;
  while (changed) {
    changed = false;
    g.edges.forEach(e => { if (layer[e.target] <= layer[e.source]) { layer[e.target] = layer[e.source] + 1; changed = true; } });
  }
  maxLayer = Math.max(...g.nodes.map(n=>layer[n.id]), 1);
  const cols = Array.from({length:maxLayer+1}, ()=>[]);
  g.nodes.forEach(n => cols[layer[n.id]].push(n.id));
  const cellW = 150, cellH = 64, padX = 30, padY = 24;
  const W = Math.max(680, (maxLayer+1)*cellW + padX*2), H = Math.max(300, Math.max(...cols.map(c=>c.length))*cellH + padY*2);
  const pos = {};
  cols.forEach((col, li) => col.forEach((nid, ri) => {
    pos[nid] = { x: padX + li*cellW + cellW/2, y: padY + ri*cellH + cellH/2 - (cols[li].length-1)*cellH/2 };
  }));
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;">`;
  g.edges.forEach(e => {
    const s = pos[e.source], t = pos[e.target];
    if (s && t) svg += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="#4f8cff" stroke-width="1.5" opacity="0.6"/>`;
  });
  g.nodes.forEach(n => {
    const p = pos[n.id];
    svg += `<g onclick="openType('${n.id}')" style="cursor:pointer;">
      <rect x="${p.x-62}" y="${p.y-16}" width="124" height="32" rx="8" fill="#171a21" stroke="#3ecf8e"/>
      <text x="${p.x}" y="${p.y+4}" fill="#e6e9ef" font-size="11" text-anchor="middle">${esc(names[n.id]||n.id)}</text></g>`;
  });
  svg += `</svg><p class="muted">节点 ${g.nodes.length} · 血缘边 ${g.edges.length}（管道 SQL + 链接类型推导）</p>`;
  c.innerHTML = `<div class="panel"><h2>🧬 数据血缘（Lineage）</h2>${svg}</div>`;
}
async function openOps() {
  const [monitors, acts] = await Promise.all([api("/api/monitors"), api("/api/activity")]);
  const types = await api("/api/ontology/object-types");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📈 运维监控</h2>
    <h3>监控规则</h3>
    <div class="row"><input id="mo_id2" placeholder="规则ID" style="width:130px;"/><input id="mo_name2" placeholder="名称" style="flex:1;"/>
      <select id="mo_type">${types.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
      <select id="mo_metric"><option value="count">count</option><option value="sum:amount">sum:字段</option></select>
      <select id="mo_op"><option value="gt">&gt;</option><option value="lt">&lt;</option><option value="gte">≥</option><option value="lte">≤</option></select>
      <input id="mo_thr" type="number" placeholder="阈值" value="100" style="width:90px;"/>
      <button onclick="createMonitor()">创建</button></div>
    <div id="mon_list"></div>
    <div class="row"><button onclick="checkAllMonitors()">▶ 运行全部检查</button></div>
    <h3>平台事件时间线（23315552）</h3>
    <div id="ops_tl" style="max-height:300px;overflow:auto;"></div></div>`;
  await renderMonitors();
  const tl = document.getElementById("ops_tl");
  tl.innerHTML = acts.slice(0, 20).map(a =>
    `<div class="act-row"><span class="tag">${esc(a.kind)}</span><span>${esc(a.message)}</span><span class="muted act-ts">${esc((a.ts||"").slice(0,16).replace("T"," "))}</span></div>`).join("");
}
async function renderMonitors() {
  const monitors = await api("/api/monitors");
  const box = document.getElementById("mon_list");
  if (!monitors.length) { box.innerHTML = `<p class="muted">暂无监控规则。</p>`; return; }
  box.innerHTML = `<table><thead><tr><th>规则</th><th>对象类型</th><th>指标</th><th>阈值</th><th>状态</th><th></th></tr></thead><tbody>` +
    monitors.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.object_type)}</td><td>${esc(m.metric)}</td><td>${esc(m.op)} ${m.threshold}</td>
      <td>${m.enabled?'<span class="tag ok">启用</span>':'<span class="tag">停用</span>'}</td>
      <td><button class="ghost sm" onclick="checkMonitor('${esc(m.id)}')">检查</button>
          <button class="ghost sm" onclick="deleteMonitor('${esc(m.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`;
}
async function createMonitor() {
  const id = document.getElementById("mo_id2").value.trim();
  const name = document.getElementById("mo_name2").value.trim();
  const object_type = document.getElementById("mo_type").value;
  const metric = document.getElementById("mo_metric").value;
  const op = document.getElementById("mo_op").value;
  const threshold = parseFloat(document.getElementById("mo_thr").value) || 100;
  if (!id) { alert("规则ID必填"); return; }
  await api("/api/monitors", { method:"POST", body: JSON.stringify({ id, name: name||id, object_type, metric, op, threshold }) });
  await renderMonitors();
}
async function checkMonitor(mid) {
  const r = await api(`/api/monitors/${mid}/check`, { method:"POST", body:"{}" });
  alert(`${r.metric} = ${r.value}（阈值 ${r.op} ${r.threshold}）→ ${r.breached ? "⚠ 告警" : "✓ 正常"}`);
  await renderMonitors();
}
async function checkAllMonitors() {
  const rs = await api("/api/monitors/check-all", { method:"POST", body:"{}" });
  alert(`已检查 ${rs.length} 条规则`);
  await openOps();
}
async function deleteMonitor(mid) {
  if (!confirm(`删除监控 ${mid}？`)) return;
  await api(`/api/monitors/${mid}`, { method:"DELETE" });
  await renderMonitors();
}

// ---------------- M11 数据平面前端（SQL / 时空 / 媒体） ----------------
async function openSql() {
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🗄️ SQL 工作台</h2>
    <p class="muted">只读 SELECT 直查数据平面（DuckDB），仅限已注册对象类型表（ont__*）。</p>
    <textarea id="sql_input" style="width:100%;height:120px;font-family:monospace;" placeholder="SELECT status, count(*) AS n FROM ont__customer GROUP BY status">SELECT status, count(*) AS n FROM ont__customer GROUP BY status</textarea>
    <div class="row"><button onclick="runSql()">▶ 运行</button><span id="sql_meta" class="muted"></span></div>
    <div id="sql_out"></div></div>`;
}
async function runSql() {
  const sql = document.getElementById("sql_input").value.trim();
  if (!sql) return;
  const box = document.getElementById("sql_out");
  try {
    const r = await api("/api/sql", { method:"POST", body: JSON.stringify({ sql }) });
    document.getElementById("sql_meta").textContent = `${r.count} 行 · ${r.elapsed_ms}ms${r.limited?"（已截断）":""}`;
    if (!r.rows.length) { box.innerHTML = `<p class="muted">无结果</p>`; return; }
    box.innerHTML = "<table><thead><tr>" + r.columns.map(c=>`<th>${esc(c)}</th>`).join("") + "</tr></thead><tbody>" +
      r.rows.map(row => "<tr>" + r.columns.map(c=>`<td>${esc(row[c])}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
  } catch(e) { box.innerHTML = `<pre style="color:var(--danger)">${esc(e.message)}</pre>`; }
}
async function openGeo() {
  const types = await api("/api/ontology/object-types");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📍 空间查询（Geospatial）</h2>
    <p class="muted">对含 lat/lng 坐标字段的对象类型做半径内邻近查询（Haversine）。</p>
    <div class="row"><select id="geo_type">${types.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
      <input id="geo_lat" type="number" step="0.01" placeholder="纬度" value="39.90" style="width:110px;"/>
      <input id="geo_lng" type="number" step="0.01" placeholder="经度" value="116.40" style="width:110px;"/>
      <input id="geo_r" type="number" placeholder="半径km" value="1200" style="width:100px;"/>
      <button onclick="runGeo()">查询</button></div>
    <div id="geo_out"></div></div>`;
}
async function runGeo() {
  const body = {
    object_type: document.getElementById("geo_type").value,
    lat: parseFloat(document.getElementById("geo_lat").value) || 0,
    lng: parseFloat(document.getElementById("geo_lng").value) || 0,
    radius_km: parseFloat(document.getElementById("geo_r").value) || 50,
  };
  const box = document.getElementById("geo_out");
  try {
    const r = await api("/api/geo/near", { method:"POST", body: JSON.stringify(body) });
    if (!r.results.length) { box.innerHTML = `<p class="muted">半径内无对象。</p>`; return; }
    box.innerHTML = `<p class="muted">${r.count} 个对象在 ${r.radius_km}km 内</p><table><thead><tr><th>ID</th><th>名称</th><th>距离(km)</th></tr></thead><tbody>` +
      r.results.map(x=>`<tr><td>${esc(x.id)}</td><td>${esc(x.name??"—")}</td><td>${x.distance_km}</td></tr>`).join("") + `</tbody></table>`;
  } catch(e) { box.innerHTML = `<pre style="color:var(--danger)">${esc(e.message)}</pre>`; }
}
async function openMedia() {
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🖼️ 媒体 / 附件</h2>
    <div class="row"><input id="media_file" type="file"/><button onclick="uploadMedia()">上传</button></div>
    <div id="media_out"></div></div>`;
  await refreshMedia();
}
async function refreshMedia() {
  const media = await api("/api/media");
  const box = document.getElementById("media_out");
  if (!media.length) { box.innerHTML = `<p class="muted">暂无媒体文件。</p>`; return; }
  box.innerHTML = `<table><thead><tr><th>文件名</th><th>大小</th><th></th></tr></thead><tbody>` +
    media.map(m => `<tr><td>${esc(m.name)}</td><td>${m.size}B</td>
      <td><a class="link" href="/api/media/${esc(m.name)}" target="_blank">查看</a></td></tr>`).join("") + `</tbody></table>`;
}
async function uploadMedia() {
  const f = document.getElementById("media_file").files[0];
  if (!f) { alert("请选择文件"); return; }
  const fd = new FormData(); fd.append("file", f);
  const r = await fetch(API + "/api/media/upload", { method:"POST", headers:{Authorization:`Bearer ${TOKEN}`}, body: fd });
  if (!r.ok) { alert(await r.text()); return; }
  await refreshMedia();
}

// ---------------- M12 开发者控制台（OSDK / 令牌 / API 参考 / 市场） ----------------
async function openDev(section) {
  const c = document.getElementById("content");
  const tabs = [["console","控制台"],["tokens","API 令牌"],["endpoints","自定义端点"],["api","API 参考"],["market","市场"]];
  c.innerHTML = `<div class="panel"><h2>🧑‍💻 开发者控制台</h2>
    <div class="tabs">${tabs.map(([id,l])=>`<span class="tab ${(section||"console")===id?"on":""}" data-tab="${id}" onclick="openDev('${id}')">${l}</span>`).join("")}</div>
    <div id="dev_body"></div></div>`;
  const body = document.getElementById("dev_body");
  if ((section||"console") === "tokens") await renderDevTokens(body);
  else if ((section||"console") === "endpoints") await renderDevEndpoints(body);
  else if ((section||"console") === "api") renderApiRef(body);
  else if ((section||"console") === "market") renderMarket(body);
  else body.innerHTML = `<div class="row"><button onclick="fetchOsdk('python')">Python OSDK</button><button onclick="fetchOsdk('typescript')">TypeScript OSDK</button></div>
    <pre id="osdk_out" style="max-height:60vh;">点击上方按钮生成类型安全客户端代码。</pre>
    <h3>快速开始</h3><p class="muted">1. 登录获取 JWT → 2. 调用 /api/**（Bearer）→ 3. 或用 API 令牌（密钥管理）。</p>`;
}
// 自定义 API 端点（custom-endpoints）
async function renderDevEndpoints(body) {
  const eps = await api("/api/endpoints");
  body.innerHTML = `<h3>自定义 API 端点</h3>
    <p class="muted">用只读 SQL 开放 REST 端点（路径以 /custom/ 开头），创建即生效、重启持久。</p>
    <div class="row"><input id="ep_id" placeholder="端点ID" style="width:140px;"/>
      <input id="ep_path" placeholder="/custom/my-endpoint" style="flex:1;"/>
      <select id="ep_method"><option>GET</option><option>POST</option></select>
      <button onclick="createEndpoint()">创建</button></div>
    <textarea id="ep_sql" placeholder="SELECT ... FROM ont__xxx" style="width:100%;height:60px;"></textarea>
    <table style="margin-top:10px;"><thead><tr><th>ID</th><th>Method</th><th>Path</th><th>说明</th><th></th></tr></thead><tbody>` +
    eps.map(e => `<tr><td>${esc(e.id)}</td><td><span class="tag">${esc(e.method)}</span></td><td><a class="link" target="_blank" href="${esc(e.path)}">${esc(e.path)}</a></td><td class="muted">${esc(e.description||"")}</td>
      <td><button class="ghost sm" onclick="deleteEndpoint('${esc(e.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`;
}
async function createEndpoint() {
  const id = document.getElementById("ep_id").value.trim();
  const path = document.getElementById("ep_path").value.trim();
  const method = document.getElementById("ep_method").value;
  const sql = document.getElementById("ep_sql").value.trim();
  if (!id || !path || !sql) { alert("端点ID/路径/SQL 必填"); return; }
  try { await api("/api/endpoints", { method:"POST", body: JSON.stringify({ id, path, method, sql }) }); }
  catch(e){ alert(e.message); return; }
  await openDev("endpoints");
}
async function deleteEndpoint(id) {
  if (!confirm(`删除端点 ${id}？`)) return;
  await api(`/api/endpoints/${id}`, { method:"DELETE" });
  await openDev("endpoints");
}
async function renderDevTokens(body) {
  const tokens = await api("/api/dev/tokens");
  body.innerHTML = `<h3>API 令牌</h3>
    <div class="row"><input id="tk_label" placeholder="用途标签(如 CI)" style="flex:1;"/>
      <button onclick="createDevToken()">签发</button></div>
    <table><thead><tr><th>标签</th><th>Token</th><th>签发</th><th>状态</th><th></th></tr></thead><tbody>` +
    tokens.map(t => `<tr><td>${esc(t.label)}</td><td><code>${esc(t.token.slice(0,12))}…</code></td><td class="muted">${esc(t.created)}</td>
      <td>${t.revoked?'<span class="tag">已撤销</span>':'<span class="tag ok">有效</span>'}</td>
      <td>${t.revoked?'':`<button class="ghost sm" onclick="revokeDevToken(${t.id})">撤销</button>`}</td></tr>`).join("") + `</tbody></table>
    <p class="muted">令牌用法：<code>curl -H "Authorization: Bearer &lt;token&gt;" http://localhost:8000/api/me</code></p>`;
}
async function createDevToken() {
  const label = document.getElementById("tk_label").value.trim();
  const r = await api("/api/dev/tokens", { method:"POST", body: JSON.stringify({ label }) });
  alert(`新令牌已签发（仅显示一次）：\n${r.token}\n\n请立即复制保存。`);
  await openDev("tokens");
}
async function revokeDevToken(id) {
  if (!confirm("撤销该令牌？")) return;
  await api(`/api/dev/tokens/${id}`, { method:"DELETE" });
  await openDev("tokens");
}
function renderApiRef(body) {
  const groups = [
    ["认证", [["POST","/api/auth/login","登录获取 JWT"],["GET","/api/me","当前用户"]]],
    ["本体", [["GET","/api/ontology/object-types","对象类型列表"],["GET","/api/ontology/stats","类型统计(对象数/动作数)"],["POST","/api/ontology/object-types","可视化建模"],["POST","/api/ontology/object-types/{id}/query","对象集查询(下推)"],["POST","/api/ontology/object-types/{id}/count","对象数计数"],["GET/POST","/api/ontology/link-types","链接类型"],["GET","/api/ontology/object-types/{id}/{oid}/graph","图遍历"],["POST/DELETE","/api/ontology/object-types/{id}/properties","属性增删"],["POST","/api/ontology/actions/{id}/execute","执行动作"],["GET","/api/ontology/osdk/{lang}","OSDK 生成"]]],
    ["数据", [["GET","/api/connectors","连接器列表"],["POST","/api/connectors/ingest","接入数据"],["POST","/api/sql","SQL 工作台(只读)"],["POST","/api/geo/near","空间邻近查询"],["POST","/api/media/upload","媒体上传"],["GET","/api/media","媒体列表"]]],
    ["管道", [["GET/POST","/api/pipelines","管道"],["POST","/api/pipelines/{id}/run","运行管道"],["GET","/api/functions","函数库"]]],
    ["AIP/模型", [["POST","/api/aip/chat","AIP 聊天"],["GET","/api/aip/usage","模型用量"],["GET/POST","/api/aip/evalsuites","评估套件"],["POST","/api/aip/evalsuites/{id}/run","运行评估"],["POST","/api/aip/playground","模型对比"],["POST","/api/aip/doc-extract","文档智能"],["GET","/api/models","模型目录"]]],
    ["应用", [["GET/POST","/api/apps","应用"],["GET","/api/apps/{id}/render","应用运行时 HTML"],["POST","/api/apps/{id}/run","运行工作流"],["GET","/api/apps/{id}/compare","版本对比"]]],
    ["治理", [["POST","/api/security/scan","敏感扫描"],["GET","/api/security/approvals","审批队列"],["GET","/api/security/retention","留存策略"],["POST","/api/security/markings/assign","安全标记"]]],
    ["运维", [["GET","/api/lineage","数据血缘"],["GET/POST","/api/monitors","监控规则"],["POST","/api/monitors/check-all","运行全部检查"],["GET","/api/activity","活动日志"]]],
    ["开发者", [["GET/POST","/api/dev/tokens","API 令牌"]]],
  ];
  body.innerHTML = groups.map(([g, eps]) => `<h3>${g}</h3><table><thead><tr><th>Method</th><th>Path</th><th>说明</th></tr></thead><tbody>` +
    eps.map(([m, p, d]) => `<tr><td><span class="tag">${m}</span></td><td><code>${esc(p)}</code></td><td>${esc(d)}</td></tr>`).join("") +
    `</tbody></table>`).join("");
}
function renderMarket(body) {
  const items = [
    { icon:"🛍️", name:"参考架构：数据集成", desc:"从连接器到本体的一键链路（58312320）", go:"openConnectors()" },
    { icon:"📊", name:"应用模板：仪表盘", desc:"指标卡 + 分组聚合", go:"showAppBuild('dashboard')" },
    { icon:"📝", name:"应用模板：表单", desc:"动作表单直连 Action", go:"showAppBuild('form')" },
    { icon:"🔀", name:"应用模板：工作流", desc:"多步动作编排", go:"showAppBuild('workflow')" },
    { icon:"🔎", name:"应用模板：视图", desc:"对象集只读视图", go:"showAppBuild('view')" },
    { icon:"🔌", name:"连接器：CSV/JSON/Parquet/REST/PG", desc:"一键接入并注册本体", go:"openConnectors()" },
  ];
  body.innerHTML = `<h3>🛍️ 市场（Marketplace）</h3><p class="muted">模板与组件市场：点击创建对应资源。</p>
    <div class="model-grid">` + items.map(i => `<div class="model-card">
      <div class="licon">${i.icon}</div><div class="ltitle">${esc(i.name)}</div><div class="ldesc">${esc(i.desc)}</div>
      <div class="row" style="margin-top:8px;"><button class="ghost sm" onclick="${i.go};openDev('market')">创建</button></div></div>`).join("") + `</div>`;
}

// ---------------- 新建启动器（9028755） ----------------
const LAUNCHER_ITEMS = [
  { cat:"对象类型", icon:"🧱", label:"新建对象类型", desc:"可视化定义字段/动作/链接", go:"openModeler()" },
  { cat:"管道", icon:"⚙️", label:"新建管道", desc:"编排多步 SQL 转换", go:"openPipelines()" },
  { cat:"数据", icon:"🔌", label:"接入数据", desc:"CSV/JSON/Parquet/REST/PG", go:"openConnectors()" },
  { cat:"应用", icon:"📱", label:"打开应用", desc:"对象类型生成的 CRUD 应用", go:"openApps()" },
  { cat:"AIP", icon:"💬", label:"AIP 分析师", desc:"自然语言查询/操作本体", go:"openAgent()" },
  { cat:"治理", icon:"🛡️", label:"用户与授权", desc:"ABAC 权限管理", go:"openAdmin()" },
];
function openLauncher() {
  document.getElementById("launcher_search").value = "";
  renderLauncher();
  show("launcher");
  document.getElementById("launcher_search").focus();
}
function closeLauncher() { hide("launcher"); }
function renderLauncher() {
  const q = document.getElementById("launcher_search").value.trim().toLowerCase();
  const cats = ["全部", ...new Set(LAUNCHER_ITEMS.map(i=>i.cat))];
  document.getElementById("launcher_cats").innerHTML = cats.map(c=>
    `<div class="lcat" onclick="filterLauncher('${c}')">${c}</div>`).join("");
  const items = LAUNCHER_ITEMS.filter(i => !q || (i.label+i.desc+i.cat).toLowerCase().includes(q));
  document.getElementById("launcher_items").innerHTML = items.map(i=>
    `<div class="litem" onclick="${i.go};closeLauncher()"><span class="licon">${i.icon}</span>
      <div><div class="ltitle">${i.label}</div><div class="ldesc">${i.desc}</div></div></div>`).join("")
    || `<p class="muted">无匹配项</p>`;
}
let _lcat = "全部";
function filterLauncher(cat) { _lcat = cat; const items = LAUNCHER_ITEMS.filter(i=>_lcat==="全部"||i.cat===_lcat);
  document.getElementById("launcher_items").innerHTML = items.map(i=>
    `<div class="litem" onclick="${i.go};closeLauncher()"><span class="licon">${i.icon}</span>
      <div><div class="ltitle">${i.label}</div><div class="ldesc">${i.desc}</div></div></div>`).join(""); }

// ---------------- 引导 ----------------
document.getElementById("loginBtn").onclick = login;
document.getElementById("logoutBtn").onclick = logout;
document.addEventListener("keydown", e => { if (e.shiftKey && (e.key==="N"||e.key==="n")) { if (document.getElementById("app").classList.contains("hidden")===false) openLauncher(); } });
if (TOKEN) enterApp(); else show("login");
