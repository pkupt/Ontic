"""FastAPI 应用入口：鉴权 + Ontology API + 静态前端(SPA)。

本地运行： cd backend && uvicorn app.main:app --reload --port 8000
Docker：     docker compose up  ->  http://localhost:8080
"""
from fastapi import FastAPI, Depends, HTTPException, Request, File, UploadFile, Form
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response
import json
import os
import warnings
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from . import config, db, security, models
from .ontology import metadata, resolver, actions, osdk
from . import ingestion, app_builder, aip, connectors, pipelines, functions, aip_platform
from . import app_platform, security_platform, observability
from . import data_plane, dev, versioning, time_series, marketplace, transforms_python
from . import chatbots, contour, ttl, knowledge, projects
from .seed import seed

app = FastAPI(title="Ontic", version="0.1.0")

# ---- P1-10 可观测性：请求指标 + 结构化访问日志 ----
_METRICS = {"requests": 0, "errors": 0, "status": {}, "latency_ms": [], "started": __import__("time").time()}
import time as _time
import datetime as _dt


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    t0 = _time.time()
    try:
        resp = await call_next(request)
    except Exception:
        _METRICS["errors"] += 1
        raise
    dur = (_time.time() - t0) * 1000
    _METRICS["requests"] += 1
    _METRICS["status"][str(resp.status_code)] = _METRICS["status"].get(str(resp.status_code), 0) + 1
    _METRICS["latency_ms"].append(dur)
    if len(_METRICS["latency_ms"]) > 5000:
        _METRICS["latency_ms"] = _METRICS["latency_ms"][-1000:]
    # 结构化访问日志（JSON 行）
    print(f'{{"ts":"{_dt.datetime.utcnow().isoformat()}Z","level":"info","event":"http","method":"{request.method}","path":"{request.url.path}","status":{resp.status_code},"dur_ms":{dur:.1f}}}')
    return resp

# CORS 白名单：默认仅本机，可通过 ONTIC_CORS_ORIGINS 配置（逗号分隔）
_default_origins = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000"
_cors_env = os.environ.get("ONTIC_CORS_ORIGINS", _default_origins)
_allow_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
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
    # 安全自检：默认密钥/弱密码告警（不阻断启动，仅警告）
    if config.SECRET_KEY in ("dev-secret-change-me-in-prod", "change-me"):
        warnings.warn(
            "ONTIC_SECRET_KEY 使用默认值！生产环境必须设置环境变量 ONTIC_SECRET_KEY 为强随机值，"
            "否则 JWT 可被伪造。",
            stacklevel=2,
        )
    if config.ADMIN_PASSWORD in ("admin123", "password", "admin"):
        warnings.warn(
            "管理员使用默认弱密码！生产环境必须设置 ONTIC_ADMIN_PASSWORD 为强密码。",
            stacklevel=2,
        )
    seed()
    aip_platform.seed_models()
    time_series.init_ts_table()
    transforms_python.init_table()
    chatbots.init_table()
    connectors.init_configs_table()
    contour.init_table()
    ttl.init_table()
    knowledge.init_table()
    for ep in data_plane.list_endpoints():
        try:
            data_plane.register_endpoint(app, ep)
        except Exception:
            pass


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "ontic"}


@app.get("/api/health/deep")
def api_health_deep(user: str = Depends(get_current_user)):
    """B3 深度健康检查：duckdb / sqlite / 媒体目录 / 磁盘 / 活动。"""
    import datetime
    import shutil
    checks = []
    try:
        dconn = db.get_duckdb()
        n = dconn.execute("SELECT count(*) FROM duckdb_tables()").fetchone()[0]
        dconn.close()
        checks.append({"name": "duckdb", "status": "ok", "detail": f"{n} 张表"})
    except Exception as e:
        checks.append({"name": "duckdb", "status": "error", "detail": str(e)})
    try:
        conn = db.get_metadata_conn()
        conn.execute("SELECT 1")
        conn.close()
        checks.append({"name": "sqlite", "status": "ok", "detail": "可读写"})
    except Exception as e:
        checks.append({"name": "sqlite", "status": "error", "detail": str(e)})
    try:
        data_plane.MEDIA_DIR.mkdir(parents=True, exist_ok=True)
        t = data_plane.MEDIA_DIR / ".probe"
        t.write_text("ok")
        try:
            t.unlink()
        except Exception:
            pass  # 写能力已证明；沙箱回收站限制不影响可用性
        checks.append({"name": "media-dir", "status": "ok", "detail": str(data_plane.MEDIA_DIR)})
    except Exception as e:
        checks.append({"name": "media-dir", "status": "error", "detail": str(e)})
    try:
        free = shutil.disk_usage(config.DATA_DIR).free // (1024 * 1024)
        checks.append({"name": "disk", "status": "ok" if free > 50 else "warn", "detail": f"{free} MB 可用"})
    except Exception as e:
        checks.append({"name": "disk", "status": "error", "detail": str(e)})
    try:
        conn = db.get_metadata_conn()
        row = conn.execute("SELECT max(ts) AS t FROM activity").fetchone()
        conn.close()
        checks.append({"name": "activity", "status": "ok", "detail": row["t"] or "暂无活动"})
    except Exception as e:
        checks.append({"name": "activity", "status": "error", "detail": str(e)})
    overall = "ok" if all(c["status"] == "ok" for c in checks) else ("warn" if any(c["status"] == "warn" for c in checks) else "error")
    return {"status": overall, "ts": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "checks": checks}


@app.get("/api/activity")
def api_activity(limit: int = 50, user: str = Depends(get_current_user)):
    """活动 / 通知中心（对齐 Foundry 通知中心 74849331；M10 审计基础）。"""
    return metadata.list_activity(limit=min(limit, 200))


# ---- 登录限流（P0-3 防爆破：同 IP 5 次失败锁 15 分钟，内存滑动窗口） ----
_LOGIN_FAILS = {}  # key -> [fail_count, locked_until_ts]


def _login_key(req) -> str:
    try:
        return req.client.host if req.client else "unknown"
    except Exception:
        return "unknown"


def _login_throttle(key: str):
    import time
    now = time.time()
    entry = _LOGIN_FAILS.get(key)
    if entry and entry[1] > now:
        left = int(entry[1] - now)
        raise HTTPException(status_code=429, detail=f"尝试过于频繁，请 {left} 秒后重试")
    return now


@app.get("/api/metrics")
def api_metrics(user: str = Depends(get_current_user)):
    """Prometheus 文本格式指标（P1-10）。"""
    import statistics
    lat = _METRICS["latency_ms"]
    lines = [
        "# HELP ontic_http_requests_total 总请求数",
        "# TYPE ontic_http_requests_total counter",
        f"ontic_http_requests_total {_METRICS['requests']}",
        "# HELP ontic_http_errors_total 5xx/异常数",
        "# TYPE ontic_http_errors_total counter",
        f"ontic_http_errors_total {_METRICS['errors']}",
        "# HELP ontic_http_latency_ms 请求耗时毫秒",
        "# TYPE ontic_http_latency_ms gauge",
        f"ontic_http_latency_ms_p50 {statistics.median(lat) if lat else 0}",
        f"ontic_http_latency_ms_p95 {sorted(lat)[int(len(lat)*0.95)-1] if lat else 0}",
        f"ontic_http_latency_ms_max {max(lat) if lat else 0}",
        f"ontic_uptime_seconds {int(_time.time() - _METRICS['started'])}",
    ]
    for code, n in sorted(_METRICS["status"].items()):
        lines.append(f'ontic_http_status{{code="{code}"}} {n}')
    return Response("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.post("/api/auth/login", response_model=models.TokenResponse)
def login(req: models.LoginRequest, request: Request = None):
    key = _login_key(request)
    _login_throttle(key)
    conn = db.get_metadata_conn()
    row = conn.execute(
        "SELECT password_hash FROM users WHERE username=?", (req.username,)
    ).fetchone()
    conn.close()
    if not row or not security.verify_password(req.password, row["password_hash"]):
        import time
        cnt = _LOGIN_FAILS.get(key, [0, 0])
        cnt[0] += 1
        if cnt[0] >= 5:
            cnt[1] = time.time() + 15 * 60
            cnt[0] = 0
        _LOGIN_FAILS[key] = cnt
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    _LOGIN_FAILS.pop(key, None)
    return models.TokenResponse(access_token=security.create_access_token(req.username))


@app.get("/api/me", response_model=models.UserOut)
def me(user: str = Depends(get_current_user)):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT role, password_hash FROM users WHERE username=?", (user,)).fetchone()
    conn.close()
    # 首启安全提示：admin 仍用默认密码
    default_pw = user == config.ADMIN_USER and security.verify_password(config.ADMIN_PASSWORD, row["password_hash"])
    return models.UserOut(username=user, role=row["role"], default_pw=default_pw)


@app.post("/api/auth/change-password")
def api_change_password(req: dict, user: str = Depends(get_current_user)):
    """用户修改自己的密码（需旧密码）。"""
    old = req.get("old_password") or ""
    new = req.get("new_password") or ""
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT password_hash FROM users WHERE username=?", (user,)).fetchone()
    conn.close()
    if not row or not security.verify_password(old, row["password_hash"]):
        raise HTTPException(status_code=400, detail="旧密码不正确")
    err = security.validate_password(new)
    if err:
        raise HTTPException(status_code=400, detail=err)
    metadata.set_password(user, new)
    metadata.log_activity("user", f"修改密码 {user}")
    return {"ok": True}


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
    err = security.validate_password(pw)
    if err:
        raise HTTPException(status_code=400, detail=err)
    metadata.create_user(uname, pw, role)
    metadata.log_activity("user", f"创建用户 {uname}（{role}）")
    return {"ok": True, "username": uname, "role": role}


@app.post("/api/admin/users/{username}/password")
def api_admin_reset_password(username: str, req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    new = req.get("password") or ""
    err = security.validate_password(new)
    if err:
        raise HTTPException(status_code=400, detail=err)
    try:
        metadata.set_password(username, new)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    metadata.log_activity("user", f"管理员重置密码 {username}")
    metadata.audit(user, "reset_password", username)
    return {"ok": True}


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
    metadata.audit(user, "set_role", username, req.get("role"))
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
    metadata.audit(user, "grant", f"{req['username']} → {req['object_type']}", req.get("level", "read"))
    return {"ok": True}


@app.delete("/api/admin/grants")
def api_revoke(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    metadata.revoke_grant(req["username"], req["object_type"])
    metadata.audit(user, "revoke", f"{req['username']} → {req['object_type']}")
    return {"ok": True}


@app.get("/api/audit")
def api_audit(limit: int = 200, user: str = Depends(get_current_user)):
    require_admin(user)
    return metadata.list_audit(limit)


@app.get("/api/ontology/object-types")
def api_list_types(project: str = None, user: str = Depends(get_current_user)):
    return metadata.list_object_types_for_user(user, project)


# ---- 多项目/空间（Foundry projects 概念） ----
@app.get("/api/projects")
def api_projects(user: str = Depends(get_current_user)):
    return projects.list_all()


@app.post("/api/projects")
def api_project_create(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = projects.create(req)
        metadata.log_activity("project", f"创建项目 {res['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/projects/{pid}")
def api_project_delete(pid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = projects.delete(pid)
        metadata.log_activity("project", f"删除项目 {pid}（资源归回默认空间）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
    # C1 风险动作审批：标记为需审批的动作，非 admin 执行自动转审批队列
    if act.get("needs_approval") and metadata.user_role(user) != "admin":
        res = security_platform.create_approval(
            user, act["object_type"], action_id, req.params, note="风险动作自动转审批"
        )
        metadata.log_activity("approval", f"风险动作 {action_id} 自动转审批（{user}）")
        return models.ActionExecuteResponse(detail={"pending_approval": res["approval_id"], "status": "pending"})
    try:
        detail = actions.execute_action(action_id, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    _oid = req.params.get("id") if isinstance(req.params, dict) else None
    if _oid is not None:
        metadata.log_activity("action", f"执行动作 {action_id}（{act['object_type']}#{_oid}）")
    else:
        metadata.log_activity("action", f"执行动作 {action_id}（{act['object_type']}）")
    return models.ActionExecuteResponse(detail=detail)


@app.post("/api/ontology/actions/{action_id}/approval-config")
def api_action_approval(action_id: str, req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        return metadata.set_action_approval(action_id, bool(req.get("needs_approval", False)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# ---- D2 导出 / 导入 / 克隆 ----
@app.get("/api/ontology/object-types/{type_id}/export")
def api_type_export(type_id: str, user: str = Depends(get_current_user)):
    try:
        return ingestion.export_object_type(type_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ontology/object-types/import")
def api_type_import(req: dict, user: str = Depends(get_current_user)):
    try:
        res = ingestion.import_object_type(req.get("definition", {}), req.get("rows"))
        metadata.log_activity("type", f"导入对象类型 {req.get('definition',{}).get('id')}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ontology/object-types/{type_id}/clone")
def api_type_clone(type_id: str, req: dict, user: str = Depends(get_current_user)):
    try:
        return ingestion.clone_object_type(type_id, req.get("new_id", ""), bool(req.get("include_data", True)))
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
    # 契约校验：parameters 必须是数组（否则 json.dumps 双重序列化导致执行时崩溃）
    if not isinstance(params, list):
        raise HTTPException(status_code=400, detail="parameters 须为字段定义数组")
    metadata.create_action({
        "id": req["id"],
        "name": req.get("name", req["id"]),
        "description": req.get("description", ""),
        "object_type": req["object_type"],
        "operation": req["operation"],
        "parameters": json.dumps(params),
    })
    return {"ok": True, "id": req["id"]}


@app.delete("/api/ontology/actions/{action_id}")
def api_delete_action(action_id: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = metadata.delete_action(action_id)
        metadata.log_activity("ontology", f"删除动作 {action_id}")
        metadata.audit(user, "delete_action", action_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/ontology/link-types/{link_id}")
def api_delete_link(link_id: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = metadata.delete_link(link_id)
        metadata.log_activity("ontology", f"删除链接 {link_id}")
        metadata.audit(user, "delete_link", link_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/ontology/object-types/{type_id}")
def api_delete_type(type_id: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = metadata.delete_object_type(type_id)
        metadata.log_activity("ontology", f"删除对象类型 {type_id}（含动作/链接/授权/数据表）")
        metadata.audit(user, "delete_object_type", type_id)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/ontology/object-types/{type_id}/clear")
def api_clear_type(type_id: str, user: str = Depends(get_current_user)):
    require_admin(user)
    ot = metadata.get_object_type(type_id)
    if not ot:
        raise HTTPException(status_code=400, detail="对象类型不存在")
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'DELETE FROM "{ot["backing_table"]}"')
    finally:
        dconn.close()
    metadata.log_activity("ontology", f"清空对象类型数据 {type_id}")
    return {"ok": True, "cleared": type_id}


# ---- M4 连接器框架 ----
@app.get("/api/connectors")
def api_connectors(user: str = Depends(get_current_user)):
    return connectors.list_connectors()


# ---- I1 Contour 分析画布 ----
@app.get("/api/analyses")
def api_analyses(user: str = Depends(get_current_user)):
    return contour.list_all()


@app.post("/api/analyses")
def api_analysis_create(req: dict, user: str = Depends(get_current_user)):
    try:
        res = contour.create(req)
        metadata.log_activity("analysis", f"创建分析 {res['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/analyses/{aid}")
def api_analysis_get(aid: str, user: str = Depends(get_current_user)):
    a = contour.get(aid)
    if not a:
        raise HTTPException(status_code=404, detail="分析不存在")
    return a


@app.delete("/api/analyses/{aid}")
def api_analysis_delete(aid: str, user: str = Depends(get_current_user)):
    contour.delete(aid)
    return {"ok": True}


@app.post("/api/analyses/{aid}/run")
def api_analysis_run(aid: str, req: dict, user: str = Depends(get_current_user)):
    try:
        return contour.run(aid, run_params=req.get("params") or {})
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/analyses/{aid}/save-as-type")
def api_analysis_save_as_type(aid: str, req: dict, user: str = Depends(get_current_user)):
    try:
        return contour.save_as_type(aid, req.get("new_type_id", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- J1 数据生命周期 TTL（data-lifetime 对齐） ----
@app.get("/api/lifetime/policies")
def api_ttl_policies(user: str = Depends(get_current_user)):
    return ttl.list_all()


@app.post("/api/lifetime/policies")
def api_ttl_policy_create(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = ttl.create(req)
        metadata.log_activity("lifetime", f"创建生命周期策略 {res['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/lifetime/policies/{pid}")
def api_ttl_policy_delete(pid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    ttl.delete(pid)
    return {"ok": True}


@app.post("/api/lifetime/apply-all")
def api_ttl_apply_all(user: str = Depends(get_current_user)):
    require_admin(user)
    return ttl.apply_all()


# ---- H4 知识库（RAG 检索上下文） ----
@app.get("/api/knowledge")
def api_knowledge(user: str = Depends(get_current_user)):
    return knowledge.list_all()


@app.post("/api/knowledge")
def api_knowledge_add(req: dict, user: str = Depends(get_current_user)):
    try:
        res = knowledge.add(req)
        metadata.log_activity("aip", f"添加知识条目 {res['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/knowledge/{kid}")
def api_knowledge_delete(kid: str, user: str = Depends(get_current_user)):
    knowledge.delete(kid)
    return {"ok": True}


@app.post("/api/knowledge/search")
def api_knowledge_search(req: dict, user: str = Depends(get_current_user)):
    return knowledge.search(req.get("query", ""), int(req.get("top_k", 3)), req.get("tags"))


# ---- J3 连接配置（凭据加密落库） ----
@app.get("/api/connectors/configs")
def api_connector_configs(user: str = Depends(get_current_user)):
    require_admin(user)
    return connectors.list_configs()


@app.post("/api/connectors/configs")
def api_connector_config_save(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = connectors.save_config(req)
        metadata.log_activity("ingest", f"保存连接配置 {res['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/connectors/configs/{cid}")
def api_connector_config_delete(cid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    connectors.delete_config(cid)
    return {"ok": True}


@app.post("/api/connectors/configs/{cid}/run")
def api_connector_config_run(cid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = connectors.run_config(cid)
        metadata.log_activity("ingest", f"运行连接配置 {cid}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
def api_list_pipelines(project: str = None, user: str = Depends(get_current_user)):
    return metadata.list_pipelines(project)


@app.delete("/api/pipelines/{pid}")
def api_delete_pipeline(pid: str, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        res = metadata.delete_pipeline(pid)
        metadata.log_activity("pipeline", f"删除管道 {pid}")
        metadata.audit(user, "delete_pipeline", pid)
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# ---- A1 AIP 会话（Threads） ----
@app.get("/api/aip/threads")
def api_threads(user: str = Depends(get_current_user)):
    return aip_platform.list_threads(user)


# ---- H1 可配置 Chatbot（chatbot-studio 对齐） ----
@app.get("/api/chatbots")
def api_chatbots(user: str = Depends(get_current_user)):
    return chatbots.list_all()


@app.post("/api/chatbots")
def api_chatbot_create(req: dict, user: str = Depends(get_current_user)):
    try:
        res = chatbots.create(req)
        metadata.log_activity("aip", f"创建 Chatbot {res['id']}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/chatbots/{cid}")
def api_chatbot_get(cid: str, user: str = Depends(get_current_user)):
    cb = chatbots.get(cid)
    if not cb:
        raise HTTPException(status_code=404, detail="Chatbot 不存在")
    return cb


@app.get("/api/chatbots/{cid}/messages")
def api_chatbot_messages(cid: str, user: str = Depends(get_current_user)):
    return chatbots.list_messages(cid)


@app.delete("/api/chatbots/{cid}")
def api_chatbot_delete(cid: str, user: str = Depends(get_current_user)):
    chatbots.delete(cid)
    return {"ok": True}


@app.post("/api/chatbots/{cid}/chat")
def api_chatbot_chat(cid: str, req: dict, user: str = Depends(get_current_user)):
    try:
        return chatbots.chat(cid, req.get("message", ""), req.get("params"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/aip/threads")
def api_thread_create(req: dict, user: str = Depends(get_current_user)):
    return aip_platform.create_thread(user, req.get("name", ""))


@app.get("/api/aip/threads/{tid}/messages")
def api_thread_messages(tid: int, user: str = Depends(get_current_user)):
    try:
        return aip_platform.get_messages(tid, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/aip/threads/{tid}/chat")
def api_thread_chat(tid: int, req: dict, user: str = Depends(get_current_user)):
    msg = req.get("message", "")
    if not msg:
        raise HTTPException(status_code=400, detail="message 必填")
    try:
        return aip_platform.thread_chat(tid, user, msg)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/aip/threads/{tid}/rename")
def api_thread_rename(tid: int, req: dict, user: str = Depends(get_current_user)):
    try:
        return aip_platform.rename_thread(tid, user, req.get("name", "新会话"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/aip/threads/{tid}")
def api_thread_delete(tid: int, user: str = Depends(get_current_user)):
    try:
        return aip_platform.delete_thread(tid, user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
def api_list_apps(project: str = None, user: str = Depends(get_current_user)):
    return app_platform.list_apps(project)


@app.post("/api/apps")
def api_create_app(req: dict, user: str = Depends(get_current_user)):
    try:
        res = app_platform.create_app(req)
        app_platform.save_version(req["id"])
        metadata.log_activity("app", f"创建应用 {req['id']}（{req.get('type')}）")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/apps/{aid}/save")
def api_update_app(aid: str, req: dict, user: str = Depends(get_current_user)):
    """应用编辑保存：更新名称/描述/配置 + 生成版本快照。"""
    try:
        res = app_platform.update_app(aid, req)
        metadata.log_activity("app", f"编辑保存应用 {aid}（v{res.get('version')}）")
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
    days = req.get("days")
    if days is None or req.get("object_type") is None:
        raise HTTPException(status_code=400, detail="object_type 与 days 必填")
    try:
        security_platform.set_retention(req["object_type"], days)
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


@app.get("/api/lineage/tables")
def api_lineage_tables(user: str = Depends(get_current_user)):
    return observability.lineage_tables()


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


@app.get("/api/automation/events")
def api_automation_events(user: str = Depends(get_current_user)):
    return observability.list_automation_events()


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


@app.delete("/api/media/{name}")
def api_media_delete(name: str, user: str = Depends(get_current_user)):
    try:
        res = data_plane.delete_media(name)
        metadata.log_activity("media", f"删除媒体 {name}")
        return res
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


# ---- 数据版本控制：检查点 / 分支 ----
@app.get("/api/checkpoints")
def api_checkpoints(object_type: str = "", user: str = Depends(get_current_user)):
    return versioning.list_checkpoints(object_type)


@app.post("/api/checkpoints")
def api_checkpoint_create(req: dict, user: str = Depends(get_current_user)):
    try:
        return versioning.create_checkpoint(req.get("object_type", ""), req.get("label", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/checkpoints/{cid}/restore")
def api_checkpoint_restore(cid: int, user: str = Depends(get_current_user)):
    try:
        return versioning.restore_checkpoint(cid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/checkpoints/{cid}/diff")
def api_checkpoint_diff(cid: int, user: str = Depends(get_current_user)):
    try:
        return versioning.checkpoint_diff(cid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/checkpoints/{cid}")
def api_checkpoint_delete(cid: int, user: str = Depends(get_current_user)):
    try:
        return versioning.delete_checkpoint(cid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/branches")
def api_branches(object_type: str = "", user: str = Depends(get_current_user)):
    return versioning.list_branches(object_type)


@app.post("/api/branches")
def api_branch_create(req: dict, user: str = Depends(get_current_user)):
    try:
        return versioning.create_branch(req.get("object_type", ""), req.get("name", ""), req.get("base"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/branches/{bid}/apply")
def api_branch_apply(bid: int, user: str = Depends(get_current_user)):
    br = versioning.get_branch(bid)
    if not br:
        raise HTTPException(status_code=404, detail="分支不存在")
    # C2 分支保护：受保护分支 apply 需审批（非 admin）
    if br.get("protected") and metadata.user_role(user) != "admin":
        res = security_platform.create_approval(user, br["object_type"], f"__branch_apply__:{bid}",
                                                {}, note=f"应用分支 {br['name']}（受保护）")
        metadata.log_activity("approval", f"受保护分支 {br['name']} apply 转审批（{user}）")
        return {"pending_approval": res["approval_id"], "status": "pending"}
    try:
        return versioning.apply_branch(bid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/branches/{bid}/protect")
def api_branch_protect(bid: int, req: dict, user: str = Depends(get_current_user)):
    require_admin(user)
    try:
        return versioning.set_branch_protection(bid, bool(req.get("protect", False)))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/branches/{bid}")
def api_branch_delete(bid: int, user: str = Depends(get_current_user)):
    try:
        return versioning.delete_branch(bid)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- B1 时间序列 ----
@app.get("/api/ts/series")
def api_ts_series(user: str = Depends(get_current_user)):
    return time_series.list_series()


@app.delete("/api/ts/series/{series_id}")
def api_ts_delete_series(series_id: str, entity: str = "", user: str = Depends(get_current_user)):
    return time_series.delete_series(series_id, entity)


@app.post("/api/ts/ingest")
def api_ts_ingest(req: dict, user: str = Depends(get_current_user)):
    try:
        return time_series.ingest(req.get("series_id", ""), req.get("entity", ""), req.get("points", []))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/ts/query")
def api_ts_query(series_id: str, entity: str = "", from_ts: str = "", to_ts: str = "",
                 agg: str = "", bucket: str = "", user: str = Depends(get_current_user)):
    try:
        return time_series.query(series_id, entity, from_ts, to_ts, agg, bucket)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- C3 市场安装包 ----
@app.get("/api/marketplace/packages")
def api_marketplace(user: str = Depends(get_current_user)):
    return marketplace.catalog()


@app.post("/api/marketplace/install")
def api_marketplace_install(req: dict, user: str = Depends(get_current_user)):
    try:
        return marketplace.install(req.get("package_id", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/marketplace/uninstall")
def api_marketplace_uninstall(req: dict, user: str = Depends(get_current_user)):
    try:
        return marketplace.uninstall(req.get("package_id", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---- D1 Python Transforms ----
@app.get("/api/transforms/python")
def api_py_transforms(user: str = Depends(get_current_user)):
    return transforms_python.list_transforms()


@app.post("/api/transforms/python")
def api_py_transform_create(req: dict, user: str = Depends(get_current_user)):
    require_admin(user)  # RCE 风险：仅 admin 可注册 Python 转换
    try:
        return transforms_python.register(req.get("name", ""), req.get("code", ""), req.get("description", ""))
    except (ValueError, SyntaxError) as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/transforms/python/{name}")
def api_py_transform_delete(name: str, user: str = Depends(get_current_user)):
    require_admin(user)
    transforms_python.delete_transform(name)
    return {"ok": True}


@app.post("/api/transforms/python/{name}/run")
def api_py_transform_run(name: str, req: dict, user: str = Depends(get_current_user)):
    require_admin(user)  # 执行用户代码，仅 admin
    try:
        return transforms_python.run_transform(name, req.get("input", ""), req.get("output", ""), req.get("object_type", ""))
    except Exception as e:  # 沙箱拦截（NameError/AttributeError 等）统一返回 400
        raise HTTPException(status_code=400, detail=f"转换执行失败: {e}")


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
