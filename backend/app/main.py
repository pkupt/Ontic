"""FastAPI 应用入口：鉴权 + Ontology API + 静态前端(SPA)。

本地运行： cd backend && uvicorn app.main:app --reload --port 8000
Docker：     docker compose up  ->  http://localhost:8080
"""
from fastapi import FastAPI, Depends, HTTPException, Request, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
import json
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from . import config, db, security, models
from .ontology import metadata, resolver, actions, osdk
from . import ingestion, app_builder, aip, connectors, pipelines, functions, aip_platform
from . import app_platform, security_platform, observability
from . import data_plane, dev
from .seed import seed

app = FastAPI(title="Ontic", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_current_user(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供令牌")
    raw = auth[len("Bearer "):]
    sub = security.decode_token(raw)
    if sub:
        conn = db.get_metadata_conn()
        row = conn.execute("SELECT username FROM users WHERE username=?", (sub,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=401, detail="用户不存在")
        return sub
    # 兜底：接受持久化 API Token（M12 开发者控制台签发）
    user = dev.verify_token(raw)
    if not user:
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    return user


@app.on_event("startup")
def _startup():
    seed()
    aip_platform.seed_models()
    for ep in data_plane.list_endpoints():
        try:
            data_plane.register_endpoint(app, ep)
        except Exception:
            pass


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ontic"}


@app.get("/api/activity")
def api_activity(limit: int = 50, user: str = Depends(get_current_user)):
    """活动 / 通知中心（对齐 Foundry 通知中心 74849331；M10 审计基础）。"""
    return metadata.list_activity(limit=min(limit, 200))


@app.post("/api/auth/login", response_model=models.TokenResponse)
def login(req: models.LoginRequest):
    conn = db.get_metadata_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username=?", (req.username,)
    ).fetchone()
    conn.close()
    if not row or not security.verify_password(req.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return models.TokenResponse(access_token=security.create_access_token(req.username))


@app.get("/api/me", response_model=models.UserOut)
def me(user: str = Depends(get_current_user)):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT role FROM users WHERE username=?", (user,)).fetchone()
    conn.close()
    return models.UserOut(username=user, role=row["role"])


def require_admin(user: str):
    if metadata.user_role(user) != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可执行此操作")


# ---- M1 权限管理（用户 / 授权） ----
@app.get("/api/admin/users")
def api_list_users(user: str = Depends(get_current_user)):
    require_admin(user)
    return metadata.list_users()


@app.post("/api/admin/users")
def api_create_user(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    uname = (req.get("username") or "").strip()
    pw = req.get("password") or ""
    role = req.get("role") or "analyst"
    if not uname or not pw:
        raise HTTPException(status_code=400, detail="用户名与密码必填")
    metadata.create_user(uname, pw, role)
    metadata.log_activity("user", f"创建用户 {uname}（{role}）")
    return {"ok": True, "username": uname, "role": role}


@app.delete("/api/admin/users/{username}")
def api_delete_user(username: str, user: str = Depends(get_current_user)):
    require_admin(user)
    if username == user:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员")
    metadata.delete_user(username)
    return {"ok": True}


@app.post("/api/admin/users/{username}/role")
def api_set_role(username: str, req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    metadata.set_role(username, req.get("role", "analyst"))
    return {"ok": True}


@app.get("/api/admin/grants")
def api_list_grants(user: str = Depends(get_current_user)):
    require_admin(user)
    return metadata.list_grants()


@app.post("/api/admin/grants")
def api_grant(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    metadata.grant(req["username"], req["object_type"], req.get("level", "read"))
    metadata.log_activity("grant", f"授权 {req['username']} → {req['object_type']}（{req.get('level','read')}）")
    return {"ok": True}


@app.delete("/api/admin/grants")
def api_revoke(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    metadata.revoke_grant(req["username"], req["object_type"])
    return {"ok": True}


@app.get("/api/ontology/object-types")
def api_list_types(user: str = Depends(get_current_user)):
    return metadata.list_object_types_for_user(user)


@app.get("/api/ontology/stats")
def api_stats(user: str = Depends(get_current_user)):
    """每个对象类型的对象数 + 动作数（侧栏徽标 / 概览用，一次请求拿到全部）。"""
    types = metadata.list_object_types_for_user(user)
    acts = metadata.list_actions()
    by_type = {}
    for a in acts:
        by_type.setdefault(a["object_type"], []).append({"id": a["id"], "name": a["name"], "operation": a["operation"]})
    dconn = db.get_duckdb()
    out = []
    try:
        for t in types:
            try:
                n = dconn.execute(f'SELECT COUNT(*) FROM {t["backing_table"]}').fetchone()[0]
            except Exception:
                n = 0
            out.append({
                "id": t["id"], "name": t["name"], "description": t.get("description", ""),
                "count": int(n), "actions": by_type.get(t["id"], []),
            })
    finally:
        dconn.close()
    return out


@app.get("/api/ontology/object-types/{type_id}")
def api_get_type(type_id: str, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    ot = metadata.get_object_type(type_id)
    if not ot:
        raise HTTPException(status_code=404, detail="对象类型不存在")
    return ot


@app.post("/api/ontology/object-types/{type_id}/query", response_model=models.QueryResponse)
def api_query(type_id: str, req: models.QueryRequest, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权查询该对象类型")
    try:
        rows = resolver.query_object_set(type_id, req.dict(), user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return models.QueryResponse(rows=rows, count=len(rows))


@app.post("/api/ontology/object-types/{type_id}/count")
def api_count(type_id: str, req: dict = None, user: str = Depends(get_current_user)):
    """返回对象集在给定过滤下的总行数（概览 / Usage 面板）。"""
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    if req is None:
        req = {}
    try:
        total = resolver.count_object_set(type_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"total": total}


@app.get("/api/ontology/actions")
def api_list_actions(user: str = Depends(get_current_user)):
    return metadata.list_actions()


@app.post("/api/ontology/actions/{action_id}/execute", response_model=models.ActionExecuteResponse)
def api_execute(action_id: str, req: models.ActionExecuteRequest, user: str = Depends(get_current_user)):
    act = metadata.get_action(action_id)
    if not act:
        raise HTTPException(status_code=404, detail="动作不存在")
    if not metadata.can_access(user, act["object_type"], "write"):
        raise HTTPException(status_code=403, detail="无权执行该动作")
    try:
        detail = actions.execute_action(action_id, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    metadata.log_activity("action", f"执行动作 {action_id}（{act['object_type']}）")
    return models.ActionExecuteResponse(detail=detail)


@app.get("/api/ontology/osdk/{lang}")
def api_osdk(lang: str, user: str = Depends(get_current_user)):
    if lang == "python":
        return JSONResponse({"language": "python", "code": osdk.generate_python()})
    if lang == "typescript":
        return JSONResponse({"language": "typescript", "code": osdk.generate_typescript()})
    raise HTTPException(status_code=400, detail="支持的语言: python | typescript")


@app.get("/api/ontology/object-types/{type_id}/app", response_class=HTMLResponse)
def api_app(type_id: str, user: str = Depends(get_current_user)):
    """S4 应用构建：把对象类型生成自包含的单文件 CRUD 应用（HTML）。"""
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    ot = metadata.get_object_type(type_id)
    if not ot:
        raise HTTPException(status_code=404, detail="对象类型不存在")
    return HTMLResponse(app_builder.generate_crud_app(ot))


# ---- M2 链接类型 + 图遍历 ----
@app.get("/api/ontology/link-types")
def api_list_links(user: str = Depends(get_current_user)):
    return metadata.list_link_types()


@app.post("/api/ontology/link-types")
def api_create_link(req: dict, user: str = Depends(get_current_user)):
    try:
        metadata.create_link_type(req)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"缺少字段: {e}")
    metadata.log_activity("link", f"创建链接类型 {req.get('id')}（{req.get('source_type')}→{req.get('target_type')}）")
    return {"ok": True, "id": req["id"]}


# ---- 属性编辑（对齐 Foundry 类型详情 Properties 面板，45104673） ----
@app.post("/api/ontology/object-types/{type_id}/properties")
def api_add_property(type_id: str, req: dict, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "write"):
        raise HTTPException(status_code=403, detail="无权修改该对象类型")
    try:
        return metadata.add_property(type_id, req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/ontology/object-types/{type_id}/properties/{key}")
def api_remove_property(type_id: str, key: str, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "write"):
        raise HTTPException(status_code=403, detail="无权修改该对象类型")
    try:
        return metadata.remove_property(type_id, key)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- M3 Ontology Manager（可视化建模，无需代码） ----
@app.post("/api/ontology/object-types")
def api_create_object_type(req: dict, user: str = Depends(get_current_user)):
    try:
        res = ingestion.create_object_type_from_def(req)
        metadata.log_activity("type", f"创建对象类型 {req.get('id')}（{req.get('name','')}）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ontology/actions")
def api_create_action(req: dict, user: str = Depends(get_current_user)):
    """创建自定义动作（如批量折扣、状态流转），parameters 为字段定义列表。"""
    if not req.get("id") or not req.get("object_type") or not req.get("operation"):
        raise HTTPException(status_code=400, detail="id / object_type / operation 必填")
    if not metadata.get_object_type(req["object_type"]):
        raise HTTPException(status_code=400, detail="关联的对象类型不存在")
    params = req.get("parameters") or []
    metadata.create_action({
        "id": req["id"],
        "name": req.get("name", req["id"]),
        "description": req.get("description", ""),
        "object_type": req["object_type"],
        "operation": req["operation"],
        "parameters": json.dumps(params),
    })
    return {"ok": True, "id": req["id"]}


# ---- M4 连接器框架 ----
@app.get("/api/connectors")
def api_connectors(user: str = Depends(get_current_user)):
    return connectors.list_connectors()


@app.post("/api/connectors/ingest")
async def api_connector_ingest(
    connector_type: str = Form(...),
    object_type_id: str = Form(...),
    primary_key: str = Form("id"),
    config: str = Form("{}"),
    file: UploadFile = File(None),
    user: str = Depends(get_current_user),
):
    try:
        cfg = json.loads(config or "{}")
        file_bytes = (await file.read()) if file and file.filename else None
        res = connectors.dispatch(
            connector_type, object_type_id, primary_key, file_bytes, file.filename if file else None, cfg
        )
        metadata.log_activity("ingest", f"接入数据 {connector_type} → {object_type_id}")
        return res
    except (ValueError, KeyError, json.JSONDecodeError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- M5 管道与转换框架 ----
@app.get("/api/functions")
def api_functions(user: str = Depends(get_current_user)):
    return functions.list_functions()


@app.get("/api/pipelines")
def api_list_pipelines(user: str = Depends(get_current_user)):
    return metadata.list_pipelines()


@app.post("/api/pipelines")
def api_create_pipeline(req: dict, user: str = Depends(get_current_user)):
    if not req.get("id") or not req.get("steps"):
        raise HTTPException(status_code=400, detail="id 与 steps 必填")
    metadata.create_pipeline(req)
    return {"ok": True, "id": req["id"]}


@app.post("/api/pipelines/{pid}/run")
def api_run_pipeline(pid: str, user: str = Depends(get_current_user)):
    p = metadata.get_pipeline(pid)
    if not p:
        raise HTTPException(status_code=404, detail="管道不存在")
    try:
        res = pipelines.run_pipeline(p)
        metadata.log_activity("pipeline", f"运行管道 {pid}（{res.get('steps_run',0)} 步）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ontology/object-types/{type_id}/links")
def api_type_links(type_id: str, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    return metadata.list_links_for_type(type_id)


@app.get("/api/ontology/object-types/{type_id}/{object_id}/links/{link_id}")
def api_traverse(type_id: str, object_id: str, link_id: str, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    try:
        return resolver.query_linked(type_id, object_id, link_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ontology/object-types/{type_id}/{object_id}/graph")
def api_graph(type_id: str, object_id: str, hops: int = 2, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, type_id, "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    try:
        return resolver.traverse_graph(type_id, object_id, max_hops=max(1, min(hops, 4)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- S5 AIP / Agent ----
@app.get("/api/aip/tools")
def api_aip_tools(user: str = Depends(get_current_user)):
    return aip.TOOLS


@app.get("/api/aip/llm-status")
def api_aip_llm_status(user: str = Depends(get_current_user)):
    return {"available": aip.llm_available(), **aip.llm_config()}


@app.post("/api/aip/llm-chat")
def api_aip_llm_chat(req: dict, user: str = Depends(get_current_user)):
    msg = req.get("message", "")
    if not msg:
        raise HTTPException(status_code=400, detail="message 必填")
    try:
        out = aip.llm_chat(msg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    aip_platform.log_usage("llm", "request", 1, True, source="llm-chat", payload={"message": msg[:200]})
    aip_platform.log_usage("llm", "token", max(4, len(msg) // 4) + len(out) // 4, True, source="llm-chat")
    return {"reply": out}


@app.post("/api/aip/chat")
def api_aip_chat(req: dict, user: str = Depends(get_current_user)):
    try:
        res = aip.chat(req.get("message", ""), req.get("history"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    msg = req.get("message", "")
    aip_platform.log_usage("ontic-rule-planner", "request", 1, True, source="chat",
                           payload={"role": "USER", "contents": [msg]})
    aip_platform.log_usage("ontic-rule-planner", "token",
                           max(4, len(msg) // 4) + len(res.get("reply", "")) // 4, True, source="chat")
    return res


# ---- M6 AIP 平台（模型 / 用量 / 评估 / 对比 / 服务日志） ----
@app.get("/api/aip/models")
def api_aip_models(user: str = Depends(get_current_user)):
    return aip_platform.list_models()


@app.get("/api/aip/usage")
def api_aip_usage(days: int = 30, user: str = Depends(get_current_user)):
    return aip_platform.get_usage(days=max(1, min(days, 365)))


@app.get("/api/aip/logs")
def api_aip_logs(limit: int = 50, source: str = "", user: str = Depends(get_current_user)):
    return aip_platform.service_logs(limit=min(limit, 200), source=source)


@app.get("/api/aip/evalsuites")
def api_eval_suites(user: str = Depends(get_current_user)):
    return aip_platform.list_suites()


@app.post("/api/aip/evalsuites")
def api_eval_create(req: dict, user: str = Depends(get_current_user)):
    if not req.get("id") or not req.get("name"):
        raise HTTPException(status_code=400, detail="id 与 name 必填")
    aip_platform.create_suite(req["id"], req["name"], req.get("target", ""))
    metadata.log_activity("eval", f"创建评估套件 {req['id']}（{req['name']}）")
    return {"ok": True, "id": req["id"]}


@app.get("/api/aip/evalsuites/{sid}")
def api_eval_get(sid: str, user: str = Depends(get_current_user)):
    s = aip_platform.get_suite(sid)
    if not s:
        raise HTTPException(status_code=404, detail="评估套件不存在")
    return s


@app.post("/api/aip/evalsuites/{sid}/cases")
def api_eval_add_case(sid: str, req: dict, user: str = Depends(get_current_user)):
    aip_platform.add_case(sid, req.get("name", "case"), req.get("input", ""), req.get("expected", ""))
    return {"ok": True}


@app.post("/api/aip/evalsuites/{sid}/run")
def api_eval_run(sid: str, user: str = Depends(get_current_user)):
    try:
        res = aip_platform.run_suite(sid)
        metadata.log_activity("eval", f"运行评估套件 {sid}：{res['passed']}/{res['total']} 通过")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/aip/evalsuites/{sid}/results")
def api_eval_results(sid: str, user: str = Depends(get_current_user)):
    return aip_platform.suite_results(sid)


@app.post("/api/aip/playground")
def api_aip_playground(req: dict, user: str = Depends(get_current_user)):
    prompt = req.get("prompt", "")
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt 必填")
    return aip_platform.playground(prompt, req.get("model_a", "ontic-rule-planner"), req.get("model_b", "gpt-4o"))


@app.post("/api/aip/doc-extract")
def api_aip_doc_extract(req: dict, user: str = Depends(get_current_user)):
    """文档智能：把文本按行抽取为对象类型（占位实现，可接 OCR/LLM）。"""
    otid = (req.get("object_type_id") or "").strip()
    text = req.get("text", "")
    if not otid or not text:
        raise HTTPException(status_code=400, detail="object_type_id 与 text 必填")
    try:
        res = aip_platform.doc_extract(text, otid)
        metadata.log_activity("ingest", f"文档智能抽取 → {otid}（{res['lines']} 行）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- S3 接入与管道 ----
@app.post("/api/ingest/csv")
async def api_ingest_csv(
    object_type_id: str = Form(...),
    primary_key: str = Form("id"),
    file: UploadFile = File(...),
    user: str = Depends(get_current_user),
):
    data = await file.read()
    try:
        return ingestion.ingest_csv(object_type_id, primary_key, data, file.filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/transform")
def api_transform(req: dict, user: str = Depends(get_current_user)):
    try:
        return ingestion.transform_from_sql(req["name"], req["sql"])
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- M7 应用构建（Form / Dashboard / View / Workflow + 版本对比） ----
@app.get("/api/apps")
def api_list_apps(user: str = Depends(get_current_user)):
    return app_platform.list_apps()


@app.post("/api/apps")
def api_create_app(req: dict, user: str = Depends(get_current_user)):
    try:
        res = app_platform.create_app(req)
        app_platform.save_version(req["id"])
        metadata.log_activity("app", f"创建应用 {req['id']}（{req.get('type')}）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/apps/{aid}")
def api_get_app(aid: str, user: str = Depends(get_current_user)):
    app = app_platform.get_app(aid)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app


@app.delete("/api/apps/{aid}")
def api_delete_app(aid: str, user: str = Depends(get_current_user)):
    app_platform.delete_app(aid)
    metadata.log_activity("app", f"删除应用 {aid}")
    return {"ok": True}


@app.get("/api/apps/{aid}/data")
def api_app_data(aid: str, user: str = Depends(get_current_user)):
    app = app_platform.get_app(aid)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app_platform.app_data(app)


@app.post("/api/apps/{aid}/run")
def api_app_run(aid: str, user: str = Depends(get_current_user)):
    app = app_platform.get_app(aid)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return app_platform.run_workflow(app)


@app.get("/api/apps/{aid}/render", response_class=HTMLResponse)
def api_app_render(aid: str, user: str = Depends(get_current_user)):
    app = app_platform.get_app(aid)
    if not app:
        raise HTTPException(status_code=404, detail="应用不存在")
    return HTMLResponse(app_platform.render_app(app))


@app.post("/api/apps/{aid}/versions")
def api_app_save_version(aid: str, user: str = Depends(get_current_user)):
    return app_platform.save_version(aid)


@app.get("/api/apps/{aid}/versions")
def api_app_versions(aid: str, user: str = Depends(get_current_user)):
    return app_platform.list_versions(aid)


@app.get("/api/apps/{aid}/compare")
def api_app_compare(aid: str, v1: int, v2: int, user: str = Depends(get_current_user)):
    try:
        return app_platform.compare_versions(aid, v1, v2)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- M8 安全与治理（扫描 / 审批 / 留存 / 标记） ----
@app.post("/api/security/scan")
def api_scan(req: dict, user: str = Depends(get_current_user)):
    if not metadata.can_access(user, req.get("object_type", ""), "read"):
        raise HTTPException(status_code=403, detail="无权访问该对象类型")
    try:
        res = security_platform.scan_object_type(req["object_type"])
        metadata.log_activity("security", f"敏感数据扫描 {req['object_type']}：{len(res['matches'])} 类命中")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/security/scans")
def api_scans(object_type: str = "", user: str = Depends(get_current_user)):
    return security_platform.list_scans(object_type)


@app.post("/api/security/approvals")
def api_approval_create(req: dict, user: str = Depends(get_current_user)):
    try:
        res = security_platform.create_approval(
            user, req.get("object_type", ""), req.get("action_id", ""), req.get("params") or {}, req.get("note", "")
        )
        metadata.log_activity("approval", f"{user} 提交审批：{req.get('action_id')}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/security/approvals")
def api_approval_list(status: str = "", user: str = Depends(get_current_user)):
    require_admin(user)
    return security_platform.list_approvals(status)


@app.post("/api/security/approvals/{aid}/decide")
def api_approval_decide(aid: int, req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = security_platform.decide_approval(aid, user, bool(req.get("approve", False)))
        metadata.log_activity("approval", f"审批 #{aid} → {res['status']}（{user}）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/security/retention")
def api_retention_list(user: str = Depends(get_current_user)):
    require_admin(user)
    return security_platform.list_retention()


@app.put("/api/security/retention")
def api_retention_set(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        security_platform.set_retention(req["object_type"], req["days"])
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/security/markings")
def api_markings(object_type: str = "", user: str = Depends(get_current_user)):
    return security_platform.list_markings(object_type)


@app.post("/api/security/markings/assign")
def api_marking_assign(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        return security_platform.assign_marking(req["object_type"], req["marking"], bool(req.get("remove", False)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- M9 模型管理（Catalog / Studio / 建模目标） ----
@app.get("/api/models")
def api_model_catalog(user: str = Depends(get_current_user)):
    return aip_platform.catalog()


@app.get("/api/models/objectives")
def api_objectives(user: str = Depends(get_current_user)):
    return aip_platform.list_objectives()


@app.post("/api/models/objectives")
def api_objective_create(req: dict, user: str = Depends(get_current_user)):
    if not req.get("id") or not req.get("name") or not req.get("model_id"):
        raise HTTPException(status_code=400, detail="id / name / model_id 必填")
    try:
        res = aip_platform.create_objective(req["id"], req["name"], req["model_id"], req.get("description", ""))
        metadata.log_activity("model", f"创建建模目标 {req['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/models/{mid}")
def api_model_detail(mid: str, user: str = Depends(get_current_user)):
    try:
        return aip_platform.model_detail(mid)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/models/{mid}/versions")
def api_model_version(mid: str, req: dict, user: str = Depends(get_current_user)):
    try:
        res = aip_platform.add_model_version(mid, req.get("note", ""))
        metadata.log_activity("model", f"提交模型版本 {mid} v{res['version']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/models/{mid}/train")
def api_model_train(mid: str, user: str = Depends(get_current_user)):
    try:
        res = aip_platform.submit_training(mid)
        metadata.log_activity("model", f"提交训练任务 {mid}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- M10 可观测性 / 血缘 ----
@app.get("/api/lineage")
def api_lineage(user: str = Depends(get_current_user)):
    return observability.lineage_graph()


@app.get("/api/lineage/{type_id}")
def api_lineage_for(type_id: str, user: str = Depends(get_current_user)):
    return observability.lineage_for(type_id)


@app.get("/api/monitors")
def api_monitors(user: str = Depends(get_current_user)):
    require_admin(user)
    return observability.list_monitors()


@app.post("/api/monitors")
def api_monitor_create(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        return observability.create_monitor(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/monitors/{mid}")
def api_monitor_delete(mid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    observability.delete_monitor(mid)
    return {"ok": True}


@app.post("/api/monitors/{mid}/check")
def api_monitor_check(mid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        return observability.check_monitor(mid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/monitors/check-all")
def api_monitor_check_all(user: str = Depends(get_current_user)):
    require_admin(user)
    return observability.check_all_monitors()


# ---- M11 数据平面（SQL 工作台 / 时空 / 媒体 / 引擎） ----
@app.post("/api/sql")
def api_sql(req: dict, user: str = Depends(get_current_user)):
    try:
        return data_plane.run_sql(req.get("sql", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/geo/near")
def api_geo_near(req: dict, user: str = Depends(get_current_user)):
    try:
        return data_plane.geo_near(req.get("object_type", ""), float(req.get("lat", 0)), float(req.get("lng", 0)),
                                   float(req.get("radius_km", 50)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/media")
def api_media_list(user: str = Depends(get_current_user)):
    return data_plane.list_media()


@app.post("/api/media/upload")
async def api_media_upload(file: UploadFile = File(...), user: str = Depends(get_current_user)):
    data = await file.read()
    res = data_plane.save_media(file.filename, data)
    metadata.log_activity("media", f"上传媒体 {res['name']}（{res['size']}B）")
    return res


@app.get("/api/media/{name}")
def api_media_get(name: str, user: str = Depends(get_current_user)):
    from pathlib import Path
    p = data_plane.MEDIA_DIR / Path(name).name
    if not p.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(str(p))


@app.get("/api/data-plane/engines")
def api_engines(user: str = Depends(get_current_user)):
    return data_plane.engines()


# ---- M12 开发者控制台（API 令牌） ----
@app.get("/api/dev/tokens")
def api_dev_tokens(user: str = Depends(get_current_user)):
    require_admin(user)
    return dev.list_tokens()


@app.post("/api/dev/tokens")
def api_dev_token_create(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    res = dev.create_token(user, req.get("label", ""))
    metadata.log_activity("dev", f"签发 API 令牌（{res['label']}）")
    return res


@app.delete("/api/dev/tokens/{tid}")
def api_dev_token_revoke(tid: int, user: str = Depends(get_current_user)):
    require_admin(user)
    dev.revoke_token(tid)
    return {"ok": True}


# ---- 自定义 API 端点（custom-endpoints） ----
@app.get("/api/endpoints")
def api_endpoints(user: str = Depends(get_current_user)):
    return data_plane.list_endpoints()


@app.post("/api/endpoints")
def api_endpoint_create(req: dict, user: str = Depends(get_current_user)):
    try:
        res = data_plane.create_endpoint(req)
        ep = next((e for e in data_plane.list_endpoints() if e["id"] == req["id"]), None)
        if ep:
            data_plane.register_endpoint(app, ep)
        metadata.log_activity("dev", f"创建自定义端点 {req['path']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/endpoints/{eid}")
def api_endpoint_delete(eid: str, user: str = Depends(get_current_user)):
    data_plane.delete_endpoint(eid)
    return {"ok": True}


# ---- 管道运行历史 + 数据快照（32266587 / 12378379） ----
@app.get("/api/pipelines/{pid}/runs")
def api_pipeline_runs(pid: str, user: str = Depends(get_current_user)):
    return pipelines.list_runs(pid)


@app.get("/api/pipelines/{pid}/snapshots")
def api_pipeline_snapshots(pid: str, user: str = Depends(get_current_user)):
    return pipelines.list_snapshots(pid)


@app.post("/api/pipelines/{pid}/snapshots/{sid}/restore")
def api_pipeline_snapshot_restore(pid: str, sid: int, user: str = Depends(get_current_user)):
    try:
        return pipelines.restore_snapshot(pid, sid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- 静态前端 (SPA) ----
ASSETS_DIR = config.FRONTEND_DIR / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR), html=True), name="assets")


@app.get("/")
def index():
    return FileResponse(str(config.FRONTEND_DIR / "index.html"))


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api"):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(str(config.FRONTEND_DIR / "index.html"))
