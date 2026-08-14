"""I1 Contour 分析画布（对齐 contour 分区，节点链简化版）。

分析 = 节点链：source(对象类型) → filter(条件) → aggregate(分组聚合) / limit → 输出。
- run：逐步执行返回行/列/计数
- save_as_type：结果注册为新对象类型（可继续被本体消费）
"""
import json
import datetime

from . import db
from . import ingestion
from .ontology import metadata, resolver

_STEP_TYPES = ("source", "filter", "aggregate", "limit")


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def init_table():
    conn = db.get_metadata_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS analyses (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            steps TEXT NOT NULL,
            created TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()


def _validate_steps(steps: list):
    if not steps or steps[0].get("type") != "source":
        raise ValueError("第一步必须是 source（数据源）")
    for s in steps:
        if s.get("type") not in _STEP_TYPES:
            raise ValueError(f"未知步骤类型: {s.get('type')}")
    src = steps[0].get("table", "")
    if not metadata.get_object_type(src):
        raise ValueError(f"数据源对象类型不存在: {src}")


def create(a: dict):
    aid = (a.get("id") or "").strip()
    if not aid:
        raise ValueError("分析 id 必填")
    steps = a.get("steps") or []
    _validate_steps(steps)
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO analyses (id, name, description, steps, created) VALUES (?,?,?,?,?)",
        (aid, a.get("name", aid), a.get("description", ""), json.dumps(steps, ensure_ascii=False), _now()),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": aid}


def list_all():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT * FROM analyses ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get(aid):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete(aid):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM analyses WHERE id=?", (aid,))
    conn.commit()
    conn.close()


def run(aid: str, limit: int = 500, run_params: dict = None):
    """运行分析：{param} 占位用 run_params 替换（I2 分析路径参数化）。"""
    a = get(aid)
    if not a:
        raise ValueError("分析不存在")
    import copy
    steps = copy.deepcopy(json.loads(a["steps"]))
    run_params = run_params or {}

    def _sub(v):
        if isinstance(v, str) and len(v) > 2 and v.startswith("{") and v.endswith("}"):
            key = v[1:-1]
            return run_params.get(key, v)
        return v

    for s in steps:
        if s.get("type") == "filter":
            w = s.get("where")
            if isinstance(w, dict) and "value" in w:
                w["value"] = _sub(w["value"])
    src = steps[0]["table"]
    ot = metadata.get_object_type(src)
    props = {p["key"]: p["column"] for p in json.loads(ot["properties"])}
    backing = ot["backing_table"]
    sql = f'SELECT * FROM "{backing}"'
    params = []
    where_applied = False
    limit_val = None
    for s in steps[1:]:
        t = s["type"]
        if t == "filter":
            if where_applied:
                sql += " AND"
            else:
                sql += " WHERE"
            w = resolver._build_where(s.get("where") or {}, params, props)
            sql += f" ({w})"
            where_applied = True
        elif t == "aggregate":
            gb = s.get("group_by")
            if gb not in props:
                raise ValueError(f"分组字段不在属性内: {gb}")
            aggs = s.get("aggs") or {}
            sel = [f'"{props[gb]}" AS "{gb}"']
            for f, ag in aggs.items():
                if f not in props or ag not in ("sum", "avg", "min", "max", "count"):
                    raise ValueError(f"聚合无效: {ag}({f})")
                sel.append(f'{ag}("{props[f]}") AS "{f}_{ag}"')
            sql = f"SELECT {', '.join(sel)} FROM ({sql}) AS t GROUP BY 1"
            where_applied = False
        elif t == "limit":
            limit_val = int(s.get("n", limit))
    if limit_val is None:
        limit_val = limit
    sql += f" LIMIT {int(limit_val)}"
    dconn = db.get_duckdb()
    try:
        cur = dconn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        dconn.close()
    return {"analysis": aid, "columns": cols, "rows": rows, "count": len(rows)}


def save_as_type(aid: str, new_type_id: str):
    """把分析结果注册为新对象类型（结果持久化，供本体继续消费）。"""
    a = get(aid)
    if not a:
        raise ValueError("分析不存在")
    res = run(aid, limit=5000)
    if not res["rows"]:
        raise ValueError("分析结果为空，无法保存")
    rows = res["rows"]
    cols = res["columns"]
    backing = f"ont__{new_type_id}"
    dconn = db.get_duckdb()
    try:
        col_defs = []
        fields = []
        for c in cols:
            v = rows[0].get(c)
            if isinstance(v, bool):
                typ = "boolean"
            elif isinstance(v, int):
                typ = "integer"
            elif isinstance(v, float):
                typ = "double"
            else:
                typ = "string"
            col_defs.append(f'"{c}" {_DUCK[typ]}')
            fields.append({"key": c, "column": c, "type": typ, "title": c})
        dconn.execute(f'CREATE OR REPLACE TABLE "{backing}" ({", ".join(col_defs)})')
        col_list = ", ".join(f'"{c}"' for c in cols)
        ph = ", ".join(["?"] * len(cols))
        dconn.executemany(
            f'INSERT INTO "{backing}" ({col_list}) VALUES ({ph})',
            [[r.get(c) for c in cols] for r in rows],
        )
    finally:
        dconn.close()
    res_reg = ingestion._register_from_table(new_type_id, backing, f"Contour 分析 {aid} 结果")
    metadata.log_activity("analysis", f"保存分析 {aid} 为新对象类型 {new_type_id}（{len(rows)} 行）")
    return {"object_type": new_type_id, "rows": len(rows), "registered": res_reg}


_DUCK = {"integer": "INTEGER", "double": "DOUBLE", "boolean": "BOOLEAN", "string": "VARCHAR"}
