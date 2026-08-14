"""M6 AIP 平台层：模型注册 / 用量追踪 / 评估套件 / 模型对比 / 服务日志。

对齐 Foundry AIP 原型：
  - 模型用量看板（21065415）：按模型的请求数/令牌数与成功率，支持时间序列。
  - 建模目标与评估套件（36581134 / 68207144 / 71082048）：测试用例 + 评估器（用
    规则规划器实际作答，期望子串匹配判定 pass）。
  - 模型对比 Playground（84211570）：两个模型并行推理，左右对比输出。
  - 服务日志（18802464）：记录每次调用的结构化 payload，可回放查看。
"""
import json
import datetime

from . import db
from . import aip

_LOCAL_MODEL = "ontic-rule-planner"
_CLOUD_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "OpenAI (placeholder)", "kind": "llm"},
    {"id": "claude-3-sonnet", "name": "Claude 3 Sonnet", "provider": "Anthropic (placeholder)", "kind": "llm"},
]


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def seed_models():
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR IGNORE INTO models (id, name, provider, kind, status) VALUES (?,?,?,?,?)",
        (_LOCAL_MODEL, "Ontic Rule Planner", "local", "rules", "active"),
    )
    for m in _CLOUD_MODELS:
        conn.execute(
            "INSERT OR IGNORE INTO models (id, name, provider, kind, status) VALUES (?,?,?,?,?)",
            (m["id"], m["name"], m["provider"], m["kind"], "active"),
        )
    conn.commit()
    conn.close()


def list_models():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM models ORDER BY kind, id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_usage(model: str, metric: str, amount: int, success: bool = True, source: str = "", payload: dict = None):
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT INTO model_usage (ts, model, metric, amount, success, source, payload) VALUES (?,?,?,?,?,?,?)",
        (_now(), model, metric, int(amount), 1 if success else 0, source or "", json.dumps(payload or {}, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def get_usage(days: int = 30):
    """用量看板：时间序列（请求/令牌）、汇总、按模型分布。"""
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT ts, model, metric, amount, success FROM model_usage WHERE ts >= datetime('now', ?)",
        (f"-{days} days",),
    ).fetchall()
    conn.close()
    rows = [dict(r) for r in rows]

    by_day = {}
    by_model = {}
    summary = {"requests": 0, "tokens": 0, "success": 0}
    for r in rows:
        day = r["ts"][:10]
        d = by_day.setdefault(day, {"date": day, "requests": 0, "tokens": 0, "success": 0})
        if r["metric"] == "request":
            d["requests"] += 1
            summary["requests"] += 1
            if r["success"]:
                d["success"] += 1
                summary["success"] += 1
        else:
            d["tokens"] += r["amount"]
            summary["tokens"] += r["amount"]
        m = by_model.setdefault(r["model"], {"model": r["model"], "requests": 0, "tokens": 0, "success": 0})
        if r["metric"] == "request":
            m["requests"] += 1
            m["success"] += 1 if r["success"] else 0
        else:
            m["tokens"] += r["amount"]
    return {
        "series": sorted(by_day.values(), key=lambda x: x["date"]),
        "summary": summary,
        "by_model": sorted(by_model.values(), key=lambda x: -x["requests"]),
    }


def service_logs(limit: int = 50, source: str = ""):
    conn = db.get_metadata_conn()
    sql = "SELECT ts, model, metric, amount, success, source, payload FROM model_usage"
    if source:
        sql += " WHERE source=?"
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", (source, limit)).fetchall()
    else:
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"])
        except Exception:
            d["payload"] = {}
        out.append(d)
    return out


# ---- 评估套件（68207144 / 71082048） ----
def create_suite(suite_id: str, name: str, target: str):
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO eval_suites (id, name, target, created) VALUES (?,?,?,?)",
        (suite_id, name, target or suite_id, _now()),
    )
    conn.commit()
    conn.close()


def list_suites():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT id, name, target, created FROM eval_suites ORDER BY created DESC").fetchall()
    cnt = {dict(r)["suite_id"]: dict(r)["n"] for r in conn.execute(
        "SELECT suite_id, count(*) AS n FROM eval_cases GROUP BY suite_id").fetchall()}
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["cases"] = int(cnt.get(d["id"], 0))
        out.append(d)
    return out


def get_suite(suite_id):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM eval_suites WHERE id=?", (suite_id,)).fetchone()
    cases = conn.execute("SELECT id, name, input, expected FROM eval_cases WHERE suite_id=? ORDER BY id", (suite_id,)).fetchall()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["cases"] = [dict(c) for c in cases]
    return d


def add_case(suite_id: str, name: str, input_text: str, expected: str):
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT INTO eval_cases (suite_id, name, input, expected) VALUES (?,?,?,?)",
        (suite_id, name, input_text, expected),
    )
    conn.commit()
    conn.close()


def run_suite(suite_id: str):
    """对套件内每个用例，用规则规划器实际作答，期望子串匹配即 pass。"""
    suite = get_suite(suite_id)
    if not suite:
        raise ValueError("评估套件不存在")
    run_id = None
    results = []
    for c in suite["cases"]:
        try:
            out = aip.chat(c["input"], None)["reply"]
        except Exception as e:
            out = f"error: {e}"
        passed = bool(c["expected"] and c["expected"] in out)
        results.append({"case": c["name"], "input": c["input"], "output": out, "pass": passed})
        conn = db.get_metadata_conn()
        if run_id is None:
            conn.execute("INSERT INTO eval_runs (suite_id, run_ts) VALUES (?,?)", (suite_id, _now()))
            run_id = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
        conn.execute(
            "INSERT INTO eval_results (run_id, case_id, output, pass) VALUES (?,?,?,?)",
            (run_id, c["id"], out, 1 if passed else 0),
        )
        conn.commit()
        conn.close()
    passed_n = sum(1 for r in results if r["pass"])
    return {"suite_id": suite_id, "run_id": run_id, "total": len(results), "passed": passed_n, "results": results}


def suite_results(suite_id: str):
    conn = db.get_metadata_conn()
    run = conn.execute("SELECT id, run_ts FROM eval_runs WHERE suite_id=? ORDER BY id DESC LIMIT 1", (suite_id,)).fetchone()
    if not run:
        conn.close()
        return {"suite_id": suite_id, "has_run": False, "results": []}
    rows = conn.execute(
        """SELECT r.id, c.name, r.output, r.pass FROM eval_results r
           JOIN eval_cases c ON c.id = r.case_id WHERE r.run_id=?""",
        (run["id"],),
    ).fetchall()
    conn.close()
    res = [dict(x) for x in rows]
    return {"suite_id": suite_id, "has_run": True, "run_ts": run["run_ts"],
            "passed": sum(1 for x in res if x["pass"]), "total": len(res), "results": res}


# ---- 文档智能（占位：文本 → 对象类型） ----
def doc_extract(text: str, otid: str):
    """将一段文本按行抽取为结构化对象类型（line_no/content/len）。

    真实实现应接 OCR / LLM 抽取（如从 PDF 提取实体）；此处先打通「文本→本体」
    的管道，作为文档智能的占位与后续接入点。
    """
    from . import ingestion
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    fields = [
        {"key": "line_no", "type": "integer", "title": "行号"},
        {"key": "content", "type": "string", "title": "内容"},
        {"key": "len", "type": "integer", "title": "长度"},
    ]
    ingestion.create_object_type_from_def({
        "id": otid, "name": otid, "description": "文档智能提取（占位）",
        "primary_key": "line_no", "fields": fields,
    })
    dconn = db.get_duckdb()
    try:
        dconn.executemany(f'INSERT INTO "ont__{otid}" VALUES (?,?,?)',
                          [(i + 1, l, len(l)) for i, l in enumerate(lines)])
    finally:
        dconn.close()
    log_usage("ontic-rule-planner", "request", 1, True, source="doc-intel", payload={"lines": len(lines), "type": otid})
    return {"object_type": otid, "lines": len(lines)}


# ---- M9 模型管理（Model Catalog / Studio / 建模目标 36581134） ----
def catalog():
    """模型目录：每个模型带用量汇总（从 model_usage 聚合）。"""
    usage = get_usage(days=365)
    by_model = {m["model"]: m for m in usage["by_model"]}
    models = list_models()
    conn = db.get_metadata_conn()
    ver = {dict(r)["model_id"]: dict(r)["v"] for r in conn.execute(
        "SELECT model_id, MAX(version) AS v FROM model_versions GROUP BY model_id").fetchall()}
    objn = {dict(r)["model_id"]: dict(r)["n"] for r in conn.execute(
        "SELECT model_id, count(*) AS n FROM model_objectives GROUP BY model_id").fetchall()}
    conn.close()
    out = []
    for m in models:
        d = dict(m)
        u = by_model.get(m["id"], {})
        d["requests"] = u.get("requests", 0)
        d["tokens"] = u.get("tokens", 0)
        d["version"] = ver.get(m["id"], 0)
        d["objectives"] = int(objn.get(m["id"], 0))
        out.append(d)
    return out


def model_detail(model_id: str):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("模型不存在")
    m = dict(row)
    versions = [dict(r) for r in conn.execute(
        "SELECT version, note, created FROM model_versions WHERE model_id=? ORDER BY version DESC", (model_id,)).fetchall()]
    objectives = [dict(r) for r in conn.execute(
        "SELECT id, name, description, status FROM model_objectives WHERE model_id=? ORDER BY created DESC", (model_id,)).fetchall()]
    conn.close()
    return {"model": m, "versions": versions, "objectives": objectives}


def add_model_version(model_id: str, note: str = ""):
    conn = db.get_metadata_conn()
    if not conn.execute("SELECT 1 FROM models WHERE id=?", (model_id,)).fetchone():
        conn.close()
        raise ValueError("模型不存在")
    ver = conn.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM model_versions WHERE model_id=?", (model_id,)).fetchone()["v"]
    conn.execute("INSERT INTO model_versions (model_id, version, note, created) VALUES (?,?,?,?)",
                 (model_id, ver, note or "", _now()))
    conn.commit()
    conn.close()
    return {"model_id": model_id, "version": ver}


def submit_training(model_id: str):
    """Model Studio 训练（占位）：本地规则模型无需训练，云端 LLM 接入前仅登记任务。"""
    m = list_models()
    if model_id not in {x["id"] for x in m}:
        raise ValueError("模型不存在")
    return {"model_id": model_id, "job": f"train-{model_id}-{datetime.datetime.utcnow().strftime('%H%M%S')}",
            "status": "submitted", "note": "占位：接入真实训练/微调后端后执行"}


def create_objective(obj_id: str, name: str, model_id: str, description: str = ""):
    conn = db.get_metadata_conn()
    if not conn.execute("SELECT 1 FROM models WHERE id=?", (model_id,)).fetchone():
        conn.close()
        raise ValueError("模型不存在")
    conn.execute("INSERT OR REPLACE INTO model_objectives (id, name, description, model_id, status, created) VALUES (?,?,?,?,'draft',?)",
                 (obj_id, name, description or "", model_id, _now()))
    conn.commit()
    conn.close()
    return {"ok": True, "id": obj_id}


def list_objectives():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT id, name, description, model_id, status, created FROM model_objectives ORDER BY created DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- A1 AIP 会话（Threads：多轮记忆 + 会话管理） ----
def create_thread(username: str, name: str = "新会话"):
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO threads (name, username, created, updated) VALUES (?,?,?,?)",
                 (name or "新会话", username, _now(), _now()))
    tid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    conn.commit()
    conn.close()
    return {"thread_id": tid, "name": name or "新会话"}


def list_threads(username: str):
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT id, name, created, updated FROM threads WHERE username=? ORDER BY updated DESC",
        (username,),
    ).fetchall()
    cnt = {dict(r)["thread_id"]: dict(r)["n"] for r in conn.execute(
        "SELECT thread_id, count(*) AS n FROM thread_messages GROUP BY thread_id").fetchall()}
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["messages"] = int(cnt.get(d["id"], 0))
        out.append(d)
    return out


def get_messages(tid: int, username: str):
    _check_thread(tid, username)
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT role, content, ts FROM thread_messages WHERE thread_id=? ORDER BY id", (tid,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def thread_chat(tid: int, username: str, message: str):
    _check_thread(tid, username)
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO thread_messages (thread_id, role, content, ts) VALUES (?,?,?,?)",
                 (tid, "user", message, _now()))
    conn.commit()
    conn.close()
    res = aip.chat(message, None)
    reply = res.get("reply", "")
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO thread_messages (thread_id, role, content, ts) VALUES (?,?,?,?)",
                 (tid, "agent", reply, _now()))
    conn.execute("UPDATE threads SET updated=? WHERE id=?", (_now(), tid))
    conn.commit()
    conn.close()
    aip_platform_log_usage(username, message, reply, "chat")
    return {"thread_id": tid, "reply": reply, "tool": res.get("tool"), "args": res.get("args"),
            "result": res.get("result")}


def rename_thread(tid: int, username: str, name: str):
    _check_thread(tid, username)
    conn = db.get_metadata_conn()
    conn.execute("UPDATE threads SET name=? WHERE id=?", (name, tid))
    conn.commit()
    conn.close()
    return {"ok": True}


def delete_thread(tid: int, username: str):
    _check_thread(tid, username)
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM thread_messages WHERE thread_id=?", (tid,))
    conn.execute("DELETE FROM threads WHERE id=?", (tid,))
    conn.commit()
    conn.close()
    return {"ok": True}


def _check_thread(tid: int, username: str):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT username FROM threads WHERE id=?", (tid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("会话不存在")
    if row["username"] != username:
        raise ValueError("无权访问该会话")


def aip_platform_log_usage(username, message, reply, source):
    log_usage("ontic-rule-planner", "request", 1, True, source=source,
              payload={"user": username, "message": message[:200]})
    log_usage("ontic-rule-planner", "token", max(4, len(message) // 4) + len(reply) // 4, True, source=source)


# ---- 模型对比 Playground（84211570） ----
def playground(prompt: str, model_a: str, model_b: str):
    """两模型并行推理：A 用本地规则规划器真实作答；B 为 LLM（配置 key 后真实，否则占位）。"""
    try:
        out_a = aip.chat(prompt, None)["reply"]
        success_a = True
    except Exception as e:
        out_a = f"error: {e}"
        success_a = False
    if model_b != _LOCAL_MODEL and aip.llm_available():
        try:
            out_b = aip.llm_chat(prompt)
            success_b = True
        except Exception as e:
            out_b = f"[LLM 调用失败，已降级] {e}"
            success_b = False
    else:
        out_b = f"[占位] 已收到提示词（{len(prompt)} 字符）。配置 ONTIC_LLM_API_KEY 后此处返回模型 {model_b} 的真实生成结果。"
        success_b = True
    for model, out, ok in ((model_a, out_a, success_a), (model_b, out_b, success_b)):
        log_usage(model, "request", 1, ok, source="playground")
        log_usage(model, "token", max(4, len(prompt) // 4) + len(out) // 4, ok, source="playground")
    return {"model_a": model_a, "output_a": out_a, "model_b": model_b, "output_b": out_b}
