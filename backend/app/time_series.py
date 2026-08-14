"""B1 时间序列模型（对齐 time-series 分区）。

时间序列 = 实体(entity) 在某时间点上的观测值。通用存储表 time_series：
  - series_id: 序列名（如 "cpu.usage"）
  - entity:    实体键（如 "node-1"）
  - ts:        时间戳（ISO 或 unix 秒）
  - value:     DOUBLE 观测值

端点能力：写入（批量点）、区间查询、按时间桶聚合（avg/sum/min/max）、序列列表。
"""
import datetime

from . import db


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_ts_table():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS time_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id TEXT NOT NULL,
            entity TEXT NOT NULL,
            ts TEXT NOT NULL,
            value DOUBLE NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ts_lookup ON time_series (series_id, entity, ts);
        """
    )
    conn.commit()
    conn.close()


def _normalize_ts(v):
    """接受 unix 秒 / ISO 字符串，统一为 ISO 8601。"""
    if isinstance(v, (int, float)):
        return datetime.datetime.fromtimestamp(float(v)).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(v).strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        return datetime.datetime.fromisoformat(s).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise ValueError(f"无法解析时间戳: {v}")


def ingest(series_id: str, entity: str, points):
    if not series_id or not entity:
        raise ValueError("series_id 与 entity 必填")
    rows = [(series_id, entity, _normalize_ts(p[0]), float(p[1])) for p in (points or [])]
    if not rows:
        raise ValueError("points 不能为空")
    conn = db.get_metadata_conn()
    conn.executemany(
        "INSERT INTO time_series (series_id, entity, ts, value) VALUES (?,?,?,?)", rows
    )
    conn.commit()
    conn.close()
    return {"series": series_id, "entity": entity, "ingested": len(rows)}


def list_series():
    conn = db.get_metadata_conn()
    rows = conn.execute(
        "SELECT series_id, entity, count(*) AS n, min(ts) AS min_ts, max(ts) AS max_ts FROM time_series GROUP BY series_id, entity ORDER BY series_id, entity"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def query(series_id: str, entity: str = "", from_ts: str = "", to_ts: str = "", agg: str = "", bucket: str = ""):
    """区间查询 + 可选时间桶聚合。bucket ∈ hour/day（按 UTC 截断）。"""
    conn = db.get_metadata_conn()
    sql = "SELECT ts, value FROM time_series WHERE series_id=?"
    params = [series_id]
    if entity:
        sql += " AND entity=?"
        params.append(entity)
    if from_ts:
        sql += " AND ts >= ?"
        params.append(_normalize_ts(from_ts))
    if to_ts:
        sql += " AND ts <= ?"
        params.append(_normalize_ts(to_ts))
    sql += " ORDER BY ts"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    data = [dict(r) for r in rows]

    if agg and bucket in ("hour", "day"):
        cut = 13 if bucket == "hour" else 10  # "YYYY-MM-DDTHH" / "YYYY-MM-DD"
        buckets = {}
        for r in data:
            key = r["ts"][:cut]
            b = buckets.setdefault(key, [])
            b.append(r["value"])
        agg_rows = []
        for key in sorted(buckets):
            vals = buckets[key]
            if agg == "sum":
                v = sum(vals)
            elif agg == "max":
                v = max(vals)
            elif agg == "min":
                v = min(vals)
            else:
                v = sum(vals) / len(vals)
            agg_rows.append({"bucket": key, "value": round(v, 4), "n": len(vals)})
        return {"series": series_id, "entity": entity, "agg": agg, "bucket": bucket, "points": agg_rows, "count": len(data)}

    return {"series": series_id, "entity": entity, "points": data, "count": len(data)}


def delete_series(series_id: str, entity: str = ""):
    """删除时间序列（按 series_id，可限定 entity）。"""
    conn = db.get_metadata_conn()
    if entity:
        conn.execute("DELETE FROM time_series WHERE series_id=? AND entity=?", (series_id, entity))
    else:
        conn.execute("DELETE FROM time_series WHERE series_id=?", (series_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": series_id}
