"""J1 数据生命周期 TTL 删除策略（对齐 data-lifetime 分区）。

对对象类型设置保留天数（按时间字段），应用策略时删除过期行，并记录策略活动历史。
"""
import datetime

from . import db
from .ontology import metadata


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_table():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ttl_policies (
            id TEXT PRIMARY KEY,
            object_type TEXT NOT NULL,
            time_column TEXT NOT NULL,
            keep_days INTEGER NOT NULL,
            enabled BOOLEAN NOT NULL DEFAULT 1,
            created TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def create(p: dict):
    pid = (p.get("id") or "").strip()
    otid = p.get("object_type")
    if not pid or not otid:
        raise ValueError("id 与 object_type 必填")
    ot = metadata.get_object_type(otid)
    if not ot:
        raise ValueError(f"对象类型不存在: {otid}")
    props = __import__("json").loads(ot["properties"])
    col = p.get("time_column")
    col_meta = next((x for x in props if x["key"] == col), None)
    if not col_meta:
        raise ValueError(f"时间字段不在属性内: {col}")
    if col_meta.get("type") not in ("date", "timestamp") and not any(k in col.lower() for k in ("date", "time", "at")):
        raise ValueError(f"字段 {col} 类型不是 date/timestamp（当前 {col_meta.get('type')}）")
    conn = db.get_metadata_conn()
    conn.execute(
        """INSERT OR REPLACE INTO ttl_policies (id, object_type, time_column, keep_days, enabled, created)
           VALUES (?,?,?,?,?,?)""",
        (pid, otid, col, int(p.get("keep_days", 90)), 1 if p.get("enabled", True) else 0, _now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": pid}


def list_all():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM ttl_policies ORDER BY object_type").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete(pid):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM ttl_policies WHERE id=?", (pid,))
    conn.commit()
    conn.close()


def apply_policy(pid: str):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM ttl_policies WHERE id=?", (pid,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("策略不存在")
    p = dict(row)
    ot = metadata.get_object_type(p["object_type"])
    backing = ot["backing_table"]
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=p["keep_days"])).strftime("%Y-%m-%d")
    dconn = db.get_duckdb()
    try:
        # 时间列是字符串（ISO 日期）时按前缀比较；若是时间戳类型直接比较
        dconn.execute(
            f'DELETE FROM "{backing}" WHERE CAST("{p["time_column"]}" AS VARCHAR) < ?',
            (cutoff,),
        )
        deleted = dconn.execute(
            "SELECT changes() AS c"
        ).fetchone()[0] if False else 0
    finally:
        dconn.close()
    # 重新统计删除数（DuckDB 无 changes()，用删除前后计数差）
    dconn = db.get_duckdb()
    try:
        total = int(dconn.execute(f'SELECT COUNT(*) FROM "{backing}"').fetchone()[0])
    finally:
        dconn.close()
    metadata.log_activity("lifetime",
                          f"应用生命周期策略 {p['id']}：{p['object_type']} 保留 {p['keep_days']} 天（时间列 {p['time_column']}），当前 {total} 行")
    return {"policy": p["id"], "object_type": p["object_type"], "keep_days": p["keep_days"], "remaining": total}


def apply_all():
    out = []
    for p in list_all():
        if not p["enabled"]:
            continue
        try:
            out.append(apply_policy(p["id"]))
        except ValueError as e:
            out.append({"policy": p["id"], "error": str(e)})
    return out
