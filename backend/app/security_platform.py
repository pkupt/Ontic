"""M8 安全与治理：敏感数据扫描 / 审批流 / 留存策略 / 安全标记。

对齐 Foundry 安全治理原型：
  - 敏感数据扫描（59324049）：PII 正则库 + 扫描历史 + 重新扫描 + Overall matches。
  - 审批流（69762283 / 31518435）：写操作审批队列（pending → approve/reject）。
  - 留存策略（数据生命周期）：每类型留存天数，超期标记（基于活动日志推算）。
  - 安全标记（5667552）：给对象类型分配标记（Restricted / Confidential / Public）。
"""
import json
import re
import datetime

from . import db
from .ontology import metadata, actions

PII_RULES = [
    {"id": "email", "name": "Email", "pattern": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"},
    {"id": "phone", "name": "Phone", "pattern": r"(?<!\d)1[3-9]\d{9}(?!\d)"},
    {"id": "idcard", "name": "Chinese ID", "pattern": r"(?<!\d)\d{17}[\dXx](?!\d)"},
    {"id": "ip", "name": "IPv4", "pattern": r"(?<!\d)(?:\d{1,3}\.){3}\d{1,3}(?!\d)"},
    {"id": "creditcard", "name": "Credit card", "pattern": r"(?<!\d)(?:\d{4}[ -]?){3}\d{4}(?!\d)"},
]
_RULES = [{"id": r["id"], "name": r["name"], "rx": re.compile(r["pattern"])} for r in PII_RULES]


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- 敏感数据扫描（59324049） ----
def scan_object_type(type_id: str):
    ot = metadata.get_object_type(type_id)
    if not ot:
        raise ValueError("对象类型不存在")
    props = json.loads(ot["properties"])
    dconn = db.get_duckdb()
    rows, cols = [], []
    try:
        if props:
            cols_sql = ", ".join(f'"{p["column"]}"' for p in props)
            cur = dconn.execute(f'SELECT {cols_sql} FROM {ot["backing_table"]}')
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
    finally:
        dconn.close()

    matches = {}
    samples = {}
    for i, col in enumerate(cols):
        for rule in _RULES:
            cnt, sample = 0, None
            for r in rows:
                v = r[i]
                if v is None:
                    continue
                for m in rule["rx"].findall(str(v)):
                    cnt += 1
                    if sample is None:
                        sample = m
            if cnt:
                key = f"{col}:{rule['name']}"
                matches[key] = cnt
                samples[key] = sample
    summary = json.dumps(
        [{"match": k, "count": c, "sample": samples.get(k)} for k, c in sorted(matches.items())],
        ensure_ascii=False,
    )
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO security_scans (ts, object_type, summary) VALUES (?,?,?)",
                 (_now(), type_id, summary))
    conn.commit()
    hist = conn.execute(
        "SELECT ts, summary FROM security_scans WHERE object_type=? ORDER BY id DESC LIMIT 5",
        (type_id,),
    ).fetchall()
    conn.close()
    history = []
    for h in hist:
        d = dict(h)
        try:
            d["summary"] = json.loads(d["summary"])
        except Exception:
            d["summary"] = []
        history.append(d)
    return {"object_type": type_id, "scanned_rows": len(rows), "matches": matches, "history": history}


def list_scans(object_type: str = ""):
    conn = db.get_metadata_conn()
    sql = "SELECT ts, object_type, summary FROM security_scans"
    params = ()
    if object_type:
        sql += " WHERE object_type=?"
        params = (object_type,)
    rows = conn.execute(sql + " ORDER BY id DESC LIMIT 20", params).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["summary"] = json.loads(d["summary"])
        except Exception:
            d["summary"] = []
        out.append(d)
    return out


# ---- 审批流（69762283） ----
def create_approval(requester: str, object_type: str, action_id: str, params: dict, note: str = ""):
    if not action_id.startswith("__branch_apply__:") and not metadata.get_action(action_id):
        raise ValueError("动作不存在")
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT INTO approvals (ts, requester, object_type, action_id, params, note, status) VALUES (?,?,?,?,?,?,'pending')",
        (_now(), requester, object_type, action_id, json.dumps(params or {}, ensure_ascii=False), note or ""),
    )
    aid = conn.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]
    conn.commit()
    conn.close()
    return {"approval_id": aid, "status": "pending"}


def list_approvals(status: str = ""):
    conn = db.get_metadata_conn()
    sql = "SELECT id, ts, requester, object_type, action_id, params, note, status, reviewer FROM approvals"
    params = ()
    if status:
        sql += " WHERE status=?"
        params = (status,)
    rows = conn.execute(sql + " ORDER BY id DESC LIMIT 50", params).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["params"] = json.loads(d["params"])
        except Exception:
            d["params"] = {}
        out.append(d)
    return out


def decide_approval(approval_id: int, reviewer: str, approve: bool):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("审批请求不存在")
    d = dict(row)
    if d["status"] != "pending":
        conn.close()
        raise ValueError(f"该请求已处理（{d['status']}）")
    detail = None
    if approve:
        if d["action_id"].startswith("__branch_apply__:"):
            # C2：分支 apply 审批（特殊动作类型）
            from . import versioning
            try:
                detail = versioning.apply_branch(int(d["action_id"].split(":")[1]))
            except ValueError as e:
                conn.close()
                raise ValueError(f"应用分支失败: {e}")
        else:
            try:
                detail = actions.execute_action(d["action_id"], json.loads(d["params"]))
            except ValueError as e:
                conn.close()
                raise ValueError(f"执行动作失败: {e}")
        new_status = "approved"
    else:
        new_status = "rejected"
    conn.execute("UPDATE approvals SET status=?, reviewer=? WHERE id=?", (new_status, reviewer, approval_id))
    conn.commit()
    conn.close()
    return {"approval_id": approval_id, "status": new_status, "detail": detail}


# ---- 留存策略 ----
DEFAULT_RETENTION_DAYS = 90


def set_retention(object_type: str, days: int):
    if not metadata.get_object_type(object_type):
        raise ValueError("对象类型不存在")
    conn = db.get_metadata_conn()
    conn.execute("INSERT OR REPLACE INTO retention (object_type, days) VALUES (?,?)", (object_type, int(days)))
    conn.commit()
    conn.close()


def list_retention():
    conn = db.get_metadata_conn()
    policies = {dict(r)["object_type"]: dict(r)["days"] for r in conn.execute("SELECT * FROM retention").fetchall()}
    # 用活动日志推算每个类型最近一次事件时间
    events = conn.execute("SELECT ts, message FROM activity").fetchall()
    conn.close()
    last_ts = {}
    for e in events:
        for ot in metadata.list_object_types():
            if ot["id"] in e["message"]:
                last_ts[ot["id"]] = max(last_ts.get(ot["id"], ""), e["ts"])
    out = []
    for ot in metadata.list_object_types():
        days = policies.get(ot["id"], DEFAULT_RETENTION_DAYS)
        last = last_ts.get(ot["id"], "")
        overdue = bool(last) and (datetime.datetime.utcnow() - datetime.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ")).days > days
        out.append({
            "object_type": ot["id"], "name": ot["name"], "days": days,
            "last_event": last, "overdue": overdue, "has_policy": ot["id"] in policies,
        })
    return out


# ---- 安全标记（5667552） ----
MARKING_REGISTRY = ["Restricted", "Confidential", "Public"]


def list_markings(object_type: str = ""):
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT object_type, marking FROM type_markings ORDER BY object_type, marking").fetchall()
    conn.close()
    assigned = {(dict(r)["object_type"], dict(r)["marking"]) for r in rows}
    if object_type:
        return {"registry": MARKING_REGISTRY, "assigned": sorted(m for (t, m) in assigned if t == object_type)}
    by_type = {}
    for t, m in assigned:
        by_type.setdefault(t, []).append(m)
    return {"registry": MARKING_REGISTRY, "assigned": by_type}


def assign_marking(object_type: str, marking: str, remove: bool = False):
    if marking not in MARKING_REGISTRY:
        raise ValueError(f"标记须属于 {MARKING_REGISTRY}")
    conn = db.get_metadata_conn()
    if remove:
        conn.execute("DELETE FROM type_markings WHERE object_type=? AND marking=?", (object_type, marking))
    else:
        conn.execute("INSERT OR IGNORE INTO type_markings (object_type, marking) VALUES (?,?)", (object_type, marking))
    conn.commit()
    conn.close()
    return {"object_type": object_type, "marking": marking, "removed": remove}
