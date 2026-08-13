"""M7 应用构建扩展：Form / Dashboard / View / Workflow 四类应用 + 版本管理。

对齐 Foundry 应用构建原型：
  - 应用列表与推荐模板（94936832）：Workshop/Slate/Quiver 映射为 Dashboard/Form/Workflow。
  - 可视化构建器（22514938）：以配置驱动的轻量构建（组件树 → 配置文件）。
  - 版本对比（17326356 / 7735061）：每次保存生成版本快照，可对比差异。
  - 仪表盘聚合（87629022）：聚合类型 + 分组 + 时间范围。
每类应用渲染为自包含单文件 HTML（复用 S4 的离线可运行模式）。
"""
import json
import datetime

from . import db
from .ontology import metadata, resolver, actions


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


_APP_TYPES = ("form", "dashboard", "view", "workflow")


def create_app(defn: dict) -> dict:
    aid = (defn.get("id") or "").strip()
    typ = defn.get("type")
    otid = defn.get("object_type")
    if not aid or typ not in _APP_TYPES:
        raise ValueError("id 必填且 type 须为 form/dashboard/view/workflow")
    if not metadata.get_object_type(otid):
        raise ValueError(f"对象类型不存在: {otid}")
    config = defn.get("config") or {}
    if isinstance(config, (dict, list)):
        config = json.dumps(config, ensure_ascii=False)
    now = _now()
    conn = db.get_metadata_conn()
    conn.execute(
        """INSERT OR REPLACE INTO apps (id, name, description, type, object_type, config, created, updated)
           VALUES (?,?,?,?,?,?,?,?)""",
        (aid, defn.get("name", aid), defn.get("description", ""), typ, otid, config, now, now),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": aid, "type": typ, "object_type": otid}


def get_app(aid):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM apps WHERE id=?", (aid,)).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    try:
        d["config"] = json.loads(d["config"])
    except Exception:
        d["config"] = {}
    return d


def list_apps():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT id, name, description, type, object_type, created, updated FROM apps ORDER BY updated DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_app(aid):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM apps WHERE id=?", (aid,))
    conn.execute("DELETE FROM app_versions WHERE app_id=?", (aid,))
    conn.commit()
    conn.close()


# ---- 版本快照与对比（17326356 / 7735061） ----
def save_version(aid):
    app = get_app(aid)
    if not app:
        raise ValueError("应用不存在")
    conn = db.get_metadata_conn()
    ver = conn.execute(
        "SELECT COALESCE(MAX(version),0)+1 AS v FROM app_versions WHERE app_id=?", (aid,)
    ).fetchone()["v"]
    snapshot = json.dumps({
        "name": app["name"], "description": app["description"],
        "type": app["type"], "object_type": app["object_type"], "config": app["config"],
    }, ensure_ascii=False)
    conn.execute("INSERT INTO app_versions (app_id, version, snapshot, created) VALUES (?,?,?,?)",
                 (aid, ver, snapshot, _now()))
    conn.commit()
    conn.close()
    return {"app_id": aid, "version": ver}


def list_versions(aid):
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT version, created FROM app_versions WHERE app_id=? ORDER BY version DESC", (aid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def compare_versions(aid, v1, v2):
    conn = db.get_metadata_conn()
    a = conn.execute("SELECT snapshot FROM app_versions WHERE app_id=? AND version=?", (aid, v1)).fetchone()
    b = conn.execute("SELECT snapshot FROM app_versions WHERE app_id=? AND version=?", (aid, v2)).fetchone()
    conn.close()
    if not a or not b:
        raise ValueError("版本不存在")
    d1, d2 = json.loads(a["snapshot"]), json.loads(b["snapshot"])
    changes = []
    for k in sorted(set(d1) | set(d2)):
        if d1.get(k) != d2.get(k):
            changes.append({"field": k, "from": d1.get(k), "to": d2.get(k)})
    return {"app_id": aid, "from_version": v1, "to_version": v2, "changes": changes}


# ---- 应用数据（服务端聚合/查询，生成的应用只负责渲染） ----
def app_data(app):
    typ = app["type"]
    cfg = app.get("config") or {}
    otid = app["object_type"]
    ot = metadata.get_object_type(otid)
    if not ot:
        return {"cards": [], "rows": [], "error": "对象类型不存在"}
    props = {p["key"]: p["column"] for p in json.loads(ot["properties"])}
    backing = ot["backing_table"]
    dconn = db.get_duckdb()
    try:
        cards = []
        rows = []
        if typ == "dashboard":
            cards.append({"label": "COUNT", "value": int(dconn.execute(f"SELECT COUNT(*) FROM {backing}").fetchone()[0])})
            m = cfg.get("metric") or {}
            field, agg = m.get("field"), m.get("agg")
            if field in props and agg in ("sum", "avg", "min", "max"):
                v = dconn.execute(f'SELECT {agg}({props[field]}) FROM {backing}').fetchone()[0]
                cards.append({"label": f"{agg.upper()} {field}", "value": v})
            gb = cfg.get("group_by")
            if gb in props:
                sql = f'SELECT {props[gb]} AS grp, COUNT(*) AS n'
                if field in props and agg in ("sum", "avg", "min", "max"):
                    sql += f', {agg}({props[field]}) AS v'
                sql += f" FROM {backing} GROUP BY {props[gb]} ORDER BY n DESC LIMIT {int(cfg.get('limit', 10))}"
                cur = dconn.execute(sql)
                rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
        elif typ == "view":
            q = {"where": cfg.get("where"), "limit": int(cfg.get("limit", 200))}
            if cfg.get("orderBy"):
                q["orderBy"] = cfg["orderBy"]
            rows = resolver.query_object_set(otid, q)
        elif typ == "form":
            cards.append({"label": "COUNT", "value": int(dconn.execute(f"SELECT COUNT(*) FROM {backing}").fetchone()[0])})
        return {"cards": cards, "rows": rows}
    finally:
        dconn.close()


def run_workflow(app):
    """按配置依次执行动作步骤（Workflow 应用运行时）。"""
    cfg = app.get("config") or {}
    steps = cfg.get("steps") or []
    out = []
    for s in steps:
        act = metadata.get_action(s.get("action_id", ""))
        if not act:
            out.append({"name": s.get("name", "?"), "status": "error", "error": "动作不存在"})
            continue
        try:
            detail = actions.execute_action(act["id"], s.get("params") or {})
            out.append({"name": s.get("name", act["id"]), "status": "ok", "detail": detail})
        except ValueError as e:
            out.append({"name": s.get("name", act["id"]), "status": "error", "error": str(e)})
    return {"app": app["id"], "steps": out}


# ---- 渲染为自包含 HTML ----
def _esc_json(o):
    return json.dumps(o, ensure_ascii=False).replace("</", "<\\/")


def render_app(app) -> str:
    cfg = app.get("config") or {}
    title = app["name"]
    otid = app["object_type"]
    app_id = app["id"]
    app_json = _esc_json({"id": app_id, "type": app["type"], "object_type": otid, "config": cfg, "name": title})

    if app["type"] == "form":
        act = metadata.get_action(cfg.get("action_id", ""))
        form_fields = cfg.get("fields")
        if not form_fields and act:
            form_fields = [{"key": p["name"], "title": p["name"], "type": p["type"]} for p in json.loads(act["parameters"])]
        action_id = cfg.get("action_id", "")
        if not action_id and act:
            action_id = act["id"]
        body = """  <div class="wrap">
    <div class="panel" style="max-width:520px;">
      <h3>填写并执行动作</h3>
      <div id="formFields"></div>
      <div style="margin-top:14px;"><button class="primary" onclick="doAction()">执行</button> <span id="msg" class="muted"></span></div>
    </div>
  </div>
<script>
const FIELDS = __FIELDS_JSON__;
const ACTION_ID = "__ACTION_ID__";
(function(){ const box=document.getElementById("formFields");
  box.innerHTML = FIELDS.map(p => "<div><label>"+p.title+" ("+p.type+")</label><input id='f_"+p.key+"' placeholder='"+p.type+"'/></div>").join("");
})();
async function doAction(){
  const params = {}; FIELDS.forEach(p => { const v=document.getElementById("f_"+p.key).value; if(v!=="") params[p.key]=v; });
  try {
    const r = await apiJson("/api/ontology/actions/"+ACTION_ID+"/execute", { method:"POST", body: JSON.stringify({ params }) });
    document.getElementById("msg").textContent = "成功：" + JSON.stringify(r.detail);
  } catch(e){ document.getElementById("msg").textContent = "失败：" + e.message; }
}
</script>"""
        body = body.replace("__FIELDS_JSON__", _esc_json(form_fields or [])).replace("__ACTION_ID__", action_id)
    elif app["type"] == "dashboard":
        body = """  <div class="wrap">
    <div class="cards" id="cards"></div>
    <div class="panel"><h3>按 __GROUP_BY__ 分组</h3><div id="tbl"></div></div>
  </div>
<script>
async function render(){
  const d = await apiJson("/api/apps/__APP_ID__/data");
  document.getElementById("cards").innerHTML = (d.cards||[]).map(c =>
    '<div class="stat"><div class="stat-n">'+esc(c.value)+'</div><div class="stat-l">'+esc(c.label)+'</div></div>').join("");
  const rows = d.rows||[];
  if(!rows.length){ document.getElementById("tbl").innerHTML='<p class="muted">暂无分组数据</p>'; return; }
  const cols = Object.keys(rows[0]);
  document.getElementById("tbl").innerHTML = "<table><thead><tr>"+cols.map(c=>'<th>'+esc(c)+'</th>').join("")+"</tr></thead><tbody>" +
    rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c])+'</td>').join("")+'</tr>').join("")+"</tbody></table>";
}
render();
</script>"""
        body = body.replace("__GROUP_BY__", _esc_json(str(cfg.get("group_by", "—")))).replace("__APP_ID__", app_id)
    elif app["type"] == "view":
        body = """  <div class="wrap">
    <div class="bar"><input id="q" placeholder="关键字过滤…" style="max-width:260px;"/><button onclick="load()">查询</button><span id="cnt" class="muted"></span></div>
    <div id="tbl"></div>
  </div>
<script>
async function load(){
  const q = document.getElementById("q").value.trim().toLowerCase();
  const d = await apiJson("/api/apps/__APP_ID__/data");
  let rows = d.rows||[];
  if(q) rows = rows.filter(r => Object.values(r).some(v => String(v==null?"":v).toLowerCase().includes(q)));
  document.getElementById("cnt").textContent = rows.length + " 行";
  if(!rows.length){ document.getElementById("tbl").innerHTML='<p class="muted">无结果</p>'; return; }
  const cols = Object.keys(rows[0]);
  document.getElementById("tbl").innerHTML = "<table><thead><tr>"+cols.map(c=>'<th>'+esc(c)+'</th>').join("")+"</tr></thead><tbody>" +
    rows.map(r=>'<tr>'+cols.map(c=>'<td>'+esc(r[c])+'</td>').join("")+'</tr>').join("")+"</tbody></table>";
}
load();
</script>"""
        body = body.replace("__APP_ID__", app_id)
    else:  # workflow
        steps = cfg.get("steps") or []
        body = """  <div class="wrap">
    <div class="panel"><h3>工作流：__TITLE__</h3>
      <div id="steps"></div>
      <button class="primary" onclick="run()">▶ 运行全部步骤</button>
      <div id="out" style="margin-top:12px;"></div></div>
  </div>
<script>
const STEPS = __STEPS_JSON__;
(function(){ document.getElementById("steps").innerHTML = STEPS.map((s,i)=>'<div class="muted">'+(i+1)+'. '+esc(s.name)+' → '+esc(s.action_id)+'</div>').join(""); })();
async function run(){
  const r = await apiJson("/api/apps/__APP_ID__/run", { method:"POST", body:"{}" });
  document.getElementById("out").innerHTML = "<table><thead><tr><th>步骤</th><th>状态</th><th>结果</th></tr></thead><tbody>" +
    (r.steps||[]).map(s => '<tr><td>'+esc(s.name)+'</td><td>'+esc(s.status)+'</td><td>'+esc(JSON.stringify(s.detail||s.error||""))+'</td></tr>').join("") + "</tbody></table>";
}
</script>"""
        body = body.replace("__TITLE__", title).replace("__STEPS_JSON__", _esc_json(steps)).replace("__APP_ID__", app_id)

    shell = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>__TITLE__ · Ontic App</title>
<style>
  :root { --bg:#f6f7f9; --card:#fff; --line:#e3e6ea; --ink:#1f2329; --mut:#8a94a6; --brand:#2f6df0; --danger:#e5484d; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,"Segoe UI",Roboto,"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--ink); }
  header { display:flex; align-items:center; gap:12px; padding:12px 18px; background:var(--card); border-bottom:1px solid var(--line); }
  .wrap { padding:18px; max-width:1100px; margin:0 auto; }
  .bar { display:flex; gap:8px; align-items:center; margin-bottom:12px; flex-wrap:wrap; }
  button { border:1px solid var(--line); background:var(--card); color:var(--ink); padding:6px 14px; border-radius:8px; cursor:pointer; font-size:13px; }
  button.primary { background:var(--brand); border-color:var(--brand); color:#fff; }
  table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:10px; overflow:hidden; }
  th,td { text-align:left; padding:8px 12px; border-bottom:1px solid var(--line); }
  th { background:#fafbfc; color:var(--mut); font-size:12px; }
  .panel { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin-top:14px; }
  .cards { display:flex; gap:12px; flex-wrap:wrap; }
  .stat { flex:1; min-width:150px; background:var(--card); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .stat-n { font-size:26px; font-weight:700; color:var(--brand); }
  .stat-l { font-size:12px; color:var(--mut); }
  label { display:block; font-size:12px; color:var(--mut); margin:10px 0 4px; }
  input,select { width:100%; padding:7px 9px; border:1px solid var(--line); border-radius:7px; font-size:13px; }
  .muted { color:var(--mut); }
  .hidden { display:none; }
  #settings { padding:8px 18px; background:#fffbe6; border-bottom:1px solid #ffe58f; font-size:12px; display:flex; gap:8px; align-items:center; }
  #settings input { width:320px; }
</style>
</head>
<body>
<div id="settings">
  <span class="muted">API 地址</span><input id="apiBase"/>
  <button onclick="saveApiBase()">保存</button><span id="connState" class="muted"></span>
</div>
<div id="login" class="wrap hidden">
  <div class="panel" style="max-width:360px;margin:40px auto;">
    <h2>登录 Ontic</h2>
    <label>用户名</label><input id="lu" value="admin"/>
    <label>密码</label><input id="lp" type="password" value="admin123"/>
    <div style="margin-top:14px;"><button class="primary" onclick="doLogin()">登录</button> <span id="lerr" class="muted"></span></div>
  </div>
</div>
<div id="app" class="hidden">
  <header><strong>__TITLE__</strong><span class="muted" id="who"></span>
    <span style="flex:1"></span><button class="ghost" onclick="doLogout()">退出</button></header>
  __BODY__
</div>
<script>
const APP = __APP_JSON__;
let API_BASE = localStorage.getItem("ontic_api_base") || (location.origin && location.origin!=="null" ? location.origin : "");
let TOKEN = localStorage.getItem("of_token") || "";
function saveApiBase(){ API_BASE=document.getElementById("apiBase").value.trim(); localStorage.setItem("ontic_api_base",API_BASE); checkConn(); }
function api(path,opts){ return fetch(API_BASE+path, Object.assign({ headers:{ "Content-Type":"application/json", Authorization:"Bearer "+TOKEN } }, opts)); }
async function apiJson(path,opts){ const r=await api(path,opts); if(!r.ok){ const t=await r.text(); throw new Error(t||r.status); } return r.json(); }
function esc(v){ if(v===null||v===undefined) return ""; return String(v).replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }
async function checkConn(){ const el=document.getElementById("connState"); if(!API_BASE){ el.textContent="未设置 API 地址"; return; }
  try{ const me=await apiJson("/api/me"); el.textContent="已连接 · "+me.username; }catch(e){ el.textContent="连接失败"; } }
function show(id){ document.getElementById(id).classList.remove("hidden"); }
function hide(id){ document.getElementById(id).classList.add("hidden"); }
async function doLogin(){
  document.getElementById("lerr").textContent="";
  try{ const r=await api("/api/auth/login",{ method:"POST", body:JSON.stringify({ username:document.getElementById("lu").value, password:document.getElementById("lp").value })});
    const j=await r.json(); TOKEN=j.access_token; localStorage.setItem("of_token",TOKEN); enter(); }
  catch(e){ document.getElementById("lerr").textContent=e.message; }
}
function doLogout(){ TOKEN=""; localStorage.removeItem("of_token"); show("login"); hide("app"); }
async function enter(){ hide("login"); show("app"); try{ const me=await apiJson("/api/me"); document.getElementById("who").textContent=me.username+" · "+me.role; }catch(e){ doLogout(); return; } }
document.getElementById("apiBase").value=API_BASE;
(async function init(){ await checkConn(); if(TOKEN){ try{ await enter(); return; }catch(e){} } show("login"); })();
</script>
</body>
</html>"""
    return (shell
            .replace("__TITLE__", title)
            .replace("__APP_JSON__", app_json)
            .replace("__BODY__", body))
