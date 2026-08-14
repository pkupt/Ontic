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
let CUR_PK = "id";
let CUR_MODULE = "home";
let CUR_QUERY_ROWS = [];
let CUR_OFFSET = 0;
const PAGE_SIZE = 50;
const SELECTED = new Set();
function starList(){ try{ return JSON.parse(localStorage.getItem("ontic_stars") || "[]"); } catch(e){ return []; } }
function toggleStar(id){ const s = starList(); const i = s.indexOf(id); if (i >= 0) s.splice(i, 1); else s.push(id); localStorage.setItem("ontic_stars", JSON.stringify(s)); loadSidebar(); }

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
  if (!q) { omnibarHistory(); return; }
  omnibarData().then(async d => {
    const res = [];
    d.types.filter(t => (t.name + " " + t.id).toLowerCase().includes(q)).slice(0, 4)
      .forEach(t => res.push({ icon: "🧩", label: t.name, sub: `对象类型 · ${t.count} 对象`, go: `openType('${t.id}')` }));
    d.apps.filter(a => (a.name + " " + a.id).toLowerCase().includes(q)).slice(0, 3)
      .forEach(a => res.push({ icon: "📱", label: a.name, sub: `应用 · ${a.type}`, go: `openAppView('${a.id}')` }));
    d.pls.filter(p => (p.name + " " + p.id).toLowerCase().includes(q)).slice(0, 3)
      .forEach(p => res.push({ icon: "⚙️", label: p.id, sub: "管道", go: "openPipelines()" }));
    // 对象实例搜索：对匹配类型查含关键字的对象（最多 4 个类型 × 3 行）
    const hitTypes = d.types.filter(t => (t.name + " " + t.id).toLowerCase().includes(q)).slice(0, 4);
    if (hitTypes.length) {
      const found = await Promise.all(hitTypes.map(async t => {
        try {
          const ot = await api(`/api/ontology/object-types/${t.id}`);
          const props = JSON.parse(ot.properties);
          const strProps = props.filter(p => p.type === "string").slice(0, 2);
          const conditions = strProps.map(p => ({ field: p.key, op: "contains", value: q }));
          const qr = await api(`/api/ontology/object-types/${t.id}/query`, { method:"POST",
            body: JSON.stringify({ where: conditions.length ? { op:"and", conditions } : null, limit: 3 }) });
          return (qr.rows || []).map(r => {
            const label = strProps.length ? r[strProps[0].key] : `${t.id}#${r[ot.primary_key]}`;
            const vid = JSON.stringify(r[ot.primary_key]);
            return { icon: "🎯", label: `${esc(label)}`, sub: `${esc(t.name)} · 对象`, go: `openType('${t.id}').then(()=>openObjectDrawer('${t.id}', ${vid}))` };
          });
        } catch (e) { return []; }
      }));
      found.flat().forEach(o => res.push(o));
    }
    list.innerHTML = (res.length ? res : [{ icon: "", label: "无匹配", sub: "", go: "omnibarHide()" }]).map(r =>
      `<div class="omni-item" onclick="${r.go};document.getElementById('omnibar').value='';omnibarHide()">${r.icon} <b>${esc(r.label)}</b> <span class="muted">${esc(r.sub)}</span></div>`).join("");
    list.classList.remove("hidden");
  });
}
function omnibarKey(e) {
  if (e.key === "Escape") omnibarHide();
  if (e.key === "Enter") {
    const q = document.getElementById("omnibar").value.trim();
    if (q) pushSearchHist(q);
    const f = document.querySelector("#omnibar-list .omni-item"); if (f) f.click();
  }
}
function pushSearchHist(q) {
  let h = JSON.parse(localStorage.getItem("ontic_sh") || "[]");
  h = [q, ...h.filter(x => x !== q)].slice(0, 5);
  localStorage.setItem("ontic_sh", JSON.stringify(h));
}
function omnibarHistory() {
  const h = JSON.parse(localStorage.getItem("ontic_sh") || "[]");
  const list = document.getElementById("omnibar-list");
  if (!h.length) { list.classList.add("hidden"); return; }
  list.innerHTML = `<div class="muted" style="padding:4px 10px;font-size:11px;">最近搜索</div>` + h.map(q =>
    `<div class="omni-item" onclick="document.getElementById('omnibar').value='${esc(q)}';omnibarSearch()">🕘 <b>${esc(q)}</b></div>`).join("");
  list.classList.remove("hidden");
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
// 铃铛下拉（最近活动直出，不跳页）
async function toggleBell(e) {
  if (e) e.stopPropagation();
  const pop = document.getElementById("bell-pop");
  if (!pop.classList.contains("hidden")) { pop.classList.add("hidden"); return; }
  const acts = await api("/api/activity");
  const r = document.getElementById("bellBtn").getBoundingClientRect();
  pop.style.left = Math.max(8, r.right - 340) + "px";
  pop.style.top = (r.bottom + 8) + "px";
  pop.innerHTML = `<div class="bell-head"><b>最近活动</b></div>` +
    (acts.length ? acts.slice(0, 8).map(a =>
      `<div class="bell-item"><span class="tag">${esc(a.kind)}</span><span class="bell-msg">${esc(a.message)}</span><span class="muted">${esc((a.ts||"").slice(11,16))}</span></div>`).join("")
      : `<div class="bell-item muted">暂无活动</div>`) +
    `<div class="bell-foot"><span class="link" onclick="openNotifications();toggleBell()">查看全部 →</span></div>`;
  pop.classList.remove("hidden");
}

// ---- P0 对象实例详情抽屉（59692531：属性 / 动作 / 链接 体验闭环） ----
function closeDrawer() { document.getElementById("drawer").classList.add("hidden"); }
// 对象类型图标（对齐 Palantir 对象视觉标识）
const TYPE_ICONS = {customer:"👤",product:"📦",order:"🧾",region:"🌐",city:"📍",lead:"🎯",event:"⚡",book:"📚",person:"🧑"};
function typeIcon(t){return TYPE_ICONS[t]||"🧩";}
function objTitleOf(props,row,pk){
  const nf = props.find(p => /^(name|title|label)$/i.test(p.key));
  if(nf && row[nf.key] != null && row[nf.key] !== "") return String(row[nf.key]);
  return `${pk}: ${row[pk] ?? ""}`;
}
async function openObjectDrawer(typeId, objId) {
  const drawer = document.getElementById("drawer");
  drawer.classList.remove("hidden");
  drawer.innerHTML = `<div class="obj-title"><span class="obj-ico">${typeIcon(typeId)}</span>
    <h2>${esc(typeId)} #${esc(objId)}</h2>
    <button class="ghost sm close-x" onclick="closeDrawer()">✕</button></div><p class="muted">加载中…</p>`;
  try {
    const [ot, acts, links, apps] = await Promise.all([
      api(`/api/ontology/object-types/${typeId}`),
      api("/api/ontology/actions"),
      api(`/api/ontology/object-types/${typeId}/links`),
      api("/api/apps"),
    ]);
    const props = JSON.parse(ot.properties);
    const pk = ot.primary_key;
    const row = (await api(`/api/ontology/object-types/${typeId}/query`, { method:"POST",
      body: JSON.stringify({ where: { op:"eq", field: pk, value: objId }, limit: 1 }) })).rows[0] || {};
    const myActs = acts.filter(a => a.object_type === typeId);
    const myApps = apps.filter(a => a.object_type === typeId);
    const title = objTitleOf(props, row, pk);
    // 属性分组：基本信息（id/name/title/pk）+ 业务属性（其余）
    const basicKeys = new Set(["id","name","title","label",pk]);
    const basic = props.filter(p => basicKeys.has(p.key));
    const biz = props.filter(p => !basicKeys.has(p.key));
    const propCard = (ps) => ps.length ? `<div class="prop-grid">` + ps.map(p =>
      `<div class="prop-card"><div class="prop-k">${esc(p.title)}${p.sensitive?' <span class="tag" style="color:var(--warn)">🔒</span>':''}</div>
       <div class="prop-v">${esc(row[p.key] ?? "—")}</div></div>`).join("") + `</div>` : "";
    let html = `<div class="obj-title"><span class="obj-ico">${typeIcon(typeId)}</span>
      <div style="flex:1;min-width:0;"><h2 style="margin:0;">${esc(title)}</h2>
      <div class="muted" style="font-size:12px;">${esc(ot.name)} · ${esc(pk)}=${esc(objId)}</div></div>
      <span class="badge">${esc(typeId)}</span>
      <button class="ghost sm close-x" onclick="closeDrawer()">✕</button></div>`;
    if (basic.length) html += `<h3 class="sec">基本信息</h3>${propCard(basic)}`;
    if (biz.length) html += `<h3 class="sec">业务属性</h3>${propCard(biz)}`;
    html += `<h3 class="sec">动作（${myActs.length}）</h3>` +
      (myActs.length ? `<div class="row" style="flex-wrap:wrap;gap:6px;">` + myActs.map(a =>
        `<button class="ghost sm" onclick="drawerAction('${typeId}','${a.id}','${esc(a.name)}')">▶ ${esc(a.name)}</button>`).join("") + `</div>` : `<p class="muted">无动作。</p>`) +
      `<div id="drawer_act"></div>
      <h3 class="sec">在应用中打开（跨应用交互）</h3><div id="drawer_apps"></div>
      <h3 class="sec">关联对象（关系图）</h3><div id="drawer_links"></div>
      <h3 class="sec">变更历史</h3><div id="drawer_tl"></div>`;
    drawer.innerHTML = html;
    const appBox = document.getElementById("drawer_apps");
    appBox.innerHTML = myApps.length ? `<div class="row" style="flex-wrap:wrap;gap:6px;">` + myApps.map(a =>
      `<button class="ghost sm" onclick="openAppView('${esc(a.id)}', ${JSON.stringify(objId)})">📱 ${esc(a.name)}（${esc(a.type)}）</button>`).join("") + `</div>`
      : `<p class="muted">该类型暂无应用（到应用模块构建后即可在此打开）。</p>`;
    await renderDrawerGraph(typeId, objId, links, title);
    await loadDrawerTimeline(typeId, objId);
  } catch (e) {
    drawer.innerHTML = `<div class="obj-title"><h2>${esc(typeId)} #${esc(objId)}</h2>
      <button class="ghost sm close-x" onclick="closeDrawer()">✕</button></div>
      <pre style="color:var(--danger)">${esc(e.message)}</pre>`;
  }
}
// 关联对象放射关系图（中心=当前对象，周围=关联对象，节点可点击跳转）
async function renderDrawerGraph(typeId, objId, links, centerTitle) {
  const box = document.getElementById("drawer_links");
  if (!links.length) { box.innerHTML = `<p class="muted">无关联对象。</p>`; return; }
  const nodes = []; // {type,id,title,linkName,icon}
  for (const lk of links) {
    try {
      const res = await api(`/api/ontology/object-types/${typeId}/${objId}/links/${lk.id}`);
      const other = res.direction === "forward" ? res.target_type : res.source_type;
      const ot = await api(`/api/ontology/object-types/${other}`);
      const opk = ot.primary_key;
      const oprops = JSON.parse(ot.properties);
      for (const r of (res.rows || [])) {
        nodes.push({ type: other, id: r[opk], title: objTitleOf(oprops, r, opk), linkName: lk.name, icon: typeIcon(other) });
      }
    } catch (e) {}
  }
  if (!nodes.length) { box.innerHTML = `<p class="muted">无关联对象。</p>`; return; }
  const W = 520, H = Math.max(280, 90 + nodes.length * 16), cx = W/2, cy = H/2;
  const R = Math.min(W, H)/2 - 70;
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="obj-graph">`;
  nodes.forEach((n, i) => {
    const ang = (i / nodes.length) * Math.PI * 2 - Math.PI/2;
    n.x = cx + Math.cos(ang) * R;
    n.y = cy + Math.sin(ang) * R;
    svg += `<line x1="${cx}" y1="${cy}" x2="${n.x}" y2="${n.y}" stroke="#4f8cff" stroke-width="1" opacity="0.35"/>`;
    const lx = cx + Math.cos(ang) * R * 0.5, ly = cy + Math.sin(ang) * R * 0.5;
    svg += `<text x="${lx}" y="${ly-4}" fill="#6b7280" font-size="9" text-anchor="middle">${esc(n.linkName)}</text>`;
  });
  // 中心节点（当前对象）
  svg += `<g><circle cx="${cx}" cy="${cy}" r="36" fill="#1e3a5f" stroke="#4f8cff" stroke-width="2.5"/>
    <text x="${cx}" y="${cy-2}" font-size="20" text-anchor="middle">${typeIcon(typeId)}</text>
    <text x="${cx}" y="${cy+15}" fill="#e6e9ef" font-size="10" text-anchor="middle">${esc(String(centerTitle).slice(0,9))}</text></g>`;
  // 周围节点（关联对象，可点击）
  nodes.forEach(n => {
    const vid = JSON.stringify(n.id);
    svg += `<g onclick="openObjectDrawer('${esc(n.type)}', ${vid})" style="cursor:pointer;">
      <circle cx="${n.x}" cy="${n.y}" r="28" fill="#171a21" stroke="#3ecf8e" stroke-width="1.5"/>
      <text x="${n.x}" y="${n.y-1}" font-size="15" text-anchor="middle">${n.icon}</text>
      <text x="${n.x}" y="${n.y+13}" fill="#e6e9ef" font-size="9" text-anchor="middle">${esc(String(n.title).slice(0,9))}</text>
      <text x="${n.x}" y="${n.y+42}" fill="#6b7280" font-size="8" text-anchor="middle">${esc(n.type)}</text></g>`;
  });
  svg += `</svg><p class="muted" style="text-align:center;margin:6px 0;">点击节点查看关联对象详情（共 ${nodes.length} 个关联对象）</p>`;
  box.innerHTML = svg;
}
async function loadDrawerTimeline(typeId, objId) {
  const box = document.getElementById("drawer_tl");
  try {
    const acts = await api("/api/activity");
    const mine = acts.filter(a => a.message.includes(typeId) && a.message.includes(`#${objId}`)).slice(0, 8);
    box.innerHTML = mine.length ? mine.map(a =>
      `<div class="act-row"><span class="tag">${esc(a.kind)}</span><span class="muted">${esc((a.ts||"").slice(0,16).replace("T"," "))}</span><span>${esc(a.message)}</span></div>`).join("")
      : `<p class="muted">暂无该对象的变更记录。</p>`;
  } catch (e) { box.innerHTML = `<p class="muted">加载失败</p>`; }
}
async function drawerAction(typeId, actionId, name) {  const acts = await api("/api/ontology/actions");
  const a = acts.find(x => x.id === actionId);
  const params = JSON.parse(a.parameters).filter(p => p.name !== "id");
  document.getElementById("drawer_act").innerHTML = `<h3>执行 ${esc(name)}</h3>
    ${params.map(p => `<div class="row"><label>${esc(p.name)}</label><input id="da_${esc(p.name)}" placeholder="${esc(p.type)}"/></div>`).join("")}
    <div class="row"><button onclick="runDrawerAction('${actionId}')">执行</button></div>`;
}
async function runDrawerAction(actionId) {
  const acts = await api("/api/ontology/actions");
  const a = acts.find(x => x.id === actionId);
  const params = JSON.parse(a.parameters).filter(p => p.name !== "id");
  const body = {};
  params.forEach(p => { const v = document.getElementById(`da_${p.name}`)?.value; if (v !== "") body[p.name] = v; });
  // 从抽屉标题取对象 id
  const title = document.querySelector("#drawer .obj-title h2")?.textContent || "";
  const id = title.split("#").pop();
  if (id && a.operation !== "create") body.id = id;
  try {
    const r = await api(`/api/ontology/actions/${actionId}/execute`, { method:"POST", body: JSON.stringify({ params: body }) });
    document.getElementById("drawer_act").innerHTML = `<pre>${JSON.stringify(r.detail, null, 2)}</pre>`;
    // 刷新抽屉数据
    const t = title.split(" #")[0];
    await openObjectDrawer(t, id);
  } catch(e) { document.getElementById("drawer_act").innerHTML = `<pre style="color:var(--danger)">${esc(e.message)}</pre>`; }
}

// ---- P0 首页新手引导卡 ----
function guideCard() {
  if (localStorage.getItem("ontic_guide_closed")) return "";
  return `<div class="guide"><div class="row" style="justify-content:space-between;">
      <strong>🚀 开始使用 Ontic</strong><button class="ghost sm" onclick="localStorage.setItem('ontic_guide_closed','1');document.getElementById('guide_box')?.remove()">✕</button></div>
    <div class="guide-steps">
      <div class="guide-step"><div class="n">1</div><div>接入数据</div><p class="muted">用连接器导入表，自动注册为对象类型</p><button class="ghost sm" onclick="openConnectors()">去接入</button></div>
      <div class="guide-step"><div class="n">2</div><div>定义本体</div><p class="muted">补属性、建链接、配动作</p><button class="ghost sm" onclick="openModeler()">去建模</button></div>
      <div class="guide-step"><div class="n">3</div><div>消费本体</div><p class="muted">问 AIP、建应用或写 OSDK</p><button class="ghost sm" onclick="openAgent()">问 AIP</button></div>
    </div></div>`;
}

function authHeaders() {
  return { "Content-Type": "application/json", Authorization: `Bearer ${TOKEN}` };
}
// 当前项目（多项目/空间）：默认 default，切换后资源列表自动按项目过滤
let CUR_PROJECT = "default";
const PROJECT_LIST_ENDPOINTS = ["/api/ontology/object-types", "/api/apps", "/api/pipelines", "/api/projects", "/api/connectors"];
async function api(path, opts = {}) {
  let p = path;
  if ((!opts.method || opts.method === "GET") && CUR_PROJECT && PROJECT_LIST_ENDPOINTS.some(e => path === e)) {
    p = path + (path.includes("?") ? "&" : "?") + "project=" + encodeURIComponent(CUR_PROJECT);
  }
  // 创建资源时自动归属当前项目
  if (opts.method === "POST" && ["/api/ontology/object-types", "/api/apps", "/api/pipelines"].includes(path) && opts.body) {
    try {
      const b = JSON.parse(opts.body);
      if (CUR_PROJECT) b.project_id = CUR_PROJECT;
      opts = { ...opts, body: JSON.stringify(b) };
    } catch(e) {}
  }
  const r = await fetch(API + p, { ...opts, headers: { ...authHeaders(), ...(opts.headers || {}) } });
  if (r.status === 401) { logout(); throw new Error("未授权"); }
  if (!r.ok) throw new Error((await r.text()) || r.status);
  return r.json();
}
async function setProject(v) {
  CUR_PROJECT = v || "default";
  localStorage.setItem("ontic_project", CUR_PROJECT);
  await renderSidebar();
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><p class="muted">已切换到项目 ${esc(CUR_PROJECT)}，选择模块继续。</p></div>`;
}
function show(id) { document.getElementById(id).classList.remove("hidden"); }
function hide(id) { document.getElementById(id).classList.add("hidden"); }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function opOptionsHTML(sel) {
  const ops = [["eq","="],["ne","≠"],["gt",">"],["gte","≥"],["lt","<"],["lte","≤"],["contains","包含"],["isNull","为空"]];
  return ops.map(([v,t]) => `<option value="${v}" ${v===sel?"selected":""}>${t}</option>`).join("");
}
// 轻量 toast 提示（替代部分 alert）
function toast(msg, ms = 2400) {
  let t = document.getElementById("ontic_toast");
  if (!t) { t = document.createElement("div"); t.id = "ontic_toast"; t.style.cssText = "position:fixed;bottom:22px;left:50%;transform:translateX(-50%);background:#1f2329;color:#fff;padding:9px 18px;border-radius:10px;font-size:13px;z-index:200;box-shadow:0 8px 30px rgba(0,0,0,.5);max-width:80vw;"; document.body.appendChild(t); }
  t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => t.style.display = "none", ms);
}
// 通用 CSV 导出（查询结果一键下载，Foundry 数据导出能力）
function exportCSV(rows, name) {
  if (!rows || !rows.length) { toast("无数据可导出"); return; }
  const cols = Object.keys(rows[0]);
  const cell = v => { const s = String(v == null ? "" : v); return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s; };
  const csv = [cols.join(","), ...rows.map(r => cols.map(c => cell(r[c])).join(","))].join("\n");
  const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = (name || "ontic-export") + ".csv"; a.click();
  URL.revokeObjectURL(a.href);
  toast(`已导出 ${rows.length} 行`);
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
  CUR_PROJECT = localStorage.getItem("ontic_project") || "default";
  ME = await api("/api/me");
  document.getElementById("who").textContent = `${ME.username} · ${ME.role}`;
  // 首启安全提示：admin 默认密码
  if (ME.default_pw) {
    const banner = document.createElement("div");
    banner.className = "warn-banner";
    banner.id = "pw-warn";
    banner.style.margin = "8px 12px 0";
    banner.innerHTML = `⚠️ 你仍在使用默认密码，请尽快修改 → <a class="link" onclick="openChangePw()">立即修改</a>`;
    document.querySelector(".topbar").after(banner);
  }
  await renderModnav();
  await loadSidebar();
  await updateBell();
  await openHome();
}
function openChangePw() {
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel" style="max-width:420px;"><h2>🔑 修改密码</h2>
    <div class="row"><label>旧密码</label><input id="pw_old" type="password" style="flex:1;"/></div>
    <div class="row"><label>新密码</label><input id="pw_new" type="password" placeholder="至少 8 位，含字母和数字" style="flex:1;"/></div>
    <div class="row"><button class="primary" onclick="doChangePw()">修改</button><span id="pw_msg" class="muted"></span></div></div>`;
}
async function doChangePw() {
  const msg = document.getElementById("pw_msg");
  try {
    await api("/api/auth/change-password", { method:"POST", body: JSON.stringify({
      old_password: document.getElementById("pw_old").value,
      new_password: document.getElementById("pw_new").value }) });
    msg.textContent = "✅ 密码已修改";
    const b = document.getElementById("pw-warn"); if (b) b.remove();
    ME = await api("/api/me");
  } catch(e) { msg.textContent = "❌ " + e.message; }
}

// 侧栏 = 当前模块的上下文导航（不再平铺全部内容）
async function loadSidebar() {
  const sb = document.getElementById("sidebar");
  // 顶部项目切换器（含资源统计）
  try {
    const projects = await fetch(API + "/api/projects", { headers: authHeaders() }).then(r => r.json());
    const sel = document.getElementById("projectSel");
    if (sel) {
      sel.innerHTML = projects.map(p =>
        `<option value="${p.id}" ${CUR_PROJECT === p.id ? "selected" : ""}>📁 ${esc(p.name)} (${p.types}类型/${p.apps}应用)</option>`).join("");
    }
  } catch(e) {}
  if (CUR_MODULE === "ontology") {
    const stats = await api("/api/ontology/stats");
    const stars = starList();
    stats.sort((a, b) => (stars.includes(b.id) - stars.includes(a.id)) || (b.count - a.count));
    let html = `<h3>对象类型 (${stats.length})</h3>`;
    stats.forEach(t => {
      html += `<div class="item type" onclick="openType('${t.id}')">
          <span class="tname">${esc(t.name)}</span>
          <span style="display:flex;gap:6px;align-items:center;">
            <span class="badge">${t.count}</span>
            <span class="star" title="${stars.includes(t.id)?"取消收藏":"收藏"}" onclick="event.stopPropagation();toggleStar('${t.id}')">${stars.includes(t.id)?"⭐":"☆"}</span>
          </span></div>`;
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
      <div class="item" onclick="openCompass()">🗂️ 资源管理器</div>
      <div class="item" onclick="openContour()">📐 Contour 分析</div>
      <div class="item" onclick="openLineage()">🧬 数据血缘</div>
      <div class="item" onclick="openSql()">🗄️ SQL 工作台</div>
      <div class="item" onclick="openGeo()">📍 空间查询</div>
      <div class="item" onclick="openTs()">📈 时间序列</div>
      <div class="item" onclick="openLifetime()">⏳ 生命周期</div>
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
      <div class="item" onclick="openChatbots()">🤖 Chatbot Studio</div>
      <div class="item" onclick="openKnowledge()">📚 知识库</div>
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
    <div class="row" style="justify-content:space-between;"><span class="muted">对象类型、动作与链接的结构化定义层。点击类型进入详情。</span>
      <button class="ghost sm" onclick="showTypeImport()">⬆ 导入定义</button></div>
    <div id="type_import"></div>
    <table><thead><tr><th>对象类型</th><th>对象数</th><th>动作</th><th>描述</th></tr></thead><tbody>` +
    stats.map(t => `<tr><td><a onclick="openType('${t.id}')" class="link">${esc(t.name)}</a></td>
      <td>${t.count}</td><td>${t.actions.length}</td><td class="muted">${esc(t.description || "")}</td></tr>`).join("") +
    `</tbody></table></div>`;
}
function showTypeImport() {
  const box = document.getElementById("type_import");
  box.innerHTML = `<div class="panel sm"><p class="muted">粘贴导出的定义 JSON（可选含 rows 数据）</p>
    <textarea id="imp_def" style="width:100%;height:110px;font-family:monospace;" placeholder='{"definition":{...},"rows":[...]}'></textarea>
    <div class="row"><button onclick="importTypeDef()">导入</button></div></div>`;
}
async function importTypeDef() {
  const raw = document.getElementById("imp_def").value.trim();
  if (!raw) { toast("请粘贴定义 JSON"); return; }
  let body; try { body = JSON.parse(raw); } catch(e){ toast("JSON 解析失败"); return; }
  if (!body.definition) { toast("缺少 definition 字段"); return; }
  const r = await api("/api/ontology/object-types/import", { method:"POST", body: JSON.stringify(body) });
  toast(`已导入 ${r.object_type}（${r.rows} 行）`);
  await loadSidebar(); await openOntology();
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
    <div id="guide_box">${guideCard()}</div>
    <div class="panel">
      <h2>👋 你好，${esc(ME.username)}</h2>
      <p class="muted">角色 ${esc(ME.role)} · 平台共 ${stats.length} 个对象类型 / ${total} 个对象 / ${apps.length} 个应用 / ${pls.length} 个管道</p>
      <div class="row" style="margin-top:10px;">
        <button onclick="openLauncher()">＋ 新建</button>
        <button class="ghost" onclick="setModule('ontology')">🧩 本体</button>
        <button class="ghost" onclick="setModule('data')">🔌 接入数据</button>
        <button class="ghost" onclick="setModule('pipeline')">⚙️ 管道</button>
        <button class="ghost" onclick="setModule('aip')">💬 AIP</button>
        <button class="ghost" onclick="setModule('apps')">📱 应用</button>
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
    <div class="crumbs"><span class="link" onclick="setModule('home')">🏠</span> › <span class="link" onclick="setModule('ontology')">本体</span> › <b>${esc(ot.name)}</b></div>
    <div class="panel">
      <div class="row" style="justify-content:space-between;">
        <div><h2>${esc(ot.name)}</h2><p class="muted">${esc(ot.description || "")} · 主键 ${esc(ot.primary_key)} · 表 ${esc(ot.backing_table)}</p></div>
        <span class="tag ok">Active</span>
      </div>
      ${tabBar("overview", [
        {id:"overview",label:"概览"},{id:"properties",label:"属性"},{id:"actions",label:"动作"},
        {id:"links",label:"链接"},{id:"data",label:"数据"},{id:"version",label:"版本"}])}
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
  else if (tab === "version") await renderVersion();
}

async function renderOverview() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties);
  let total = 0;
  try { total = (await api(`/api/ontology/object-types/${CUR_TYPE}/count`, { method:"POST", body:"{}" })).total; } catch(e){}
  const acts = (await api("/api/ontology/actions")).filter(a => a.object_type === CUR_TYPE);
  const links = await api(`/api/ontology/object-types/${CUR_TYPE}/links`);
  const trendHtml = await buildTrendHtml();
  const box = document.getElementById("tab_body");
  box.innerHTML = `
    <div class="row"><button class="ghost sm" onclick="exportTypeDef()">⬇ 导出定义</button>
      <button class="ghost sm" onclick="cloneType()">📋 克隆</button></div>
    <div class="stat-row">
      <div class="stat"><div class="stat-n">${total}</div><div class="stat-l">对象数</div></div>
      <div class="stat"><div class="stat-n">${props.length}</div><div class="stat-l">属性</div></div>
      <div class="stat"><div class="stat-n">${acts.length}</div><div class="stat-l">动作</div></div>
      <div class="stat"><div class="stat-n">${links.length}</div><div class="stat-l">链接类型</div></div>
    </div>
    <h3>Danger zone</h3>
    <div class="row">
      <button class="ghost sm" style="color:#d9534f;" onclick="clearTypeData()">🗑 清空数据</button>
      <button class="ghost sm" style="color:#d9534f;" onclick="deleteType()">✖ 删除类型（含动作/链接/授权/数据表）</button>
    </div>
    <h3>General information</h3>
    <table><tbody>
      <tr><td>状态</td><td><span class="tag ok">Active</span></td></tr>
      <tr><td>主键</td><td>${esc(ot.primary_key)}</td></tr>
      <tr><td>Backing table</td><td>${esc(ot.backing_table)}</td></tr>
      <tr><td>聚合使用量</td><td>${total} 次读取</td></tr>
    </tbody></table>
    <h3>近 7 天活动趋势（真实活动日志）</h3>
    <div class="spark">${trendHtml}</div>`;
}
async function buildTrendHtml() {
  // 真实数据：按活动日志（activity 表）统计最近 7 天操作数
  try {
    const acts = await api("/api/activity");
    const byDay = {};
    const now = new Date();
    acts.forEach(a => {
      const d = new Date(a.ts);
      if (isNaN(d)) return;
      const key = d.toDateString();
      byDay[key] = (byDay[key] || 0) + 1;
    });
    const trend = [];
    for (let i = 6; i >= 0; i--) {
      const day = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
      trend.push({ date: day, n: byDay[day.toDateString()] || 0 });
    }
    const vals = trend.map(t => t.n);
    if (!vals.some(v => v > 0)) return `<p class="muted">最近 7 天暂无活动记录。</p>`;
    const labels = trend.map(t => `${t.date.getMonth() + 1}/${t.date.getDate()}`).join(" · ");
    return `<div>${sparkline(vals)}<p class="muted" style="text-align:center;font-size:11px;margin:2px 0 0;">${labels}（每日操作数）</p></div>`;
  } catch(e) { return `<p class="muted">活动数据加载失败。</p>`; }
}
async function exportTypeDef() {
  const d = await api(`/api/ontology/object-types/${CUR_TYPE}/export`);
  const blob = new Blob([JSON.stringify(d, null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `${CUR_TYPE}.ontic.json`; a.click();
  URL.revokeObjectURL(a.href);
  toast(`已导出 ${CUR_TYPE} 定义（含 ${d.rows.length} 行数据）`);
}
async function cloneType() {
  const newId = prompt("新类型 ID：");
  if (!newId) return;
  const r = await api(`/api/ontology/object-types/${CUR_TYPE}/clone`, { method:"POST", body: JSON.stringify({ new_id: newId, include_data: true }) });
  toast(`已克隆 → ${r.object_type}（${r.rows} 行）`);
  await loadSidebar();
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
      <button class="ghost" onclick="batchPropRow()">＋＋ 批量添加</button>
      <button class="ghost" style="color:var(--danger)" onclick="clearProps()">Remove all properties</button>
    </div>
    <div id="prop_add"></div>
    <div id="prop_batch"></div>`;
  const tb = document.getElementById("prop_rows");
  tb.innerHTML = props.map(p => {
    const ctags = [];
    if (p.required) ctags.push("必填");
    if (p.enum) ctags.push("枚举:" + p.enum.join("/"));
    if (p.pattern) ctags.push("正则");
    if (p.sensitive) ctags.push("🔒");
    return `<tr>
      <td>${esc(p.key)}</td><td>${esc(p.title)} ${ctags.map(t=>`<span class="tag" style="color:var(--warn)">${esc(t)}</span>`).join("")}</td><td>${esc(p.type)}</td>
      <td>${p.key===ot.primary_key ? '<span class="muted">主键</span>' : `<button class="ghost sm" onclick="removeProp('${esc(p.key)}')">🗑 删除</button>`}</td>
    </tr>`;
  }).join("");
}
function batchPropRow() {
  const box = document.getElementById("prop_batch");
  box.innerHTML = `<div class="panel sm"><p class="muted">每行一个：<code>key:类型:标题</code>（类型 ∈ string/integer/double/boolean），如 <code>note:string:备注</code></p>
    <textarea id="batch_text" placeholder="key:type:title&#10;note:string:备注&#10;qty:integer:数量" style="width:100%;height:90px;"></textarea>
    <div class="row"><button onclick="submitBatchProps()">批量添加</button></div></div>`;
}
async function submitBatchProps() {
  const lines = document.getElementById("batch_text").value.split("\n").map(s => s.trim()).filter(Boolean);
  let ok = 0, errs = [];
  for (const line of lines) {
    const [key, type = "string", ...rest] = line.split(":");
    const title = rest.join(":") || key;
    try { await api(`/api/ontology/object-types/${CUR_TYPE}/properties`, { method:"POST", body: JSON.stringify({ key, type, title }) }); ok++; }
    catch(e){ errs.push(`${key}: ${e.message}`); }
  }
  alert(`成功 ${ok} 个${errs.length ? "，失败：" + errs.join("；") : ""}`);
  await renderProperties();
}
async function clearProps() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties).filter(p => p.key !== ot.primary_key);
  if (!props.length) { alert("没有可删除的属性（主键除外）。"); return; }
  if (!confirm(`删除全部非主键属性（${props.length} 个）？对应数据列将一并移除。`)) return;
  let ok = 0;
  for (const p of props) { try { await api(`/api/ontology/object-types/${CUR_TYPE}/properties/${p.key}`, { method:"DELETE" }); ok++; } catch(e){} }
  alert(`已删除 ${ok}/${props.length} 个属性`);
  await renderProperties();
}
function addPropRow() {
  const box = document.getElementById("prop_add");
  box.innerHTML = `<div class="row">
    <input id="np_key" placeholder="字段key" style="width:140px;"/>
    <select id="np_type"><option value="string">string</option><option value="integer">integer</option><option value="double">double</option><option value="boolean">boolean</option><option value="date">date</option><option value="timestamp">timestamp</option><option value="geohash">geohash</option><option value="attachment">attachment</option></select>
    <input id="np_title" placeholder="标题" style="flex:1;"/>
    <label style="display:flex;align-items:center;gap:4px;font-size:13px;"><input id="np_sensitive" type="checkbox"/>敏感</label>
    <label style="display:flex;align-items:center;gap:4px;font-size:13px;"><input id="np_required" type="checkbox"/>必填</label>
    <button onclick="submitProp()">保存</button></div>
    <div class="row"><input id="np_enum" placeholder="枚举值(逗号分隔，如 active,inactive)" style="flex:1;"/>
      <input id="np_pattern" placeholder="正则(如 ^[A-Z]{3}$)" style="flex:1;"/></div>`;
}
async function submitProp() {
  const key = document.getElementById("np_key").value.trim();
  const type = document.getElementById("np_type").value;
  const title = document.getElementById("np_title").value.trim();
  const sensitive = document.getElementById("np_sensitive")?.checked || false;
  const required = document.getElementById("np_required")?.checked || false;
  const enumRaw = document.getElementById("np_enum")?.value.trim();
  const pattern = document.getElementById("np_pattern")?.value.trim();
  const enumList = enumRaw ? enumRaw.split(",").map(s => s.trim()).filter(Boolean) : null;
  if (!key) { alert("字段key必填"); return; }
  try { await api(`/api/ontology/object-types/${CUR_TYPE}/properties`, { method:"POST", body: JSON.stringify({ key, type, title, sensitive, required, enum: enumList, pattern }) }); }
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
    acts.map(a => `<tr><td>${esc(a.name)}${a.needs_approval ? ' <span class="tag" style="color:var(--warn)">⏳ 需审批</span>' : ""}</td><td><span class="tag">${esc(a.operation)}</span></td><td class="muted">${esc(a.description||"")}</td>
      <td><button class="ghost sm" onclick="openAction('${a.id}')">执行</button>
          <button class="ghost sm" style="color:#d9534f;" onclick="deleteAction('${a.id}')">删除</button></td></tr>`).join("") + `</tbody></table>`;
}
async function deleteAction(aid) {
  if (!confirm(`删除动作 ${aid}？`)) return;
  await api(`/api/ontology/actions/${aid}`, { method:"DELETE" });
  toast(`已删除动作 ${aid}`);
  await renderActions();
}
async function deleteType() {
  if (!confirm(`⚠️ 删除对象类型 ${CUR_TYPE}？\n将级联删除：全部动作 / 链接 / 授权 / 数据表！此操作不可逆。`)) return;
  if (!confirm(`再次确认：真的删除 ${CUR_TYPE} 吗？`)) return;
  await api(`/api/ontology/object-types/${CUR_TYPE}`, { method:"DELETE" });
  toast(`已删除对象类型 ${CUR_TYPE}`);
  setModule("ontology");
}
async function clearTypeData() {
  if (!confirm(`清空 ${CUR_TYPE} 的全部数据？类型定义保留。`)) return;
  await api(`/api/ontology/object-types/${CUR_TYPE}/clear`, { method:"POST", body:"{}" });
  toast(`已清空 ${CUR_TYPE} 数据`);
  await renderOverview();
}

// 链接面板（辐射图 4178460 + 图探索 M2）
async function renderLinks() {
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const links = await api(`/api/ontology/object-types/${CUR_TYPE}/links`);
  const types = await api("/api/ontology/object-types");
  const box = document.getElementById("tab_body");
  box.innerHTML = `
    <h3 class="sec">链接类型（${links.length}）</h3>
    <div id="lk_list"></div>
    <h3 class="sec">关系图（关联对象类型 · 点击节点跳转）</h3>
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
  // 关系图：中心=当前类型，周围=关联类型，节点可点击跳转；hover 显示对象数
  const W=680,H=320,cx=340,cy=160;
  let counts = {};
  try { counts = Object.fromEntries((await api("/api/ontology/stats")).map(s => [s.id, s.count])); } catch(e){}
  const others = links.map(l => ({type: l.source_type===CUR_TYPE ? l.target_type : l.source_type, name: l.name, link: l.id}));
  let svg = `<svg viewBox="0 0 ${W} ${H}" class="obj-graph">`;
  others.forEach((o,i) => {
    const a = (2*Math.PI*i)/Math.max(others.length,1) - Math.PI/2;
    const x = cx + 140*Math.cos(a), y = cy + 120*Math.sin(a);
    svg += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="#4f8cff" stroke-width="1" opacity="0.35">
      <title>${esc(o.name)}（${esc(o.link)}）</title></line>`;
    const lx = cx + 70*Math.cos(a), ly = cy + 60*Math.sin(a);
    svg += `<text x="${lx}" y="${ly-3}" fill="#6b7280" font-size="9" text-anchor="middle">${esc(o.name)}</text>`;
  });
  svg += `<g><circle cx="${cx}" cy="${cy}" r="38" fill="#1e3a5f" stroke="#4f8cff" stroke-width="2.5"/>
    <text x="${cx}" y="${cy-2}" font-size="20" text-anchor="middle">${typeIcon(CUR_TYPE)}</text>
    <text x="${cx}" y="${cy+15}" fill="#e6e9ef" font-size="11" text-anchor="middle">${esc(ot.name)}</text>
    <title>${esc(ot.name)} · 当前类型 · ${counts[CUR_TYPE] !== undefined ? counts[CUR_TYPE] + " 个对象" : "点击查看"} </title></g>`;
  others.forEach((o,i) => {
    const a = (2*Math.PI*i)/Math.max(others.length,1) - Math.PI/2;
    const x = cx + 140*Math.cos(a), y = cy + 120*Math.sin(a);
    const n = counts[o.type];
    svg += `<g class="g-node" onclick="openType('${esc(o.type)}')" style="cursor:pointer;">
      <circle cx="${x}" cy="${y}" r="30" fill="#171a21" stroke="#3ecf8e" stroke-width="1.5"/>
      <text x="${x}" y="${y-1}" font-size="16" text-anchor="middle">${typeIcon(o.type)}</text>
      <text x="${x}" y="${y+12}" fill="#e6e9ef" font-size="9" text-anchor="middle">${esc(o.type)}${n !== undefined ? " · " + n : ""}</text>
      <title>${esc(o.type)} · ${n !== undefined ? n + " 个对象" : "对象数未知"} · 点击进入类型</title></g>`;
  });
  svg += `</svg><p class="muted" style="text-align:center;margin:6px 0;">${others.length} 个关联对象类型 · 悬停看对象数，点击节点进入类型</p>`;
  document.getElementById("radial").innerHTML = svg;
  // 链接列表 + 删除
  document.getElementById("lk_list").innerHTML = links.length
    ? `<table><thead><tr><th>链接</th><th>方向</th><th>外键</th><th></th></tr></thead><tbody>` +
      links.map(l => `<tr><td><b>${esc(l.name)}</b> <span class="muted">(${esc(l.id)})</span></td>
        <td class="muted">${esc(l.source_type)} → ${esc(l.target_type)}</td>
        <td class="muted">${esc(l.source_fk || "—")}</td>
        <td><button class="ghost sm" style="color:#d9534f;" onclick="deleteLink('${esc(l.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`
    : `<p class="muted">暂无链接。</p>`;
}
async function deleteLink(lid) {
  if (!confirm(`删除链接 ${lid}？`)) return;
  await api(`/api/ontology/link-types/${lid}`, { method:"DELETE" });
  toast(`已删除链接 ${lid}`);
  await renderLinks();
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
// 版本 tab：检查点（打点/恢复/差异）+ 分支（创建/查看/应用）
async function renderVersion() {
  const box = document.getElementById("tab_body");
  const [cps, brs] = await Promise.all([
    api(`/api/checkpoints?object_type=${CUR_TYPE}`),
    api(`/api/branches?object_type=${CUR_TYPE}`),
  ]);
  box.innerHTML = `<h3>检查点（Checkpoints）</h3>
    <div class="row"><input id="cp_label" placeholder="标签(如 Q1 基线)" style="flex:1;"/>
      <button onclick="createCheckpoint()">打点</button></div>
    <div id="cp_list"></div>
    <h3>分支（Branches）</h3>
    <div class="row"><input id="br_name" placeholder="分支名(字母数字下划线)" style="flex:1;"/>
      <select id="br_base"><option value="">基于当前数据</option>${cps.map(c=>`<option value="${c.id}">检查点 #${c.id} ${esc(c.label||"")}</option>`).join("")}</select>
      <button onclick="createBranch()">创建分支</button></div>
    <div id="br_list"></div>`;
  renderCpList(cps);
  renderBrList(brs);
}
async function renderCpList(cps) {
  const box = document.getElementById("cp_list");
  box.innerHTML = cps.length ? `<table><thead><tr><th>#</th><th>标签</th><th>时间</th><th></th></tr></thead><tbody>` +
    cps.map(c => `<tr><td>${c.id}</td><td>${esc(c.label||"")}</td><td class="muted">${esc(c.ts)}</td>
      <td><button class="ghost sm" onclick="cpDiff(${c.id})">差异</button>
          <button class="ghost sm" onclick="cpRestore(${c.id})">恢复</button>
          <button class="ghost sm" onclick="cpDelete(${c.id})">删除</button></td></tr>`).join("") + `</tbody></table>
      <div id="cp_diff"></div>`
    : `<p class="muted">暂无检查点。改动数据前先「打点」留基线。</p>`;
}
async function renderBrList(brs) {
  const box = document.getElementById("br_list");
  box.innerHTML = brs.length ? `<table><thead><tr><th>分支</th><th>基于</th><th>时间</th><th></th></tr></thead><tbody>` +
    brs.map(b => `<tr><td><code>${esc(b.name)}</code>${b.protected ? ' <span class="tag" style="color:var(--warn)">🛡 受保护</span>' : ""}</td><td class="muted">${b.base_ckpt ? `#${b.base_ckpt}` : "当前"}</td><td class="muted">${esc(b.ts)}</td>
      <td><button class="ghost sm" onclick="brView('${esc(b.table_name)}')">查看</button>
          <button class="ghost sm" onclick="brApply(${b.id})">应用</button>
          <button class="ghost sm" onclick="brProtect(${b.id}, ${b.protected ? "false" : "true"})">${b.protected ? "解除保护" : "保护"}</button>
          <button class="ghost sm" onclick="brDelete(${b.id})">删除</button></td></tr>`).join("") + `</tbody></table>
      <div id="br_view"></div>`
    : `<p class="muted">暂无分支。</p>`;
}
async function brProtect(bid, protect) {
  await api(`/api/branches/${bid}/protect`, { method:"POST", body: JSON.stringify({ protect }) });
  toast(protect ? "分支已保护（apply 需审批）" : "已解除保护"); await renderVersion();
}
async function createCheckpoint() {
  const label = document.getElementById("cp_label").value.trim();
  await api("/api/checkpoints", { method:"POST", body: JSON.stringify({ object_type: CUR_TYPE, label }) });
  toast("已打点"); await renderVersion();
}
async function cpDiff(cid) {
  const d = await api(`/api/checkpoints/${cid}/diff`);
  const box = document.getElementById("cp_diff");
  box.innerHTML = `<div class="panel sm"><b>检查点 #${cid} vs 当前：</b> ${d.rows_old} 行 → ${d.rows_new} 行（${d.rows_diff >= 0 ? "+" : ""}${d.rows_diff}）
    <table style="margin-top:6px;"><thead><tr><th>列</th><th>检查点非空</th><th>当前非空</th><th>变化</th></tr></thead><tbody>` +
    (d.columns || []).map(c => `<tr><td>${esc(c.column)}</td><td>${c.old_nonnull}</td><td>${c.new_nonnull}</td><td>${c.changed ? '<span class="tag" style="color:var(--warn)">变化</span>' : '<span class="tag ok">一致</span>'}</td></tr>`).join("") +
    `</tbody></table></div>`;
}
async function cpRestore(cid) {
  if (!confirm(`恢复检查点 #${cid}？当前数据将被覆盖。`)) return;
  const r = await api(`/api/checkpoints/${cid}/restore`, { method:"POST", body:"{}" });
  toast(`已恢复 ${r.restored}`); await renderVersion();
}
async function cpDelete(cid) {
  if (!confirm(`删除检查点 #${cid}？`)) return;
  await api(`/api/checkpoints/${cid}`, { method:"DELETE" }); await renderVersion();
}
async function createBranch() {
  const name = document.getElementById("br_name").value.trim();
  const base = document.getElementById("br_base").value;
  if (!name) { toast("分支名必填"); return; }
  await api("/api/branches", { method:"POST", body: JSON.stringify({ object_type: CUR_TYPE, name, base: base ? Number(base) : undefined }) });
  toast("分支已创建"); await renderVersion();
}
async function brView(table) {
  const r = await api("/api/sql", { method:"POST", body: JSON.stringify({ sql: `SELECT * FROM ${table} LIMIT 50` }) });
  const box = document.getElementById("br_view");
  if (!r.rows.length) { box.innerHTML = `<p class="muted">空</p>`; return; }
  const cols = Object.keys(r.rows[0]);
  box.innerHTML = `<p class="muted">${table} · ${r.count} 行</p><table><thead><tr>` + cols.map(c=>`<th>${esc(c)}</th>`).join("") +
    `</tr></thead><tbody>` + r.rows.map(row=>"<tr>"+cols.map(c=>`<td>${esc(row[c])}</td>`).join("")+"</tr>").join("") + `</tbody></table>`;
}
async function brApply(bid) {
  if (!confirm("用分支数据覆盖主表？")) return;
  await api(`/api/branches/${bid}/apply`, { method:"POST", body:"{}" });
  toast("分支已应用到主表"); await renderVersion();
}
async function brDelete(bid) {
  if (!confirm("删除分支？")) return;
  await api(`/api/branches/${bid}`, { method:"DELETE" }); await renderVersion();
}

async function renderData() {  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties);
  CUR_PK = ot.primary_key;
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
let BATCH_ACTS = [];
async function applyFilters() {
  const logic = document.getElementById("f_logic").value;
  const ot = await api(`/api/ontology/object-types/${CUR_TYPE}`);
  const props = JSON.parse(ot.properties);
  const conditions = [];
  document.querySelectorAll("#f_rows .f-row").forEach(r => {
    const field = r.querySelector(".f_field").value;
    const op = r.querySelector(".f_op").value;
    const val = r.querySelector(".f_val").value;
    if (op === "isNull" || val !== "") conditions.push({ field, op, value: val });
  });
  const where = conditions.length ? { op: logic, conditions } : { op: "and", conditions: [] };
  const offset = Math.max(0, CUR_OFFSET || 0);
  const [res, cnt] = await Promise.all([
    api(`/api/ontology/object-types/${CUR_TYPE}/query`, { method:"POST", body: JSON.stringify({ where, limit: PAGE_SIZE, offset }) }),
    api(`/api/ontology/object-types/${CUR_TYPE}/count`, { method:"POST", body: JSON.stringify({ where }) }),
  ]);
  const rows = res.rows;
  const total = cnt.total;
  const box = document.getElementById("q_out");
  if (!rows.length) { CUR_QUERY_ROWS = []; box.innerHTML = `<p class="muted">无结果</p>`; return; }
  CUR_QUERY_ROWS = rows;
  CUR_PK = ot.primary_key;
  const acts = (await api("/api/ontology/actions")).filter(a => a.object_type === CUR_TYPE && ["update","delete"].includes(a.operation));
  BATCH_ACTS = acts;
  const cols = Object.keys(rows[0]);
  const from = offset + 1, to = offset + rows.length;
  let h = `<div class="row" style="justify-content:space-between;">
      <div class="row" style="margin:0;">
        <label style="display:flex;gap:4px;align-items:center;"><input type="checkbox" onchange="toggleAll(this.checked)"/> 全选</label>
        <span id="sel_cnt" class="muted">已选 0</span>
        <select id="batch_act" onchange="renderBatchParams()"><option value="">批量动作…</option>
          ${acts.map(a=>`<option value="${a.id}">${esc(a.name)}</option>`).join("")}</select>
        <span id="batch_params"></span>
        <button onclick="runBatch()">执行</button>
      </div>
      <div class="row" style="margin:0;">
        <button class="ghost sm" onclick="exportCSV(CUR_QUERY_ROWS,'${esc(CUR_TYPE)}')">⬇ CSV</button>
        <button class="ghost sm" ${offset===0?"disabled":""} onclick="goPage(-1)">‹ 上一页</button>
        <span class="muted">${from}-${to} / ${total}</span>
        <button class="ghost sm" ${to>=total?"disabled":""} onclick="goPage(1)">下一页 ›</button>
      </div>
    </div>
    <table><thead><tr><th></th>` +
    cols.map(c=>`<th>${c}</th>`).join("") + `</tr></thead><tbody>`;
  rows.forEach(r => {
    const sid = String(r[CUR_PK]);
    h += `<tr style="cursor:pointer" onclick="openObjectDrawer('${CUR_TYPE}', ${JSON.stringify(r[CUR_PK])})">
      <td onclick="event.stopPropagation()"><input type="checkbox" ${SELECTED.has(sid)?"checked":""} onchange="toggleSel('${esc(sid)}', this.checked)"/></td>` +
      cols.map(c=>`<td>${esc(r[c])}</td>`).join("") + "</tr>";
  });
  h += `</tbody></table>`;
  box.innerHTML = h;
  updateSelCount();
}
function toggleSel(sid, on) { if (on) SELECTED.add(sid); else SELECTED.delete(sid); updateSelCount(); }
function toggleAll(on) {
  (CUR_QUERY_ROWS || []).forEach(r => { const sid = String(r[CUR_PK]); on ? SELECTED.add(sid) : SELECTED.delete(sid); });
  document.querySelectorAll("#q_out input[type=checkbox]").forEach(cb => cb.checked = on);
  updateSelCount();
}
function updateSelCount() { const el = document.getElementById("sel_cnt"); if (el) el.textContent = `已选 ${SELECTED.size}`; }
function goPage(delta) { CUR_OFFSET = Math.max(0, (CUR_OFFSET || 0) + delta * PAGE_SIZE); applyFilters(); }
async function renderBatchParams() {
  const act = BATCH_ACTS.find(a => a.id === document.getElementById("batch_act").value);
  const box = document.getElementById("batch_params");
  if (!act) { box.innerHTML = ""; return; }
  if (act.operation === "delete") { box.innerHTML = `<span class="muted">将删除选中的 ${SELECTED.size} 个对象</span>`; return; }
  const params = JSON.parse(act.parameters).filter(p => p.name !== "id");
  box.innerHTML = params.map(p => `<input id="bp_${esc(p.name)}" placeholder="${esc(p.title || p.name)}" style="width:120px;"/>`).join("");
}
async function runBatch() {
  const act = BATCH_ACTS.find(a => a.id === document.getElementById("batch_act").value);
  if (!act) { toast("请先选择批量动作"); return; }
  const ids = [...SELECTED];
  if (!ids.length) { toast("请先勾选对象"); return; }
  let ok = 0; const errs = [];
  for (const sid of ids) {
    const params = { id: sid };
    if (act.operation === "update") {
      JSON.parse(act.parameters).filter(p => p.name !== "id").forEach(p => {
        const v = document.getElementById(`bp_${p.name}`)?.value;
        if (v !== "") params[p.name] = v;
      });
    }
    try { await api(`/api/ontology/actions/${act.id}/execute`, { method:"POST", body: JSON.stringify({ params }) }); ok++; }
    catch(e) { errs.push(`${sid}: ${e.message}`); }
  }
  toast(`批量执行完成：成功 ${ok}${errs.length ? "，失败 " + errs.length : ""}`);
  SELECTED.clear();
  await applyFilters();
}
function sparkline(pts = []) {
  if (!pts.length) return "";
  const max = Math.max(...pts, 1);
  const w = 560, h = 70, step = w / Math.max(pts.length - 1, 1);
  const d = pts.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(1)},${(h - v * (h - 10) / max).toFixed(1)}`).join(" ");
  const labels = pts.map((v, i) => `<text x="${(i * step).toFixed(1)}" y="${h + 12}" fill="#6b7280" font-size="8" text-anchor="middle">${v}</text>`).join("");
  return `<svg viewBox="0 0 ${w} ${h + 16}" style="width:100%;height:96px;">
    <path d="${d}" fill="none" stroke="#4f8cff" stroke-width="6" opacity="0.12"/>
    <path d="${d}" fill="none" stroke="#4f8cff" stroke-width="2"/>${labels}</svg>`;
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
    <div class="row" style="justify-content:space-between;"><span class="muted">构建 Form / Dashboard / View / Workflow / Kanban 五类应用，或打开自动生成的 CRUD 应用。</span></div>
    <h3>推荐模板</h3>
    <div class="tpl-row">
      <div class="tpl"><div class="tpl-t">📊 Dashboard</div><div class="tpl-d">指标卡 + 分组聚合，无代码</div><button class="ghost sm" onclick="showAppBuild('dashboard')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">📝 Form</div><div class="tpl-d">动作表单，直连 Action</div><button class="ghost sm" onclick="showAppBuild('form')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">🔀 Workflow</div><div class="tpl-d">多步动作编排</div><button class="ghost sm" onclick="showAppBuild('workflow')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">🔎 View</div><div class="tpl-d">对象集只读视图</div><button class="ghost sm" onclick="showAppBuild('view')">＋ Create</button></div>
      <div class="tpl"><div class="tpl-t">📋 Kanban</div><div class="tpl-d">按状态分列的对象看板</div><button class="ghost sm" onclick="showAppBuild('kanban')">＋ Create</button></div>
    </div>
    <div id="app_build"></div>
    <h3>构建的应用</h3>
    <table><thead><tr><th>名称</th><th>类型</th><th>对象类型</th><th>更新时间</th><th></th></tr></thead><tbody>` +
    (apps.length ? apps.map(a => `<tr><td>${esc(a.name)}</td><td><span class="tag">${esc(a.type)}</span></td><td>${esc(a.object_type)}</td><td class="muted">${esc(a.updated)}</td>
      <td><button class="ghost sm" onclick="openAppView('${esc(a.id)}')">打开</button>
          <button class="ghost sm" onclick="openAppEdit('${esc(a.id)}')">编辑</button>
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
  } else if (type === "kanban") {
    html = `<div class="row"><label>分组列（状态字段）</label><select id="ab_gb">${props.map(p=>`<option value="${p.key}" ${p.key==="status"?"selected":""}>${esc(p.title)}</option>`).join("")}</select></div>
      <div class="row"><label>卡片字段（逗号分隔，首个为标题）</label><input id="ab_fields" placeholder="name,price,status" style="flex:1;" value="${esc(props[0]?.key||"id")}"/></div>`;
  } else if (type === "workflow") {
    html = `<div class="row"><label>动作步骤(JSON)</label><textarea id="ab_steps" style="flex:1;height:70px;" placeholder='[{"name":"步骤1","action_id":"...","params":{}}]'></textarea></div>`;
  } else {
    html = `<div class="row"><label>过滤器(JSON，可选)</label><textarea id="ab_where" style="flex:1;height:60px;" placeholder='{"op":"eq","field":"status","value":"active"}'></textarea></div>
      <div class="row"><label>筛选组件字段（可选）</label><select id="ab_ff"><option value="">— 无 —</option>${props.map(p=>`<option value="${p.key}">${esc(p.title)}</option>`).join("")}</select>
      <span class="muted" style="font-size:12px;">运行时按字段值下拉过滤（J2 自定义组件）</span></div>`;
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
  } else if (type === "kanban") {
    config = { group_by: document.getElementById("ab_gb").value,
               card_fields: document.getElementById("ab_fields").value.split(",").map(s=>s.trim()).filter(Boolean) };
  } else if (type === "workflow") {
    try { config = { steps: JSON.parse(document.getElementById("ab_steps").value || "[]") }; }
    catch(e){ alert("步骤 JSON 解析失败"); return; }
  } else {
    let w = null;
    const raw = document.getElementById("ab_where").value.trim();
    if (raw) { try { w = JSON.parse(raw); } catch(e){ alert("过滤器 JSON 解析失败"); return; } }
    config = { where: w, limit: 200, filter_field: document.getElementById("ab_ff").value || undefined };
  }
  await api("/api/apps", { method:"POST", body: JSON.stringify({ id, name, type, object_type: otid, config }) });
  await openApps();
}
async function deleteApp(id) {
  if (!confirm(`删除应用 ${id}？`)) return;
  await api(`/api/apps/${id}`, { method:"DELETE" });
  await openApps();
}
async function openAppEdit(id) {
  const a = await api(`/api/apps/${id}`);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>✏️ 编辑应用 ${esc(id)}</h2>
    <div class="row"><label>名称</label><input id="ae_name" value="${esc(a.name)}" style="flex:1;"/></div>
    <div class="row"><label>描述</label><input id="ae_desc" value="${esc(a.description||"")}" style="flex:1;"/></div>
    <div class="row"><label>配置 JSON</label><textarea id="ae_cfg" style="flex:1;height:110px;font-family:monospace;">${esc(JSON.stringify(a.config||{}, null, 2))}</textarea></div>
    <div class="row"><button class="primary" onclick="saveAppEdit('${esc(id)}')">保存（生成新版本）</button>
      <button class="ghost" onclick="openApps()">取消</button></div>
    <div id="ae_out" class="muted"></div></div>`;
}
async function saveAppEdit(id) {
  let cfg = {};
  try { cfg = JSON.parse(document.getElementById("ae_cfg").value || "{}"); }
  catch(e){ toast("配置 JSON 不合法"); return; }
  const r = await api(`/api/apps/${id}/save`, { method:"POST", body: JSON.stringify({
    name: document.getElementById("ae_name").value.trim() || id,
    description: document.getElementById("ae_desc").value.trim(), config: cfg }) });
  toast(`已保存 v${r.version && r.version.version}`);
  await openApps();
}
const APP_TYPE_HINT = {
  view: "只读视图：关键字搜索 + 字段下拉筛选，点击行可开对象详情",
  kanban: "看板：按状态分列展示对象，点卡片看对象详情",
  dashboard: "仪表盘：指标卡 + 分组聚合统计",
  form: "动作表单：填写参数并执行动作",
  workflow: "工作流：多步动作编排，一键运行",
};
async function openAppView(id, objId) {
  const url = API + `/api/apps/${id}/render` + (objId ? `?object_id=${encodeURIComponent(objId)}` : "");
  const html = await (await fetch(url, { headers: { Authorization: `Bearer ${TOKEN}` } })).text();
  let meta = { name: id, type: "", object_type: "" };
  try { meta = await api(`/api/apps/${id}`); } catch(e) {}
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel">
    <div class="row" style="justify-content:space-between;flex-wrap:wrap;">
      <div>
        <h2 style="margin:0;">📱 ${esc(meta.name || id)}</h2>
        <p class="muted" style="margin:4px 0 0;">
          <span class="tag">${esc(meta.type || "app")}</span> 对象类型 <b>${esc(meta.object_type || "—")}</b>
          ${objId ? `<span class="tag">定位对象 #${esc(objId)}</span>` : ""}
        </p>
        <p class="muted" style="margin:4px 0 0;font-size:12px;">${esc(APP_TYPE_HINT[meta.type] || "")}</p>
      </div>
      <div class="row">
        <button class="ghost" onclick="openAppEdit('${esc(id)}')">编辑</button>
        <button class="ghost" onclick="openAppVersions('${esc(id)}')">版本</button>
        <button onclick="openApps()">返回列表</button>
      </div>
    </div>
    <iframe id="appframe" style="width:100%;height:72vh;border:1px solid var(--line);border-radius:10px;margin-top:10px;background:#fff;"></iframe></div>`;
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

// ---------------- H1 Chatbot Studio（chatbot-studio 对齐） ----------------
const CB_TOOLS = ["query_object_set","list_object_types","execute_action","ts_query","sql_query"];
async function openChatbots() {
  const cbs = await api("/api/chatbots");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🤖 Chatbot Studio</h2>
    <p class="muted">创建自定义 AIP Chatbot：指令 + 工具集 + 参数变量（对齐 chatbot-studio）。</p>
    <details><summary>＋ 新建 Chatbot</summary>
      <div class="row"><input id="cb_id" placeholder="ID" style="width:140px;"/><input id="cb_name" placeholder="名称" style="flex:1;"/></div>
      <div class="row"><input id="cb_desc" placeholder="描述" style="flex:1;"/></div>
      <div class="row"><label>指令（可含 {参数} 占位）</label></div>
      <textarea id="cb_instr" style="width:100%;height:80px;" placeholder="你是采购助手。目标区域：{region}"></textarea>
      <div class="row"><label>工具集</label>${CB_TOOLS.map(t=>`<label style="font-size:12px;display:flex;align-items:center;gap:3px;"><input type="checkbox" class="cb_tool" value="${t}" ${t==="query_object_set"||t==="list_object_types"?"checked":""}/>${t}</label>`).join("")}</div>
      <div class="row"><label>参数变量 JSON（可选）</label><input id="cb_params" placeholder='[{"key":"region","label":"区域","type":"string"}]' style="flex:1;"/></div>
      <div class="row"><label>知识标签（RAG，可选）</label><input id="cb_kb" placeholder="如 采购,supplier（逗号分隔）" style="flex:1;"/></div>
      <div class="row"><button onclick="createChatbot()">创建</button></div>
    </details>
    <h3>已建 Chatbot（${cbs.length}）</h3><div id="cb_list"></div>
    <h3>运行会话</h3>
    <select id="cb_sel" onchange="loadCbParams()">${cbs.map(x=>`<option value="${x.id}">${esc(x.name)} (${x.id})</option>`).join("")}</select>
    <div id="cb_pbox" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:8px;"></div>
    <div class="row" style="margin-top:8px;"><input id="cb_msg" placeholder="输入消息…" style="flex:1;min-width:200px;" onkeydown="if(event.key==='Enter')runChatbot()"/>
    <button class="primary" onclick="runChatbot()">发送</button></div>
    <div id="cb_out" style="margin-top:10px;"></div></div>`;
  await renderCbList(cbs);
  loadCbParams();
}
async function loadCbParams() {
  const cid = document.getElementById("cb_sel").value;
  const box = document.getElementById("cb_pbox");
  if (!cid) { box.innerHTML = ""; return; }
  try {
    const cb = await api(`/api/chatbots/${cid}`);
    const params = JSON.parse(cb.params || "[]");
    box.innerHTML = params.length ? params.map(p =>
      `<label style="font-size:12px;color:var(--muted);">${esc(p.label || p.key)}${p.required?" *":""}</label>
       <input class="cb_param" data-key="${esc(p.key)}" placeholder="${esc(p.type || "string")}" style="width:130px;"/>`).join("")
      : "";
  } catch(e) { box.innerHTML = ""; }
}
async function renderCbList(cbs) {
  const box = document.getElementById("cb_list");
  box.innerHTML = cbs.length ? `<table><thead><tr><th>名称</th><th>工具集</th><th>参数</th><th></th></tr></thead><tbody>` +
    cbs.map(x => `<tr><td><b>${esc(x.name)}</b><div class="muted" style="font-size:12px;">${esc(x.description||"")}</div></td>
      <td class="muted">${(JSON.parse(x.tools||"[]")).join(", ")}</td>
      <td class="muted">${(JSON.parse(x.params||"[]")).map(p=>p.key).join(", ")||"—"}</td>
      <td><button class="ghost sm" onclick="deleteChatbot('${esc(x.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`
    : `<p class="muted">暂无 Chatbot。</p>`;
}
async function createChatbot() {
  const id = document.getElementById("cb_id").value.trim();
  if (!id) { ontic_toast("Chatbot ID 必填"); return; }
  const tools = [...document.querySelectorAll(".cb_tool:checked")].map(i => i.value);
  let params = [];
  const raw = document.getElementById("cb_params").value.trim();
  if (raw) { try { params = JSON.parse(raw); } catch(e) { ontic_toast("参数 JSON 不合法"); return; } }
  await api("/api/chatbots", { method:"POST", body: JSON.stringify({
    id, name: document.getElementById("cb_name").value.trim() || id,
    description: document.getElementById("cb_desc").value.trim(),
    instructions: document.getElementById("cb_instr").value,
    tools, params,
    knowledge: document.getElementById("cb_kb").value.split(",").map(s=>s.trim()).filter(Boolean) }) });
  ontic_toast(`已创建 Chatbot ${id}`);
  await openChatbots();
}
async function deleteChatbot(id) {
  if (!confirm(`删除 Chatbot ${id}？`)) return;
  await api(`/api/chatbots/${id}`, { method:"DELETE" });
  await openChatbots();
}
async function runChatbot() {
  const cid = document.getElementById("cb_sel").value;
  const msg = document.getElementById("cb_msg").value.trim();
  if (!cid || !msg) return;
  const params = {};
  document.querySelectorAll(".cb_param").forEach(i => { const v = i.value.trim(); if (v) params[i.dataset.key] = v; });
  const out = document.getElementById("cb_out");
  out.innerHTML = `<div class="act-row"><b>你:</b> ${esc(msg)}</div>`;
  try {
    const r = await api(`/api/chatbots/${cid}/chat`, { method:"POST", body: JSON.stringify({ message: msg, params }) });
    out.innerHTML += `<div class="act-row" style="color:var(--ok);"><b>${esc(r.chatbot)}:</b> ${esc(r.reply)}</div>`;
    await loadCbHistory(cid);
  } catch(e) {
    out.innerHTML += `<div class="act-row" style="color:var(--danger);">错误: ${esc(e.message)}</div>`;
    await loadCbHistory(cid);
  }
}
async function loadCbHistory(cid) {
  const box = document.getElementById("cb_out");
  try {
    const msgs = await api(`/api/chatbots/${cid}/messages`);
    if (msgs.length) {
      box.innerHTML = msgs.map(m =>
        `<div class="act-row" style="${m.role==="assistant"?"color:var(--ok);":""}"><b>${m.role==="assistant"?"Chatbot":"你"}:</b> ${esc(m.content)}<span class="muted act-ts">${esc((m.ts||"").slice(11,19))}</span></div>`).join("");
    }
  } catch(e) {}
}

// ---------------- AIP 分析师（A1 会话 Threads + A2 结果表格/图表） ----------------
let CUR_THREAD = null;
async function openAgent() {
  const c = document.getElementById("content");
  let llm = null;
  try { llm = await api("/api/aip/llm-status"); } catch(e){}
  c.innerHTML = `<div class="panel"><h2>💬 AIP Analyst</h2>
    <p class="muted">多轮会话 + 结果可视化。试试「列出对象类型」「查 customer 和 region」「product 状态为 active 的」</p>
    <div class="row">${llm ? (llm.available ? `<span class="tag ok">LLM 已接入：${esc(llm.model)}</span>` : `<span class="tag">规则模式（配置 ONTIC_LLM_API_KEY 启用 LLM）</span>`) : ""}
      <button class="ghost sm" onclick="saveAnalysis()">保存分析</button>
      <button class="ghost sm" onclick="listAnalyses()">已存分析</button></div>
    <div class="thread-layout">
      <div class="thread-list">
        <div class="row"><button class="ghost sm" onclick="newThread()">＋ 新会话</button></div>
        <div id="thread_list"></div>
      </div>
      <div class="thread-main">
        <div id="chatLog" style="background:#0c0e12;border:1px solid var(--line);border-radius:8px;padding:12px;min-height:220px;max-height:52vh;overflow:auto;"></div>
        <div class="row" style="margin-top:10px;">
          <input id="chatInput" placeholder="输入消息，回车发送" style="flex:1;" onkeydown="if(event.key==='Enter')sendChat()"/>
          <button class="primary" onclick="sendChat()">发送</button></div>
      </div>
    </div>
    <div id="analyses"></div></div>`;
  await loadThreads(true);
}
async function loadThreads(autoCreate) {
  let ts = await api("/api/aip/threads");
  if (!ts.length && autoCreate) {
    await api("/api/aip/threads", { method:"POST", body: JSON.stringify({ name: "新会话" }) });
    ts = await api("/api/aip/threads");
  }
  const box = document.getElementById("thread_list");
  box.innerHTML = ts.map(t => `<div class="titem ${t.id === CUR_THREAD ? "on" : ""}" onclick="selectThread(${t.id})">
      <div class="tname">${esc(t.name)}</div>
      <div class="tmuted">${t.messages} 条 · ${esc((t.updated||"").slice(11,16))}
        <span class="tops" onclick="event.stopPropagation();renameThread(${t.id})">✎</span>
        <span class="tops" style="color:var(--danger)" onclick="event.stopPropagation();delThread(${t.id})">✕</span></div>
    </div>`).join("") || `<p class="muted">无会话</p>`;
  if (!ts.find(t => t.id === CUR_THREAD) && ts.length) CUR_THREAD = ts[0].id;
  if (ts.length) await selectThread(CUR_THREAD);
}
async function selectThread(tid) {
  CUR_THREAD = tid;
  document.querySelectorAll(".titem").forEach(el => el.classList.toggle("on", String(el.getAttribute("onclick")).includes(String(tid))));
  const msgs = await api(`/api/aip/threads/${tid}/messages`);
  const log = document.getElementById("chatLog");
  log.innerHTML = msgs.map(m => m.role === "user"
    ? `<div style="margin:6px 0;"><b>你:</b> ${esc(m.content)}</div>`
    : `<div style="margin:6px 0;color:var(--ok)"><b>Agent:</b> ${esc(m.content)}</div>`).join("") || `<p class="muted">新会话，说点什么开始吧。</p>`;
  log.scrollTop = log.scrollHeight;
}
async function newThread() {
  await api("/api/aip/threads", { method:"POST", body: JSON.stringify({ name: "新会话" }) });
  const ts = await api("/api/aip/threads");
  CUR_THREAD = ts[0].id;
  await loadThreads(false);
}
async function renameThread(tid) {
  const name = prompt("会话名称：") || "新会话";
  await api(`/api/aip/threads/${tid}/rename`, { method:"POST", body: JSON.stringify({ name }) });
  await loadThreads(false);
}
async function delThread(tid) {
  if (!confirm("删除该会话？消息将一并删除。")) return;
  await api(`/api/aip/threads/${tid}`, { method:"DELETE" });
  CUR_THREAD = null;
  await loadThreads(true);
}
async function sendChat() {
  const inp = document.getElementById("chatInput");
  const msg = inp.value.trim();
  if (!msg || !CUR_THREAD) return;
  inp.value = "";
  const log = document.getElementById("chatLog");
  log.innerHTML += `<div style="margin:6px 0;"><b>你:</b> ${esc(msg)}</div>`;
  log.scrollTop = log.scrollHeight;
  try {
    const r = await api(`/api/aip/threads/${CUR_THREAD}/chat`, { method:"POST", body: JSON.stringify({ message: msg }) });
    log.innerHTML += `<div style="margin:6px 0;color:var(--ok)"><b>Agent:</b> ${esc(r.reply)}</div>`;
    if (r.tool) log.innerHTML += `<details class="svc-log"><summary>↳ 服务日志：工具 ${esc(r.tool)}</summary><pre>${esc(JSON.stringify(r.args||{}, null, 2))}</pre></details>`;
    renderChatResults(r.result, log);
    log.scrollTop = log.scrollHeight;
    await loadThreads(false);
  } catch(e) { log.innerHTML += `<div style="color:#ff6b6b">错误: ${esc(e.message)}</div>`; }
}
// A2：查询结果渲染为表格 + 自动柱状图（零依赖 SVG）
function renderChatResults(result, log) {
  const items = Array.isArray(result) ? result : (result && result.rows ? [{ args: {}, result }] : []);
  items.forEach(it => {
    const rows = it.result && it.result.rows;
    if (!rows || !rows.length) return;
    const typeId = (it.args && it.args.type_id) || "";
    const cols = Object.keys(rows[0]);
    const numCol = cols.find(c => typeof rows[0][c] === "number");
    let h = `<div style="margin-top:8px;"><table style="font-size:12px;"><thead><tr>` + cols.map(c=>`<th>${esc(c)}</th>`).join("") + `</tr></thead><tbody>`;
    rows.slice(0, 20).forEach(r => {
      const first = r[cols[0]];
      const vid = JSON.stringify(first);
      h += `<tr ${typeId ? `style="cursor:pointer" onclick="openObjectDrawer('${typeId}', ${vid})"` : ""}>` + cols.map(c=>`<td>${esc(r[c])}</td>`).join("") + `</tr>`;
    });
    h += `</tbody></table>`;
    if (numCol) h += `<button class="ghost sm" style="margin-top:6px;" onclick="chartResult(this,'${esc(JSON.stringify(rows.slice(0,20))).replace(/'/g,"&#39;")}','${esc(cols[0])}','${esc(numCol)}')">📊 图表</button>`;
    h += `</div>`;
    log.innerHTML += h;
  });
}
function chartResult(btn, rowsJson, labelCol, valCol) {
  const rows = JSON.parse(rowsJson.replace(/&quot;/g, '"'));
  const W = 640, H = 200, pad = 36;
  const vals = rows.map(r => Number(r[valCol]) || 0);
  const max = Math.max(...vals, 1);
  const bw = (W - pad - 10) / vals.length;
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;margin-top:6px;">`;
  vals.forEach((v, i) => {
    const x = pad + i * bw + 2, bh = (v / max) * (H - 40), y = H - 24 - bh;
    svg += `<rect x="${x}" y="${y}" width="${Math.max(bw - 4, 2)}" height="${bh}" fill="#4f8cff" rx="2"/>`;
    svg += `<text x="${x + bw/2}" y="${y - 4}" fill="#e6e9ef" font-size="10" text-anchor="middle">${v}</text>`;
    const lbl = String(rows[i][labelCol] ?? "");
    svg += `<text x="${x + bw/2}" y="${H - 10}" fill="#8b93a7" font-size="9" text-anchor="middle">${esc(lbl.length > 8 ? lbl.slice(0,8)+"…" : lbl)}</text>`;
  });
  svg += `</svg>`;
  btn.insertAdjacentHTML("afterend", svg);
  btn.remove();
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
      <option value="boolean" ${type==="boolean"?"selected":""}>boolean</option>
      <option value="date" ${type==="date"?"selected":""}>date</option>
      <option value="timestamp" ${type==="timestamp"?"selected":""}>timestamp</option>
      <option value="geohash" ${type==="geohash"?"selected":""}>geohash</option>
      <option value="attachment" ${type==="attachment"?"selected":""}>attachment</option></select>
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
let SQL_ROWS = [];
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
    <div id="conn_out"></div>
    <h3>🔐 连接配置（凭据加密存储 · J3）</h3>
    <details><summary>＋ 保存连接配置（密码/令牌加密落库）</summary>
      <div class="row"><input id="cfg_id" placeholder="配置ID" style="width:130px;"/>
        <select id="cfg_type">${sel}</select>
        <input id="cfg_otid" placeholder="对象类型ID" style="width:140px;"/></div>
      <div class="row"><input id="cfg_url" placeholder="URL / 主机" style="flex:1;"/><input id="cfg_secret" type="password" placeholder="密码 / 令牌（将加密存储）" style="flex:1;"/></div>
      <div class="row"><button onclick="saveConnConfig()">保存</button></div>
    </details>
    <div id="cfg_list"></div></div>`;
  renderConnForm();
  loadConnConfigs();
}
async function loadConnConfigs() {
  const box = document.getElementById("cfg_list");
  try {
    const cfgs = await api("/api/connectors/configs");
    box.innerHTML = cfgs.length ? `<table><thead><tr><th>配置</th><th>类型</th><th>对象类型</th><th>凭据</th><th></th></tr></thead><tbody>` +
      cfgs.map(x => `<tr><td><b>${esc(x.id)}</b></td><td>${esc(x.connector_type)}</td><td>${esc(x.object_type_id)}</td>
        <td class="muted">${esc(JSON.stringify(x.config))}</td>
        <td><button class="ghost sm" onclick="runConnConfig('${esc(x.id)}')">运行</button>
            <button class="ghost sm" onclick="deleteConnConfig('${esc(x.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`
      : `<p class="muted">暂无连接配置。</p>`;
  } catch(e) { box.innerHTML = `<p class="muted">加载失败</p>`; }
}
async function saveConnConfig() {
  const id = document.getElementById("cfg_id").value.trim();
  if (!id) { ontic_toast("配置ID必填"); return; }
  const cfg = {};
  const url = document.getElementById("cfg_url").value.trim();
  if (url) cfg.url = url;
  const sec = document.getElementById("cfg_secret").value;
  if (sec) cfg.password = sec;
  await api("/api/connectors/configs", { method:"POST", body: JSON.stringify({
    id, connector_type: document.getElementById("cfg_type").value,
    object_type_id: document.getElementById("cfg_otid").value.trim(), config: cfg }) });
  ontic_toast(`已保存连接配置 ${id}（凭据加密存储）`);
  await loadConnConfigs();
}
async function runConnConfig(id) {
  try {
    const r = await api(`/api/connectors/configs/${id}/run`, { method:"POST", body:"{}" });
    ontic_toast(`运行 ${id}：${r.object_type} ${r.rows} 行`);
  } catch(e) { ontic_toast(`运行失败: ${e.message}`); }
}
async function deleteConnConfig(id) {
  if (!confirm(`删除连接配置 ${id}？`)) return;
  await api(`/api/connectors/configs/${id}`, { method:"DELETE" });
  await loadConnConfigs();
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
  const [fns, pls, pyts] = await Promise.all([api("/api/functions"), api("/api/pipelines"), api("/api/transforms/python")]);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>⚙️ 管道构建器（Pipeline Builder）</h2>
    <p class="muted">编排多步转换（SQL 或 Python），每步可注册为 Ontology 对象类型。</p>
    <h3>函数库（pb-functions）</h3>
    <div class="row">${fns.map(f=>`<span class="tag" title="${esc(f.desc)}">${esc(f.signature)}</span>`).join("")}
      ${pyts.map(t=>`<span class="tag" style="border-color:var(--ok);" title="Python 转换">🐍 ${esc(t.name)}</span>`).join("")}</div>
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
      ${pipelineFlow(p)}<div id="step_sql_${esc(p.id)}"></div>
      <div class="row"><button onclick="runPipeline('${esc(p.id)}')">运行</button>
      <button class="ghost" onclick="loadPipelineHistory('${esc(p.id)}')">运行历史 / 快照</button>
      <button class="ghost" style="color:#d9534f;" onclick="deletePipeline('${esc(p.id)}')">删除</button></div>
      <div id="ph_${esc(p.id)}"></div></div>`).join("")
    : `<p class="muted">暂无管道。</p>`;
}
async function deletePipeline(pid) {
  if (!confirm(`删除管道 ${pid}？运行历史与快照一并删除。`)) return;
  await api(`/api/pipelines/${pid}`, { method:"DELETE" });
  toast(`已删除管道 ${pid}`);
  await openPipelines();
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
  // 数据流卡片：Source → Transform → Output（10096559 / 68855017），点击步骤查看 SQL
  let cards = "";
  p.steps.forEach((s,i) => {
    const kind = s.target ? "OUTPUT DATASET" : "TRANSFORM";
    cards += `<div class="flow-card ${s.target?'out':'tf'}" style="cursor:pointer;" title="点击查看 SQL" onclick="showStepSql('${esc(p.id)}',${i})">
      <div class="flow-kind">${kind}</div>
      <div class="flow-name">${esc(s.name||('step'+i))}</div>${s.target?`<div class="flow-sub">→ ${esc(s.target)}</div>`:""}</div>`;
    if (i < p.steps.length-1) cards += `<span class="flow-arrow">→</span>`;
  });
  return `<div class="flow">${cards}</div>`;
}
async function showStepSql(pid, idx) {
  const pls = await api("/api/pipelines");
  const p = pls.find(x => x.id === pid);
  const s = p?.steps?.[idx];
  if (!s) return;
  const box = document.getElementById(`step_sql_${pid}`);
  if (box) box.innerHTML = `<div class="panel sm"><div class="row" style="justify-content:space-between;">
      <b>步骤 ${idx+1}：${esc(s.name||"")}</b>
      <button class="ghost sm" onclick="this.closest('.panel').remove()">✕</button></div>
    <pre style="margin:0;">${esc(s.sql)}</pre>
    ${s.target ? `<p class="muted">产出对象类型：${esc(s.target)}</p>` : ""}</div>`;
}
function addStepRow() {
  const wrap = document.getElementById("pl_steps");
  const row = document.createElement("div"); row.className = "row"; row.style.flexDirection="column"; row.style.alignItems="stretch";
  row.innerHTML = `<div class="row"><input class="s_name" placeholder="步骤名" style="width:150px;"/>
    <select class="s_kind" onchange="toggleStepKind(this)">
      <option value="sql">SQL</option><option value="python">Python</option></select>
    <select class="s_py" style="display:none;width:170px;"><option value="">选择 Python 转换…</option></select>
    <input class="s_input" placeholder="输入表(如 product)" style="display:none;width:140px;"/>
    <input class="s_target" placeholder="产出对象类型ID(可选)" style="flex:1;"/>
    <button class="ghost" onclick="this.parentNode.remove()">✕ 移除</button></div>
    <textarea class="s_sql" placeholder="SELECT ... 可用 ont_* 函数" style="width:100%;height:48px;"></textarea>`;
  const pySel = row.querySelector(".s_py");
  PY_TRANSFORMS.forEach(t => { const o = document.createElement("option"); o.value = t.name; o.textContent = t.name; pySel.appendChild(o); });
  wrap.appendChild(row);
}
function toggleStepKind(sel) {
  const row = sel.closest(".row");
  const isPy = sel.value === "python";
  row.querySelector(".s_sql").style.display = isPy ? "none" : "";
  row.querySelector(".s_py").style.display = isPy ? "" : "none";
  row.querySelector(".s_input").style.display = isPy ? "" : "none";
}
async function createPipeline() {
  const id = document.getElementById("pl_id").value.trim();
  const name = document.getElementById("pl_name").value.trim();
  const steps = [];
  document.querySelectorAll("#pl_steps .row").forEach(r => {
    const kind = r.querySelector(".s_kind").value;
    const target = r.querySelector(".s_target").value.trim();
    if (kind === "python") {
      const py = r.querySelector(".s_py").value;
      const input = r.querySelector(".s_input").value.trim();
      if (!py) return;
      steps.push({ name: r.querySelector(".s_name").value.trim() || py, python: py, input: input || "product", target });
    } else {
      const sql = r.querySelector(".s_sql").value.trim(); if (!sql) return;
      steps.push({ name: r.querySelector(".s_name").value.trim(), sql, target });
    }
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
      <div class="row"><input id="nu_name" placeholder="用户名"/><input id="nu_pw" type="password" placeholder="密码(≥8位含字母数字)"/>
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
    users.map(u=>`<tr><td>${esc(u.username)}</td><td>
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
  if (!confirm(`将 ${username} 的角色改为 ${role}？`)) { await adminRefresh(); return; }
  await api(`/api/admin/users/${username}/role`, { method:"POST", body: JSON.stringify({ role }) });
  toast(`已更新 ${username} 角色为 ${role}`);
  await adminRefresh();
}
async function adminGrant() {
  const username = document.getElementById("g_user").value.trim();
  const object_type = document.getElementById("g_type").value.trim();
  const level = document.getElementById("g_level").value;
  if (!username || !object_type) { alert("用户名和对象类型必填"); return; }
  if (!confirm(`授权 ${username} 对 ${object_type} 的 ${level} 权限？`)) return;
  await api("/api/admin/grants", { method:"POST", body: JSON.stringify({ username, object_type, level }) });
  await adminRefresh();
}
async function adminRevoke(username, object_type) {
  if (!confirm(`撤销 ${username} 对 ${object_type} 的授权？`)) return;
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
let CUR_APPROVAL = null;
async function renderApprovals() {
  const appr = await api("/api/security/approvals?status=pending");
  const box = document.getElementById("appr_out");
  if (!appr.length) { box.innerHTML = `<p class="muted">无待审批请求。</p>`; return; }
  if (!CUR_APPROVAL || !appr.find(a => a.id === CUR_APPROVAL)) CUR_APPROVAL = appr[0].id;
  const cur = appr.find(a => a.id === CUR_APPROVAL);
  box.innerHTML = `<div class="inbox">
    <div class="inbox-list">` + appr.map(a =>
      `<div class="inbox-item ${a.id === CUR_APPROVAL ? "on" : ""}" onclick="CUR_APPROVAL=${a.id};renderApprovals()">
        <b>${esc(a.action_id)}</b><br/><span class="muted">${esc(a.requester)} · ${esc(a.ts)}</span></div>`).join("") + `</div>
    <div class="inbox-detail"><div class="panel sm">
      <h4>${esc(cur.action_id)}</h4>
      <table><tbody>
        <tr><td>请求人</td><td>${esc(cur.requester)}</td></tr>
        <tr><td>对象类型</td><td>${esc(cur.object_type)}</td></tr>
        <tr><td>参数</td><td><pre style="margin:0;max-height:160px;">${esc(JSON.stringify(cur.params, null, 2))}</pre></td></tr>
        <tr><td>备注</td><td>${esc(cur.note || "—")}</td></tr>
        <tr><td>提交时间</td><td class="muted">${esc(cur.ts)}</td></tr>
      </tbody></table>
      <div class="row" style="margin-top:10px;">
        <button class="ghost sm" style="color:var(--ok);border-color:var(--ok);" onclick="decideApproval(${cur.id},true)">✔ 批准</button>
        <button class="ghost sm" style="color:var(--danger);" onclick="decideApproval(${cur.id},false)">✖ 拒绝</button>
      </div></div></div></div>`;
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

// ---------------- M10 血缘图（类型级/表级切换）+ 运维监控 ----------------
let LINEAGE_MODE = "type";
async function openLineage() {
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🧬 数据血缘（Lineage）</h2>
    <div class="row"><button class="ghost sm ${LINEAGE_MODE==="type"?"ok":""}" onclick="LINEAGE_MODE='type';renderLineage()">类型级</button>
      <button class="ghost sm ${LINEAGE_MODE==="table"?"ok":""}" onclick="LINEAGE_MODE='table';renderLineage()">表级</button>
      <span class="muted">管道 SQL FROM + 链接类型推导</span></div>
    <div id="lineage_svg"></div></div>`;
  await renderLineage();
}
async function renderLineage() {
  const g = LINEAGE_MODE === "table" ? await api("/api/lineage/tables") : await api("/api/lineage");
  const nodes = g.nodes || [];
  let edges = g.edges || [];
  if (LINEAGE_MODE === "table") {
    const ids = new Set();
    edges.forEach(e => { ids.add(e.source); ids.add(e.target); });
    renderLineageSVG([...ids].map(id => ({ id, name: id })), edges, "");
    return;
  }
  renderLineageSVG(nodes, edges, "type");
}
function renderLineageSVG(nodes, edges, clickMode) {
  const box = document.getElementById("lineage_svg");
  if (!nodes.length) { box.innerHTML = `<p class="muted">暂无血缘数据（先建管道或链接）。</p>`; return; }
  const names = Object.fromEntries(nodes.map(n => [n.id, n.name || n.id]));
  const layer = {}; nodes.forEach(n => layer[n.id] = 0);
  let changed = true;
  while (changed) {
    changed = false;
    edges.forEach(e => { if (layer[e.target] <= layer[e.source]) { layer[e.target] = layer[e.source] + 1; changed = true; } });
  }
  const maxLayer = Math.max(...nodes.map(n => layer[n.id]), 1);
  const cols = Array.from({ length: maxLayer + 1 }, () => []);
  nodes.forEach(n => cols[layer[n.id]].push(n.id));
  const cellW = 150, cellH = 64, padX = 30, padY = 24;
  const W = Math.max(680, (maxLayer + 1) * cellW + padX * 2);
  const H = Math.max(300, Math.max(...cols.map(c => c.length)) * cellH + padY * 2);
  const pos = {};
  cols.forEach((col, li) => col.forEach((nid, ri) => {
    pos[nid] = { x: padX + li * cellW + cellW / 2, y: padY + ri * cellH + cellH / 2 - (cols[li].length - 1) * cellH / 2 };
  }));
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;">`;
  edges.forEach(e => {
    const s = pos[e.source], t = pos[e.target];
    if (s && t) svg += `<line x1="${s.x}" y1="${s.y}" x2="${t.x}" y2="${t.y}" stroke="#4f8cff" stroke-width="1.5" opacity="0.6" title="${esc(e.via || "")}"/>`;
  });
  nodes.forEach(n => {
    const p = pos[n.id];
    const label = names[n.id] || n.id;
    const go = clickMode === "type" ? `openType('${n.id}')` : "";
    svg += `<g style="cursor:${go ? "pointer" : "default"}" onclick="${go}">
      <rect x="${p.x-62}" y="${p.y-16}" width="124" height="32" rx="8" fill="#171a21" stroke="#3ecf8e"/>
      <text x="${p.x}" y="${p.y+4}" fill="#e6e9ef" font-size="10" text-anchor="middle">${esc(label.length > 14 ? label.slice(0,14)+"…" : label)}</text></g>`;
  });
  svg += `</svg><p class="muted">节点 ${nodes.length} · 边 ${edges.length}</p>`;
  box.innerHTML = svg;
}
async function openOps() {
  const [monitors, acts, allActs] = await Promise.all([
    api("/api/monitors"), api("/api/activity"), api("/api/ontology/actions"),
  ]);
  window.MON_ACTS = allActs; // 供监控向导选择"命中动作"
  const types = await api("/api/ontology/object-types");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📈 运维监控</h2>
    <h3>深度健康检查</h3>
    <div class="row"><button onclick="runHealthCheck()">🩺 检查</button><span id="health_summary" class="muted"></span></div>
    <div id="health_out"></div>
    <h3>监控规则（命中可自动执行动作 ⚡）</h3>
    <div id="mon_wizard"></div>
    <div id="mon_list"></div>
    <div class="row"><button onclick="checkAllMonitors()">▶ 运行全部检查</button></div>
    <h3>自动化事件（autopilot automation-events）</h3>
    <div id="auto_events" style="max-height:220px;overflow:auto;"></div>
    <h3>平台事件时间线（23315552）</h3>
    <div id="ops_tl" style="max-height:300px;overflow:auto;"></div></div>`;
  initWizard(types);
  await renderMonitors();
  await loadAutoEvents();
  const tl = document.getElementById("ops_tl");
  tl.innerHTML = acts.slice(0, 20).map(a =>
    `<div class="act-row"><span class="tag">${esc(a.kind)}</span><span>${esc(a.message)}</span><span class="muted act-ts">${esc((a.ts||"").slice(0,16).replace("T"," "))}</span></div>`).join("");
}
async function loadAutoEvents() {
  const box = document.getElementById("auto_events");
  try {
    const evs = await api("/api/automation/events");
    box.innerHTML = evs.length ? `<table><thead><tr><th>规则</th><th>结果</th><th>详情</th><th>时间</th></tr></thead><tbody>` +
      evs.map(e => `<tr><td>${esc(e.rule)}</td>
        <td>${e.outcome==="ok"?'<span class="tag ok">正常</span>':e.outcome==="executed"?'<span class="tag" style="color:var(--ok)">已执行</span>':e.outcome==="failed"?'<span class="tag" style="color:var(--danger)">失败</span>':'<span class="tag" style="color:var(--warn)">告警</span>'}</td>
        <td class="muted">${esc(e.detail||"")}</td><td class="muted">${esc((e.ts||"").slice(11,19))}</td></tr>`).join("") + `</tbody></table>`
      : `<p class="muted">暂无自动化事件（运行监控检查后产生）。</p>`;
  } catch(e) { box.innerHTML = `<p class="muted">加载失败</p>`; }
}
// 监控创建向导（34752748：Select scope → Configure → Review）
let MON_STEP = 1, MON_TYPES = [];
async function runHealthCheck() {
  const r = await api("/api/health/deep");
  document.getElementById("health_summary").textContent = `总体：${r.status} @ ${r.ts}`;
  document.getElementById("health_out").innerHTML = `<table><thead><tr><th>检查项</th><th>状态</th><th>详情</th></tr></thead><tbody>` +
    r.checks.map(c => `<tr><td>${esc(c.name)}</td>
      <td>${c.status === "ok" ? '<span class="tag ok">ok</span>' : c.status === "warn" ? '<span class="tag" style="color:var(--warn)">warn</span>' : '<span class="tag" style="color:var(--danger)">error</span>'}</td>
      <td class="muted">${esc(c.detail)}</td></tr>`).join("") + `</tbody></table>`;
}
function initWizard(types) { MON_TYPES = types; MON_STEP = 1; renderWizard(); }
function renderWizard() {
  const box = document.getElementById("mon_wizard");
  if (!box) return;
  const stepTags = ["1 选择对象", "2 指标阈值", "3 确认"];
  let html = `<div class="row"><b>创建监控规则：</b>` + stepTags.map((s, i) =>
    `<span class="tag ${i + 1 === MON_STEP ? "ok" : ""}">${s}</span>`).join(" ") + `</div>`;
  if (MON_STEP === 1) {
    html += `<div class="row"><input id="mo_id2" placeholder="规则ID" style="width:150px;"/>
      <input id="mo_name2" placeholder="规则名" style="flex:1;"/>
      <select id="mo_type">${MON_TYPES.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
      <button onclick="MON_STEP=2;renderWizard()">下一步 →</button></div>`;
  } else if (MON_STEP === 2) {
    html += `<div class="row"><select id="mo_metric"><option value="count">count</option><option value="sum:amount">sum:字段</option></select>
      <select id="mo_op"><option value="gt">&gt;</option><option value="lt">&lt;</option><option value="gte">≥</option><option value="lte">≤</option></select>
      <input id="mo_thr" type="number" placeholder="阈值" value="100" style="width:110px;"/>
      <button class="ghost" onclick="MON_STEP=1;renderWizard()">← 上一步</button>
      <button onclick="MON_STEP=3;renderWizard()">下一步 →</button></div>
      <div class="row" style="margin-top:8px;"><select id="mo_action"><option value="">⚡ 命中自动执行动作（可选）</option>${
        (window.MON_ACTS||[]).map(a=>`<option value="${a.id}">${esc(a.name)} (${a.operation})</option>`).join("")}</select>
      <input id="mo_params" placeholder='动作参数 JSON，如 {"name":"x","code":"ABC"}' style="flex:1;"/></div>`;
  } else {
    const id = document.getElementById("mo_id2").value.trim() || "(未命名)";
    const name = document.getElementById("mo_name2").value.trim() || id;
    const type = document.getElementById("mo_type").value;
    const metric = document.getElementById("mo_metric").value;
    const op = document.getElementById("mo_op").value;
    const thr = document.getElementById("mo_thr").value;
    html += `<div class="panel sm"><p class="muted">将创建：</p>
      <p><b>${esc(name)}</b> — 当 <code>${esc(metric)}</code> 对 ${esc(type)} ${esc(op)} ${esc(thr)} 时告警</p>
      <div class="row"><button class="ghost" onclick="MON_STEP=2;renderWizard()">← 上一步</button>
      <button onclick="finishWizard('${esc(id)}','${esc(name)}','${esc(type)}','${esc(metric)}','${esc(op)}',${esc(thr)||0})">✓ 创建规则</button></div></div>`;
  }
  box.innerHTML = html;
}
async function finishWizard(id, name, object_type, metric, op, threshold) {
  const action_id = document.getElementById("mo_action").value || null;
  let action_params = {};
  const paramsRaw = (document.getElementById("mo_params").value || "").trim();
  if (paramsRaw) {
    try { action_params = JSON.parse(paramsRaw); }
    catch (e) { ontic_toast("动作参数 JSON 不合法"); return; }
  }
  await api("/api/monitors", { method:"POST", body: JSON.stringify({ id, name, object_type, metric, op, threshold, action_id, action_params }) });
  ontic_toast(`已创建监控规则 ${name}`);
  await renderMonitors();
  initWizard(MON_TYPES);
}
async function renderMonitors() {
  const monitors = await api("/api/monitors");
  const box = document.getElementById("mon_list");
  if (!monitors.length) { box.innerHTML = `<p class="muted">暂无监控规则。</p>`; return; }
  box.innerHTML = `<table><thead><tr><th>规则</th><th>对象类型</th><th>指标</th><th>阈值</th><th>命中动作</th><th>状态</th><th></th></tr></thead><tbody>` +
    monitors.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.object_type)}</td><td>${esc(m.metric)}</td><td>${esc(m.op)} ${m.threshold}</td>
      <td>${m.action_id ? `<span class="tag" style="color:var(--ok)">⚡ ${esc(m.action_id)}</span>` : '<span class="muted">—</span>'}</td>
      <td>${m.enabled?'<span class="tag ok">启用</span>':'<span class="tag">停用</span>'}</td>
      <td><button class="ghost sm" onclick="checkMonitor('${esc(m.id)}')">检查</button>
          <button class="ghost sm" onclick="deleteMonitor('${esc(m.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`;
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

// ---------------- Compass 资源管理器（全资产树） ----------------
let COMPASS = null;
let COMPASS_CAT = "types";
// ---------------- H4 知识库（RAG 检索上下文） ----------------
async function openKnowledge() {
  const items = await api("/api/knowledge");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📚 知识库（RAG 检索上下文）</h2>
    <p class="muted">知识条目供 Chatbot 按标签检索增强回答（对齐 chatbot-studio retrieval-context）。</p>
    <details><summary>＋ 添加知识条目</summary>
      <div class="row"><input id="kb_id" placeholder="条目ID" style="width:130px;"/><input id="kb_tags" placeholder="标签（逗号分隔，如 采购,supplier）" style="flex:1;"/></div>
      <textarea id="kb_content" placeholder="知识内容…" style="width:100%;height:70px;"></textarea>
      <div class="row"><button onclick="addKnowledge()">添加</button></div>
    </details>
    <h3>知识条目（${items.length}）</h3><div id="kb_list"></div></div>`;
  renderKbList(items);
}
function renderKbList(items) {
  const box = document.getElementById("kb_list");
  box.innerHTML = items.length ? `<table><thead><tr><th>ID</th><th>内容</th><th>标签</th><th></th></tr></thead><tbody>` +
    items.map(k => `<tr><td><b>${esc(k.id)}</b></td><td class="muted">${esc(k.content)}</td>
      <td class="muted">${JSON.parse(k.tags||"[]").map(t=>`<span class="tag">${esc(t)}</span>`).join(" ")}</td>
      <td><button class="ghost sm" onclick="deleteKnowledge('${esc(k.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`
    : `<p class="muted">暂无知识条目。</p>`;
}
async function addKnowledge() {
  const id = document.getElementById("kb_id").value.trim();
  const content = document.getElementById("kb_content").value.trim();
  if (!id || !content) { ontic_toast("条目ID与内容必填"); return; }
  await api("/api/knowledge", { method:"POST", body: JSON.stringify({
    id, content,
    tags: document.getElementById("kb_tags").value.split(",").map(s=>s.trim()).filter(Boolean) }) });
  ontic_toast(`已添加知识 ${id}`);
  await openKnowledge();
}
async function deleteKnowledge(id) {
  if (!confirm(`删除知识条目 ${id}？`)) return;
  await api(`/api/knowledge/${id}`, { method:"DELETE" });
  await openKnowledge();
}

// ---------------- I1 Contour 分析（contour 分区对齐） ----------------
async function openContour() {
  const [types, ans] = await Promise.all([api("/api/ontology/object-types"), api("/api/analyses")]);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📐 Contour 分析画布</h2>
    <p class="muted">节点式分析：数据源 → 过滤 → 聚合 → 输出，可保存结果为对象类型（对齐 contour）。</p>
    <details><summary>＋ 新建分析</summary>
      <div class="row"><input id="an_id" placeholder="分析ID" style="width:140px;"/><input id="an_name" placeholder="名称" style="flex:1;"/>
        <select id="an_src"><option value="">— 数据源对象类型 —</option>${types.map(t=>`<option value="${t.id}">${esc(t.name)} (${t.id})</option>`).join("")}</select></div>
      <div class="row"><label>过滤 JSON（可选）</label><input id="an_filter" placeholder='{"op":"ne","field":"status","value":"cancelled"}' style="flex:1;"/></div>
      <div class="row"><label>分组字段</label><input id="an_gb" placeholder="如 status" style="width:140px;"/>
        <label>聚合 JSON</label><input id="an_aggs" placeholder='{"amount":"sum","qty":"sum"}' style="flex:1;"/></div>
      <div class="row"><label>LIMIT</label><input id="an_limit" type="number" value="10" style="width:90px;"/>
        <button onclick="createAnalysis()">创建分析</button></div>
    </details>
    <h3>分析列表（${ans.length}）</h3><div id="an_list"></div>
    <h3>运行结果</h3><div id="an_out"></div></div>`;
  renderAnList(ans);
}
function renderAnList(ans) {
  const box = document.getElementById("an_list");
  box.innerHTML = ans.length ? `<table><thead><tr><th>分析</th><th>步骤</th><th></th></tr></thead><tbody>` +
    ans.map(a => `<tr><td><b>${esc(a.name)}</b><div class="muted" style="font-size:12px;">${esc(a.description||"")}</div></td>
      <td class="muted">${JSON.parse(a.steps||"[]").map(s=>s.type).join(" → ")}</td>
      <td><button class="ghost sm" onclick="runAnalysis('${esc(a.id)}')">运行</button>
          <button class="ghost sm" onclick="saveAnalysisAsType('${esc(a.id)}')">存为新类型</button>
          <button class="ghost sm" onclick="deleteAnalysis('${esc(a.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`
    : `<p class="muted">暂无分析。</p>`;
}
async function createAnalysis() {
  const id = document.getElementById("an_id").value.trim();
  const src = document.getElementById("an_src").value;
  if (!id || !src) { ontic_toast("分析ID与数据源必填"); return; }
  const steps = [{ type: "source", table: src }];
  const fRaw = document.getElementById("an_filter").value.trim();
  if (fRaw) { try { steps.push({ type: "filter", where: JSON.parse(fRaw) }); } catch(e){ ontic_toast("过滤 JSON 不合法"); return; } }
  const gb = document.getElementById("an_gb").value.trim();
  if (gb) {
    let aggs = {};
    const aRaw = document.getElementById("an_aggs").value.trim();
    if (aRaw) { try { aggs = JSON.parse(aRaw); } catch(e){ ontic_toast("聚合 JSON 不合法"); return; } }
    steps.push({ type: "aggregate", group_by: gb, aggs });
  }
  steps.push({ type: "limit", n: parseInt(document.getElementById("an_limit").value) || 10 });
  await api("/api/analyses", { method:"POST", body: JSON.stringify({ id, name: document.getElementById("an_name").value.trim() || id, steps }) });
  ontic_toast(`已创建分析 ${id}`);
  await openContour();
}
async function runAnalysis(id) {
  const box = document.getElementById("an_out");
  let params = {};
  try {
    const a = await api(`/api/analyses/${id}`);
    const steps = JSON.parse(a.steps || "[]");
    // 检测 {param} 占位 → 提示输入
    const placeholders = new Set();
    steps.forEach(s => { if (s.where && s.where.value && /^\{.+}$/.test(String(s.where.value))) placeholders.add(String(s.where.value).slice(1,-1)); });
    if (placeholders.size) {
      const raw = prompt(`该分析含参数：${[...placeholders].join(", ")}\n输入参数（JSON 或 key=value）`);
      if (raw == null) return;
      if (raw.includes("=") && !raw.trim().startsWith("{")) {
        raw.split(/[,\s]+/).filter(Boolean).forEach(kv => { const [k,v] = kv.split("="); if (k&&v) params[k.trim()] = v.trim(); });
      } else if (raw.trim()) { try { params = JSON.parse(raw); } catch(e){ ontic_toast("参数格式不合法"); return; } }
    }
    const r = await api(`/api/analyses/${id}/run`, { method:"POST", body: JSON.stringify({ params }) });
    if (!r.rows.length) { box.innerHTML = `<p class="muted">无结果</p>`; return; }
    box.innerHTML = `<p class="muted">${r.count} 行 · ${r.columns.join(", ")}</p><table><thead><tr>` +
      r.columns.map(x=>`<th>${esc(x)}</th>`).join("") + `</tr></thead><tbody>` +
      r.rows.map(row=>"<tr>"+r.columns.map(x=>`<td>${esc(row[x])}</td>`).join("")+"</tr>").join("") + `</tbody></table>`;
  } catch(e) { box.innerHTML = `<pre style="color:var(--danger)">${esc(e.message)}</pre>`; }
}
async function saveAnalysisAsType(id) {
  const newId = prompt("新对象类型 ID（如 po_agg）");
  if (!newId) return;
  try {
    const r = await api(`/api/analyses/${id}/save-as-type`, { method:"POST", body: JSON.stringify({ new_type_id: newId }) });
    ontic_toast(`已保存为对象类型 ${r.object_type}（${r.rows} 行）`);
  } catch(e) { ontic_toast(`保存失败: ${e.message}`); }
}
async function deleteAnalysis(id) {
  if (!confirm(`删除分析 ${id}？`)) return;
  await api(`/api/analyses/${id}`, { method:"DELETE" });
  await openContour();
}

// ---------------- J1 数据生命周期（data-lifetime 对齐） ----------------
async function openLifetime() {
  const [types, pols] = await Promise.all([api("/api/ontology/object-types"), api("/api/lifetime/policies")]);
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>⏳ 数据生命周期（TTL）</h2>
    <p class="muted">为对象类型设置保留天数（按 date/timestamp 字段），应用策略删除过期数据（对齐 data-lifetime）。</p>
    <details><summary>＋ 新建策略</summary>
      <div class="row"><input id="ttl_id" placeholder="策略ID" style="width:140px;"/>
        <select id="ttl_type"><option value="">— 对象类型 —</option>${types.map(t=>`<option value="${t.id}">${esc(t.name)}</option>`).join("")}</select>
        <input id="ttl_col" placeholder="时间字段(如 order_date)" style="flex:1;"/>
        <input id="ttl_days" type="number" placeholder="保留天数" value="90" style="width:100px;"/>
        <button onclick="createTtlPolicy()">创建</button></div>
    </details>
    <div class="row"><button onclick="applyAllTtl()">▶ 应用全部策略</button></div>
    <h3>策略列表（${pols.length}）</h3><div id="ttl_list"></div></div>`;
  renderTtlList(pols);
}
function renderTtlList(pols) {
  const box = document.getElementById("ttl_list");
  box.innerHTML = pols.length ? `<table><thead><tr><th>策略</th><th>对象类型</th><th>时间字段</th><th>保留天数</th><th>状态</th><th></th></tr></thead><tbody>` +
    pols.map(p => `<tr><td><b>${esc(p.id)}</b></td><td>${esc(p.object_type)}</td><td>${esc(p.time_column)}</td><td>${p.keep_days} 天</td>
      <td>${p.enabled?'<span class="tag ok">启用</span>':'<span class="tag">停用</span>'}</td>
      <td><button class="ghost sm" onclick="deleteTtlPolicy('${esc(p.id)}')">删除</button></td></tr>`).join("") + `</tbody></table>`
    : `<p class="muted">暂无策略。</p>`;
}
async function createTtlPolicy() {
  const id = document.getElementById("ttl_id").value.trim();
  const otid = document.getElementById("ttl_type").value;
  if (!id || !otid) { ontic_toast("策略ID与对象类型必填"); return; }
  try {
    await api("/api/lifetime/policies", { method:"POST", body: JSON.stringify({
      id, object_type: otid,
      time_column: document.getElementById("ttl_col").value.trim(),
      keep_days: parseInt(document.getElementById("ttl_days").value) || 90 }) });
    ontic_toast(`已创建策略 ${id}`);
    await openLifetime();
  } catch(e) { ontic_toast(e.message); }
}
async function applyAllTtl() {
  try {
    const r = await api("/api/lifetime/apply-all", { method:"POST", body:"{}" });
    ontic_toast(r.map(x=>`${x.policy}: 剩 ${x.remaining} 行`).join("，") || "无启用策略");
    await openLifetime();
  } catch(e) { ontic_toast(`应用失败: ${e.message}`); }
}
async function deleteTtlPolicy(id) {
  if (!confirm(`删除策略 ${id}？`)) return;
  await api(`/api/lifetime/policies/${id}`, { method:"DELETE" });
  await openLifetime();
}

async function openCompass() {
  if (!COMPASS) {
    const [stats, pls, apps, models, eps, mons, media] = await Promise.all([
      api("/api/ontology/stats"), api("/api/pipelines"), api("/api/apps"),
      api("/api/models"), api("/api/endpoints"), api("/api/monitors"), api("/api/media"),
    ]);
    COMPASS = { stats, pls, apps, models, eps, mons, media };
  }
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>🗂️ 资源管理器（Compass）</h2>
    <div class="compass">
      <div class="compass-tree" id="compass_tree"></div>
      <div class="compass-detail" id="compass_detail"></div>
    </div></div>`;
  renderCompassTree();
  compassShow("types");
}
function renderCompassTree() {
  const cats = [
    ["types", "🧩 对象类型", COMPASS.stats.length],
    ["pipes", "⚙️ 管道", COMPASS.pls.length],
    ["apps", "📱 应用", COMPASS.apps.length],
    ["models", "🧠 模型", COMPASS.models.length],
    ["eps", "🔌 自定义端点", COMPASS.eps.length],
    ["mons", "📈 监控", COMPASS.mons.length],
    ["media", "🖼️ 媒体", COMPASS.media.length],
  ];
  document.getElementById("compass_tree").innerHTML = `<div class="cnode ${COMPASS_CAT==="types"?"on":""}" onclick="compassShow('types')">📦 全部资源</div>` +
    cats.map(([id, label, n]) => `<div class="cnode ${COMPASS_CAT===id?"on":""}" onclick="compassShow('${id}')">${label} <span class="badge">${n}</span></div>`).join("");
}
async function compassShow(cat) {
  COMPASS_CAT = cat;
  renderCompassTree();
  const box = document.getElementById("compass_detail");
  const d = COMPASS;
  if (cat === "types") {
    box.innerHTML = `<h3>对象类型</h3><table><thead><tr><th>类型</th><th>对象数</th><th>动作</th><th></th></tr></thead><tbody>` +
      d.stats.map(t => `<tr><td>${esc(t.name)}</td><td>${t.count}</td><td>${t.actions.length}</td>
        <td><button class="ghost sm" onclick="openType('${t.id}')">打开</button></td></tr>`).join("") + `</tbody></table>`;
  } else if (cat === "pipes") {
    box.innerHTML = `<h3>管道</h3><table><thead><tr><th>ID</th><th>名称</th><th>步骤</th><th></th></tr></thead><tbody>` +
      d.pls.map(p => `<tr><td>${esc(p.id)}</td><td>${esc(p.name)}</td><td>${p.steps.length}</td>
        <td><button class="ghost sm" onclick="setModule('pipeline')">打开</button></td></tr>`).join("") + `</tbody></table>`;
  } else if (cat === "apps") {
    box.innerHTML = `<h3>应用</h3><table><thead><tr><th>名称</th><th>类型</th><th>对象类型</th><th></th></tr></thead><tbody>` +
      d.apps.map(a => `<tr><td>${esc(a.name)}</td><td><span class="tag">${esc(a.type)}</span></td><td>${esc(a.object_type)}</td>
        <td><button class="ghost sm" onclick="openAppView('${a.id}')">打开</button></td></tr>`).join("") + `</tbody></table>`;
  } else if (cat === "models") {
    box.innerHTML = `<h3>模型</h3><table><thead><tr><th>模型</th><th>类型</th><th>请求</th><th></th></tr></thead><tbody>` +
      d.models.map(m => `<tr><td>${esc(m.name)}</td><td><span class="tag">${esc(m.kind)}</span></td><td>${m.requests}</td>
        <td><button class="ghost sm" onclick="setModule('aip');openModelCatalog()">打开</button></td></tr>`).join("") + `</tbody></table>`;
  } else if (cat === "eps") {
    box.innerHTML = `<h3>自定义端点</h3><table><thead><tr><th>ID</th><th>Method</th><th>Path</th></tr></thead><tbody>` +
      d.eps.map(e => `<tr><td>${esc(e.id)}</td><td><span class="tag">${esc(e.method)}</span></td><td><code>${esc(e.path)}</code></td></tr>`).join("") + `</tbody></table>`;
  } else if (cat === "mons") {
    box.innerHTML = `<h3>监控</h3><table><thead><tr><th>规则</th><th>对象类型</th><th>指标</th><th>阈值</th></tr></thead><tbody>` +
      d.mons.map(m => `<tr><td>${esc(m.name)}</td><td>${esc(m.object_type)}</td><td>${esc(m.metric)}</td><td>${esc(m.op)} ${m.threshold}</td></tr>`).join("") + `</tbody></table>`;
  } else if (cat === "media") {
    box.innerHTML = `<h3>媒体</h3><table><thead><tr><th>文件</th><th>大小</th><th></th></tr></thead><tbody>` +
      d.media.map(m => `<tr><td>${esc(m.name)}</td><td>${m.size}B</td><td><a class="link" href="/api/media/${esc(m.name)}" target="_blank">查看</a></td></tr>`).join("") + `</tbody></table>`;
  }
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
    SQL_ROWS = r.rows;
    box.innerHTML = `<div class="row" style="justify-content:space-between;"><span></span>
      <button class="ghost sm" onclick="exportCSV(SQL_ROWS,'sql-result')">⬇ 导出 CSV</button></div>
      <table><thead><tr>` + r.columns.map(c=>`<th>${esc(c)}</th>`).join("") + `</tr></thead><tbody>` +
      r.rows.map(row => "<tr>" + r.columns.map(c=>`<td>${esc(row[c])}</td>`).join("") + "</tr>").join("") + `</tbody></table>`;
  } catch(e) { box.innerHTML = `<pre style="color:var(--danger)">${esc(e.message)}</pre>`; }
}
// B1 时间序列（time-series 分区）
async function openTs() {
  const series = await api("/api/ts/series");
  const c = document.getElementById("content");
  c.innerHTML = `<div class="panel"><h2>📈 时间序列</h2>
    <div class="row"><input id="ts_sid" placeholder="序列ID(如 cpu.usage)" style="width:170px;"/>
      <input id="ts_ent" placeholder="实体(如 node-1)" style="width:140px;"/>
      <textarea id="ts_points" placeholder='数据点 JSON: [["2026-08-13T10:00:00",35.5],["2026-08-13T11:00:00",42.1]]' style="flex:1;height:40px;"></textarea>
      <button onclick="tsIngest()">写入</button></div>
    <div class="row"><select id="ts_pick" onchange="tsShow()">${series.map(s=>`<option value="${esc(s.series_id)}|${esc(s.entity)}">${esc(s.series_id)} · ${esc(s.entity)} (${s.n}点)</option>`).join("")}</select>
      <select id="ts_agg"><option value="">原始</option><option value="avg">平均</option><option value="sum">求和</option><option value="max">最大</option><option value="min">最小</option></select>
      <select id="ts_bucket"><option value="">不聚合</option><option value="hour">按小时</option><option value="day">按天</option></select>
      <button onclick="tsShow()">查询</button>
      <button class="ghost" style="color:#d9534f;" onclick="deleteTsSeries()">删除选中系列</button></div>
    <div id="ts_out"></div></div>`;
  if (series.length) tsShow();
}
async function deleteTsSeries() {
  const sel = document.getElementById("ts_pick").value;
  if (!sel) return;
  const [sid, ent] = sel.split("|");
  if (!confirm(`删除时间序列 ${sid}（实体 ${ent}）？`)) return;
  await api(`/api/ts/series/${encodeURIComponent(sid)}?entity=${encodeURIComponent(ent)}`, { method:"DELETE" });
  toast(`已删除序列 ${sid}`);
  await openTs();
}
async function tsIngest() {
  const sid = document.getElementById("ts_sid").value.trim();
  const ent = document.getElementById("ts_ent").value.trim();
  const raw = document.getElementById("ts_points").value.trim();
  if (!sid || !ent || !raw) { toast("序列/实体/数据点必填"); return; }
  let points; try { points = JSON.parse(raw); } catch(e){ toast("数据点 JSON 解析失败"); return; }
  const r = await api("/api/ts/ingest", { method:"POST", body: JSON.stringify({ series_id: sid, entity: ent, points }) });
  toast(`已写入 ${r.ingested} 点`); await openTs();
}
async function tsShow() {
  const pick = document.getElementById("ts_pick").value;
  if (!pick) return;
  const [sid, ent] = pick.split("|");
  const agg = document.getElementById("ts_agg").value;
  const bucket = document.getElementById("ts_bucket").value;
  const q = await api(`/api/ts/query?series_id=${encodeURIComponent(sid)}&entity=${encodeURIComponent(ent)}${agg ? `&agg=${agg}&bucket=${bucket||"hour"}` : ""}`);
  const pts = q.points || [];
  const box = document.getElementById("ts_out");
  if (!pts.length) { box.innerHTML = `<p class="muted">无数据</p>`; return; }
  // 折线图
  const W = 680, H = 220, padL = 44, padB = 26, padT = 14;
  const vals = pts.map(p => p.value);
  const max = Math.max(...vals), min = Math.min(...vals, 0);
  const rng = (max - min) || 1;
  const step = (W - padL - 10) / Math.max(pts.length - 1, 1);
  const X = i => padL + i * step, Y = v => padT + (H - padB - padT) * (1 - (v - min) / rng);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(" ");
  const area = line + ` L${X(pts.length-1).toFixed(1)},${H-padB} L${padL},${H-padB} Z`;
  let svg = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:#0c0e12;border:1px solid var(--line);border-radius:8px;">
    <path d="${area}" fill="rgba(79,140,255,.15)"/>
    <path d="${line}" fill="none" stroke="#4f8cff" stroke-width="2"/>`;
  pts.forEach((p, i) => {
    svg += `<circle cx="${X(i).toFixed(1)}" cy="${Y(p.value).toFixed(1)}" r="3" fill="#3ecf8e"/>`;
    if (pts.length <= 12) svg += `<text x="${X(i).toFixed(0)}" y="${H-8}" fill="#8b93a7" font-size="9" text-anchor="middle">${esc(String(p.bucket || p.ts || "").slice(5, 16))}</text>`;
  });
  svg += `<text x="6" y="12" fill="#8b93a7" font-size="11">${esc(sid)} · ${esc(ent)}</text></svg>`;
  const cols = Object.keys(pts[0]);
  box.innerHTML = svg + `<table style="margin-top:8px;"><thead><tr>` + cols.map(c=>`<th>${esc(c)}</th>`).join("") + `</tr></thead><tbody>` +
    pts.map(p=>"<tr>"+cols.map(c=>`<td>${esc(p[c])}</td>`).join("")+"</tr>").join("") + `</tbody></table>`;
}

async function openGeo() {  const types = await api("/api/ontology/object-types");
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
      <td><a class="link" href="/api/media/${esc(m.name)}" target="_blank">查看</a>
          <button class="ghost sm" style="color:#d9534f;" onclick="deleteMedia('${esc(m.name)}')">删除</button></td></tr>`).join("") + `</tbody></table>`;
}
async function deleteMedia(name) {
  if (!confirm(`删除媒体 ${name}？`)) return;
  await api(`/api/media/${encodeURIComponent(name)}`, { method:"DELETE" });
  toast(`已删除 ${name}`);
  await refreshMedia();
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
  api("/api/marketplace/packages").then(pkgs => {
    body.innerHTML = `<h3>🛍️ 市场（Marketplace）</h3>
    <h4>安装包</h4><table><thead><tr><th>包</th><th>版本</th><th>分类</th><th>说明</th><th></th></tr></thead><tbody>` +
      pkgs.map(p => `<tr><td><b>${esc(p.name)}</b></td><td>v${esc(p.version)}</td><td><span class="tag">${esc(p.category)}</span></td>
        <td class="muted">${esc(p.description)}（${p.types} 类型 / ${p.apps} 应用）</td>
        <td>${p.installed ? `<button class="ghost sm" style="color:var(--danger)" onclick="uninstallPkg('${esc(p.id)}')">卸载</button>` : `<button class="ghost sm" onclick="installPkg('${esc(p.id)}')">安装</button>`}</td></tr>`).join("") + `</tbody></table>
    <h4>模板</h4><div class="model-grid">` +
    [{ icon:"🛍️", name:"参考架构：数据集成", desc:"从连接器到本体的一键链路", go:"openConnectors()" },
     { icon:"📊", name:"应用模板：仪表盘", desc:"指标卡 + 分组聚合", go:"showAppBuild('dashboard')" },
     { icon:"📝", name:"应用模板：表单", desc:"动作表单直连 Action", go:"showAppBuild('form')" },
     { icon:"🔀", name:"应用模板：工作流", desc:"多步动作编排", go:"showAppBuild('workflow')" },
     { icon:"🔎", name:"应用模板：视图", desc:"对象集只读视图", go:"showAppBuild('view')" }]
      .map(i => `<div class="model-card"><div class="licon">${i.icon}</div><div class="ltitle">${esc(i.name)}</div><div class="ldesc">${esc(i.desc)}</div>
        <div class="row" style="margin-top:8px;"><button class="ghost sm" onclick="${i.go}">创建</button></div></div>`).join("") + `</div>`;
  });
}
async function installPkg(id) {
  try { const r = await api("/api/marketplace/install", { method:"POST", body: JSON.stringify({ package_id: id }) });
    toast(`已安装：${(r.created.types||[]).join(",")}`); await loadSidebar(); openDev("market"); }
  catch(e){ alert(e.message); }
}
async function uninstallPkg(id) {
  if (!confirm(`卸载市场包 ${id}？将删除其应用与对象类型（含数据）。`)) return;
  try { await api("/api/marketplace/uninstall", { method:"POST", body: JSON.stringify({ package_id: id }) });
    toast("已卸载"); await loadSidebar(); openDev("market"); }
  catch(e){ alert(e.message); }
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
document.addEventListener("keydown", e => {
  if (e.shiftKey && (e.key==="N"||e.key==="n")) { if (!document.getElementById("app").classList.contains("hidden")) openLauncher(); }
  if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) { e.preventDefault(); if (!document.getElementById("app").classList.contains("hidden")) { document.getElementById("omnibar").focus(); omnibarSearch(); } }
  if (e.key === "Escape") { omnibarHide(); closeDrawer(); document.getElementById("bell-pop")?.classList.add("hidden"); }
});
document.addEventListener("click", e => {
  const pop = document.getElementById("bell-pop");
  if (pop && !pop.contains(e.target) && e.target.id !== "bellBtn") pop.classList.add("hidden");
});
if (TOKEN) enterApp(); else show("login");
