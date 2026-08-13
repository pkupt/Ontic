"""M10 可观测性 / 血缘：数据血缘图 + 监控规则。

对齐 Foundry 原型：
  - 数据血缘（10096559 / 75035474 Data lineage）：从管道步骤 SQL 推导
    输入/输出对象类型，形成 Data Source → Sync → Transform → Output 的血缘边。
  - 监控规则（34752748）：对对象类型设置指标阈值，运行检查并告警到活动日志。
  - 事件时间线（23315552）：复用 activity 日志（通知中心已有）。
"""
import re
import datetime

from . import db
from .ontology import metadata

_FROM_RE = re.compile(r"\bfrom\s+([`\"\[]?)([a-zA-Z_][a-zA-Z0-9_]*)\1", re.IGNORECASE)


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _type_of_table(tbl: str):
    """ont__customer -> customer；裸名直接视为类型 id（若存在）。"""
    if tbl.startswith("ont__"):
        return tbl[len("ont__"):]
    return tbl


def derive_lineage():
    """从全部管道推导血缘边：{source_type -> [target_type]}（含链接关系边）。"""
    edges = []  # {source, target, via}
    seen = set()
    for p in metadata.list_pipelines():
        for step in (p.get("steps") or []):
            target = step.get("target")
            if not target:
                continue
            sql = step.get("sql", "")
            for m in _FROM_RE.finditer(sql):
                src = _type_of_table(m.group(2))
                if src == target:
                    continue
                key = (src, target)
                if key not in seen:
                    seen.add(key)
                    edges.append({"source": src, "target": target, "via": p["id"]})
    # 链接关系也作为血缘边（customer -> region）
    for lk in metadata.list_link_types():
        key = (lk["source_type"], lk["target_type"])
        if key not in seen:
            seen.add(key)
            edges.append({"source": lk["source_type"], "target": lk["target_type"], "via": f"link:{lk['id']}"})
    return edges


def lineage_graph():
    edges = derive_lineage()
    types = {t["id"]: {"id": t["id"], "name": t["name"]} for t in metadata.list_object_types()}
    return {"nodes": list(types.values()), "edges": edges}


def lineage_for(type_id):
    edges = derive_lineage()
    up = [e for e in edges if e["target"] == type_id]
    down = [e for e in edges if e["source"] == type_id]
    return {
        "type_id": type_id,
        "upstream": [{"type": e["source"], "via": e["via"]} for e in up],
        "downstream": [{"type": e["target"], "via": e["via"]} for e in down],
    }


# ---- 监控规则（34752748） ----
def create_monitor(m: dict):
    mid = (m.get("id") or "").strip()
    if not mid or not m.get("object_type"):
        raise ValueError("id 与 object_type 必填")
    if not metadata.get_object_type(m["object_type"]):
        raise ValueError("对象类型不存在")
    conn = db.get_metadata_conn()
    conn.execute(
        """INSERT OR REPLACE INTO monitors (id, name, object_type, metric, op, threshold, enabled)
           VALUES (?,?,?,?,?,?,?)""",
        (mid, m.get("name", mid), m["object_type"], m.get("metric", "count"),
         m.get("op", "gt"), float(m.get("threshold", 100)), 1 if m.get("enabled", True) else 0),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": mid}


def list_monitors():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM monitors ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_monitor(mid):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM monitors WHERE id=?", (mid,))
    conn.commit()
    conn.close()


def check_monitor(mid):
    """对单个监控执行检查：取值 + 阈值判定，违规写入活动日志。"""
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM monitors WHERE id=?", (mid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("监控不存在")
    m = dict(row)
    dconn = db.get_duckdb()
    try:
        ot = metadata.get_object_type(m["object_type"])
        if m["metric"] == "count":
            value = float(dconn.execute(f'SELECT COUNT(*) FROM {ot["backing_table"]}').fetchone()[0])
        else:
            # 其余指标按列聚合（metric 形如 sum:amount）
            col = m["metric"].split(":", 1)[1]
            agg = m["metric"].split(":", 1)[0]
            value = float(dconn.execute(f'SELECT {agg}("{col}") FROM {ot["backing_table"]}').fetchone()[0] or 0)
    except Exception as e:
        return {"monitor": mid, "status": "error", "error": str(e)}
    finally:
        dconn.close()
    breached = {"gt": value > m["threshold"], "lt": value < m["threshold"], "gte": value >= m["threshold"], "lte": value <= m["threshold"]}.get(m["op"], False)
    metadata.log_activity("monitor",
                          f"监控 {m['name']}：{m['metric']} = {value:.2f}（阈值 {m['op']} {m['threshold']:g}）" + (" ⚠ 告警" if breached else " ✓ 正常"))
    return {"monitor": mid, "metric": m["metric"], "value": value, "threshold": m["threshold"],
            "op": m["op"], "breached": breached}


def check_all_monitors():
    out = []
    for m in list_monitors():
        if not m["enabled"]:
            continue
        try:
            out.append(check_monitor(m["id"]))
        except ValueError as e:
            out.append({"monitor": m["id"], "status": "error", "error": str(e)})
    return out
