"""应用构建（S4）：把一个对象类型生成为自包含的单文件 CRUD Web 应用。

生成的 HTML 是纯静态单文件：内置 CSS/JS，用 Ontic REST API 做 查询/创建/编辑/删除。
- 内嵌到 Ontic 前端时：同源，自动复用主会话令牌（localStorage 'of_token'），无需重登。
- 下载为独立文件运行时：可手动填写 API 地址并登录，开箱即用。
这对应 Foundry 的 "Application Building"——本体定义即应用骨架。
"""
import json


def _escape_for_script(js: str) -> str:
    """防止嵌入到 <script> 里的 JSON 被 </script> 提前截断。"""
    return js.replace("</", "<\\/")


def generate_crud_app(ot: dict) -> str:
    props = json.loads(ot["properties"])
    pk = ot["primary_key"]
    ot_id = ot["id"]
    ot_name = ot.get("name") or ot_id
    props_json = _escape_for_script(json.dumps(props, ensure_ascii=False))

    template = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>__OT_NAME__ · Ontic App</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --ink:#1f2329; --mut:#8a94a6; --brand:#2f6df0; --danger:#e5484d; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--ink); }
  header { display:flex; align-items:center; gap:12px; padding:12px 18px; background:var(--card); border-bottom:1px solid var(--line); }
  header strong { font-size:16px; }
  header .sp { flex:1; }
  .wrap { padding:18px; max-width:1100px; margin:0 auto; }
  .bar { display:flex; align-items:center; gap:8px; margin-bottom:14px; flex-wrap:wrap; }
  button { border:1px solid var(--line); background:var(--card); color:var(--ink); padding:6px 14px; border-radius:8px; cursor:pointer; font-size:13px; }
  button.primary { background:var(--brand); border-color:var(--brand); color:#fff; }
  button.danger { color:var(--danger); border-color:#f3c2c4; }
  button.ghost { background:transparent; border-color:transparent; color:var(--mut); }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th,td { text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); }
  th { background:#fafbfc; color:var(--mut); font-weight:600; font-size:12px; }
  tr:last-child td { border-bottom:none; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin-top:14px; }
  label { display:block; font-size:12px; color:var(--mut); margin:10px 0 4px; }
  input,select { width:100%; padding:7px 9px; border:1px solid var(--line); border-radius:7px; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:10px; }
  .muted { color:var(--mut); }
  .hidden { display:none; }
  .toast { position:fixed; bottom:20px; left:50%; transform:translateX(-50%); background:#1f2329; color:#fff; padding:8px 16px; border-radius:8px; font-size:13px; }
  #settings { padding:8px 18px; background:#fffbe6; border-bottom:1px solid #ffe58f; font-size:12px; display:flex; gap:8px; align-items:center; }
  #settings input { width:320px; }
</style>
</head>
<body>
<div id="settings">
  <span class="muted">API 地址</span>
  <input id="apiBase" placeholder="例如 http://localhost:8000" />
  <button onclick="saveApiBase()">保存</button>
  <span id="connState" class="muted"></span>
</div>

<div id="login" class="wrap hidden">
  <div class="panel" style="max-width:360px;margin:40px auto;">
    <h2>登录 Ontic</h2>
    <p class="muted">该应用通过 Ontic API 读写业务对象，需要令牌。</p>
    <label>用户名</label><input id="lu" value="admin"/>
    <label>密码</label><input id="lp" type="password" value="admin123"/>
    <div style="margin-top:14px;"><button class="primary" onclick="doLogin()">登录</button> <span id="lerr" class="muted"></span></div>
  </div>
</div>

<div id="app" class="hidden">
  <header>
    <strong>__OT_NAME__</strong>
    <span class="muted" id="who"></span>
    <span class="sp"></span>
    <button class="primary" onclick="openNew()">+ 新建</button>
    <button class="ghost" onclick="doLogout()">退出</button>
  </header>
  <div class="wrap">
    <div class="bar">
      <input id="q" placeholder="过滤（任意字段包含…）" style="max-width:280px;" oninput="load()"/>
      <button onclick="load()">刷新</button>
      <span id="cnt" class="muted"></span>
    </div>
    <div id="tableWrap"></div>
    <div id="editor" class="panel hidden">
      <h3 id="edTitle">新建</h3>
      <div class="grid" id="formFields"></div>
      <div style="margin-top:14px;">
        <button class="primary" onclick="save()">保存</button>
        <button class="ghost" onclick="closeEditor()">取消</button>
        <span id="edMsg" class="muted"></span>
      </div>
    </div>
  </div>
</div>

<script>
const OT_ID = "__OT_ID__";
const OT_NAME = "__OT_NAME__";
const PK = "__PK__";
const PROPS = __PROPS_JSON__;
const CREATE_ACT = OT_ID + "__create";
const UPDATE_ACT = OT_ID + "__update";
const DELETE_ACT = OT_ID + "__delete";

let API_BASE = localStorage.getItem("ontic_api_base") || (location.origin && location.origin !== "null" ? location.origin : "");
let TOKEN = localStorage.getItem("of_token") || "";
let editingId = null;
let ROWS = [];

function saveApiBase(){ API_BASE = document.getElementById("apiBase").value.trim(); localStorage.setItem("ontic_api_base", API_BASE); checkConn(); }
function api(path, opts){ return fetch(API_BASE + path, Object.assign({ headers: { "Content-Type":"application/json", Authorization:"Bearer "+TOKEN } }, opts)); }
async function apiJson(path, opts){ const r = await api(path, opts); if(!r.ok){ const t = await r.text(); throw new Error(t||r.status); } return r.json(); }

async function checkConn(){
  const el = document.getElementById("connState");
  if(!API_BASE){ el.textContent = "未设置 API 地址"; return; }
  try { const me = await apiJson("/api/me"); el.textContent = "已连接 · "+me.username; }
  catch(e){ el.textContent = "连接失败：" + e.message; }
}

function show(id){ document.getElementById(id).classList.remove("hidden"); }
function hide(id){ document.getElementById(id).classList.add("hidden"); }
function toast(msg){ const t=document.createElement("div"); t.className="toast"; t.textContent=msg; document.body.appendChild(t); setTimeout(()=>t.remove(),2200); }

async function doLogin(){
  document.getElementById("lerr").textContent = "";
  try {
    const r = await api("/api/auth/login", { method:"POST", body: JSON.stringify({ username:document.getElementById("lu").value, password:document.getElementById("lp").value }) });
    const j = await r.json(); TOKEN = j.access_token; localStorage.setItem("of_token", TOKEN);
    enter();
  } catch(e){ document.getElementById("lerr").textContent = e.message; }
}
function doLogout(){ TOKEN=""; localStorage.removeItem("of_token"); show("login"); hide("app"); }

async function enter(){
  hide("login"); show("app");
  try { const me = await apiJson("/api/me"); document.getElementById("who").textContent = me.username + " · " + me.role; }
  catch(e){ doLogout(); return; }
  load();
}

async function load(){
  const q = document.getElementById("q").value.trim();
  let where = null;
  if(q){ where = { op:"and", conditions: PROPS.map(p => ({ field:p.key, op:"contains", value:q })) }; }
  const body = { where, limit: 500, offset: 0 };
  try {
    const res = await apiJson("/api/ontology/object-types/" + OT_ID + "/query", { method:"POST", body: JSON.stringify(body) });
    render(res.rows || []);
    document.getElementById("cnt").textContent = (res.rows||[]).length + " 行";
  } catch(e){ toast("查询失败：" + e.message); }
}

function render(rows){
  ROWS = rows;
  const wrap = document.getElementById("tableWrap");
  if(!rows.length){ wrap.innerHTML = '<p class="muted">暂无数据</p>'; return; }
  const cols = PROPS.map(p => p.key);
  let h = "<table><thead><tr>" + cols.map(c => "<th>"+c+"</th>").join("") + "<th></th></tr></thead><tbody>";
  rows.forEach((r, i) => {
    h += "<tr>" + cols.map(c => "<td>" + escapeHtml(r[c]) + "</td>").join("") + "<td style='white-space:nowrap'>"
       + "<button onclick='openEdit(ROWS[" + i + "])'>编辑</button> "
       + "<button class='danger' onclick='del(ROWS[" + i + "][" + JSON.stringify(PK) + "])'>删除</button></td></tr>";
  });
  h += "</tbody></table>";
  wrap.innerHTML = h;
}

function escapeHtml(v){ if(v===null||v===undefined) return ""; return String(v).replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }

function buildForm(row){
  const box = document.getElementById("formFields");
  box.innerHTML = PROPS.map(p => {
    const v = row ? (row[p.key] ?? "") : "";
    const dis = (row && p.key === PK) ? "disabled" : "";
    return "<div><label>"+p.title+" ("+p.type+")</label><input id='f_"+p.key+"' value='"+escapeHtml(v)+"' "+dis+"/></div>";
  }).join("");
}

function openNew(){ editingId = null; document.getElementById("edTitle").textContent = "新建 " + OT_NAME; buildForm(null); show("editor"); }
function openEdit(row){ editingId = row[PK]; document.getElementById("edTitle").textContent = "编辑 #" + row[PK]; buildForm(row); show("editor"); }
function closeEditor(){ hide("editor"); }

async function save(){
  const params = {};
  PROPS.forEach(p => { const v = document.getElementById("f_"+p.key).value; if(v !== "" || p.key === PK) params[p.key] = v; });
  if(editingId !== null) params[PK] = editingId;
  const act = editingId !== null ? UPDATE_ACT : CREATE_ACT;
  try {
    const res = await apiJson("/api/ontology/actions/" + act + "/execute", { method:"POST", body: JSON.stringify({ params }) });
    document.getElementById("edMsg").textContent = JSON.stringify(res.detail);
    closeEditor(); load();
  } catch(e){ document.getElementById("edMsg").textContent = "失败：" + e.message; }
}

async function del(id){
  if(!confirm("确认删除 #" + id + " ?")) return;
  try {
    const res = await apiJson("/api/ontology/actions/" + DELETE_ACT + "/execute", { method:"POST", body: JSON.stringify({ params: { id } }) });
    toast("已删除 #" + id); load();
  } catch(e){ toast("删除失败：" + e.message); }
}

// 启动
document.getElementById("apiBase").value = API_BASE;
(async function init(){
  await checkConn();
  if(TOKEN){ try { await enter(); return; } catch(e){} }
  show("login");
})();
</script>
</body>
</html>"""
    return (template
            .replace("__OT_ID__", ot_id)
            .replace("__OT_NAME__", ot_name)
            .replace("__PK__", pk)
            .replace("__PROPS_JSON__", props_json))
