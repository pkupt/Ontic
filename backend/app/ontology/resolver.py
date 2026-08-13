"""对象集查询 -> SQL 下推解析器（Ontology 护城河的核心）。

关键思想（与 Foundry 一致）：对象集查询(过滤/排序/分页)不下拉全表到内存，
而是翻译成 SQL 直接打到数据平面(DuckDB)。字段名经白名单校验后映射到 backing
表的列，值全部参数化，杜绝 SQL 注入。

此外提供链接图遍历（object-link-types / graph traversal）：沿链接类型在对象之间
做多跳跳转，形成知识图谱式的关联探索。
"""
import json
from .. import db
from . import metadata

_LEAF_OPS = {
    "eq": "=",
    "ne": "<>",
    "gt": ">",
    "gte": ">=",
    "lt": "<",
    "lte": "<=",
    "contains": "LIKE",
    "in": "IN",
    "isNull": "IS NULL",
}


def _build_where(node, params: list, props: dict) -> str:
    if not node:
        return "1=1"
    op = node.get("op")
    if op in ("and", "or"):
        parts = [_build_where(c, params, props) for c in node.get("conditions", [])]
        return "(" + f" {op.upper()} ".join(parts) + ")" if parts else "1=1"
    if op == "not":
        return "NOT (" + _build_where(node.get("condition", {}), params, props) + ")"

    field = node.get("field")
    if field not in props:
        raise ValueError(f"未知字段: {field}")
    col = props[field]
    o = node.get("op")
    val = node.get("value")

    if o == "isNull":
        return f"{col} IS NULL" if not node.get("not", False) else f"{col} IS NOT NULL"
    if o == "in":
        ph = []
        for v in (val or []):
            params.append(v)
            ph.append("?")
        return f"{col} IN ({','.join(ph)})"
    if o == "contains":
        params.append(f"%{val}%")
        return f"{col} LIKE ?"
    if o in _LEAF_OPS and o != "isNull":
        params.append(val)
        return f"{col} {_LEAF_OPS[o]} ?"
    raise ValueError(f"不支持的操作: {o}")


def _mask(v, keep=2):
    """敏感值脱敏：保留首尾 keep 个字符，中间打码。"""
    s = str(v)
    if len(s) <= keep * 2:
        return "*" * len(s)
    return s[:keep] + "*" * (len(s) - keep * 2) + s[-keep:]


def query_object_set(type_id, query: dict, user: str = None):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM object_types WHERE id=?", (type_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("对象类型不存在")
    ot = dict(row)
    props = {p["key"]: p["column"] for p in json.loads(ot["properties"])}
    sensitive = {p["key"] for p in json.loads(ot["properties"]) if p.get("sensitive")}
    backing = ot["backing_table"]
    pk = ot["primary_key"]

    select = query.get("select") or list(props.keys())
    for s in select:
        if s not in props:
            raise ValueError(f"未知查询字段: {s}")
    cols = [props[s] for s in select]

    params: list = []
    where = _build_where(query.get("where"), params, props)
    sql = f"SELECT {','.join(cols)} FROM {backing} WHERE {where}"

    ob = query.get("orderBy")
    if ob and ob.get("field") in props:
        sql += f" ORDER BY {props[ob['field']]} {ob.get('direction', 'ASC').upper()}"

    limit = int(query.get("limit", 100))
    offset = int(query.get("offset", 0))
    sql += f" LIMIT {limit} OFFSET {offset}"

    dconn = db.get_duckdb()
    try:
        rows = dconn.execute(sql, params).fetchall()
    finally:
        dconn.close()

    out = [dict(zip(select, r)) for r in rows]
    # Cipher 简化：非 admin 用户对敏感字段返回掩码（admin 可见明文）
    if user and sensitive:
        role = metadata.user_role(user)
        if role != "admin":
            for r in out:
                for s in sensitive:
                    if s in r and r[s] is not None:
                        r[s] = _mask(r[s])
    return out


def count_object_set(type_id, query: dict):
    """返回对象集在给定过滤条件下的总行数（Usage / 概览面板用）。"""
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM object_types WHERE id=?", (type_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("对象类型不存在")
    ot = dict(row)
    props = {p["key"]: p["column"] for p in json.loads(ot["properties"])}
    params: list = []
    where = _build_where(query.get("where"), params, props)
    sql = f"SELECT COUNT(*) FROM {ot['backing_table']} WHERE {where}"
    dconn = db.get_duckdb()
    try:
        n = dconn.execute(sql, params).fetchone()[0]
    finally:
        dconn.close()
    return int(n)


# ---- M2 链接图遍历（object-link-types / graph traversal） ----
def query_linked(start_type: str, start_id, link_id: str):
    """沿单个链接类型，从 start_type 的某对象出发，返回关联的另一侧对象列表。

    方向判定：若 start_type 是链接的 source，则正向跟随外键；若是 target，则反向查找。
    """
    link = metadata.get_link_type(link_id)
    if not link:
        raise ValueError("链接类型不存在")
    src_ot = metadata.get_object_type(link["source_type"])
    tgt_ot = metadata.get_object_type(link["target_type"])
    if not src_ot or not tgt_ot:
        raise ValueError("链接关联的对象类型不存在")
    s_back = src_ot["backing_table"]
    t_back = tgt_ot["backing_table"]
    s_pk = src_ot["primary_key"]
    t_pk = tgt_ot["primary_key"]
    sfk = link["source_fk"]

    dconn = db.get_duckdb()
    try:
        if start_type == link["source_type"]:
            # 正向：从 source 的 sfk 找到对应的 target
            sql = f"SELECT t.* FROM {t_back} t WHERE t.{t_pk} = (SELECT s.{sfk} FROM {s_back} s WHERE s.{s_pk}=?)"
            rows = dconn.execute(sql, [start_id]).fetchall()
            cols = [d[0] for d in dconn.description]
            return {"link": link, "direction": "forward", "target_type": link["target_type"], "rows": [dict(zip(cols, r)) for r in rows]}
        elif start_type == link["target_type"]:
            # 反向：找到所有 sfk == start_id 的 source 对象
            sql = f"SELECT s.* FROM {s_back} s WHERE s.{sfk}=?"
            rows = dconn.execute(sql, [start_id]).fetchall()
            cols = [d[0] for d in dconn.description]
            return {"link": link, "direction": "reverse", "target_type": link["source_type"], "rows": [dict(zip(cols, r)) for r in rows]}
        else:
            raise ValueError("起始对象类型与该链接无关")
    finally:
        dconn.close()


def traverse_graph(start_type: str, start_id, max_hops: int = 2):
    """从起始对象出发，沿所有相关链接做 BFS 多跳遍历，返回节点与边（知识图谱式探索）。"""
    nodes = {}   # "type#id" -> {type, id, label}

    def add_node(t, oid, row=None):
        key = f"{t}#{oid}"
        if key in nodes:
            return key
        label = f"{t}:{oid}"
        if row is not None:
            ot = metadata.get_object_type(t)
            if ot:
                for p in json.loads(ot["properties"]):
                    if p["type"] == "string" and p["key"] in row and row[p["key"]]:
                        label = str(row[p["key"]])
                        break
        nodes[key] = {"type": t, "id": oid, "label": label}
        return key

    add_node(start_type, start_id)
    edges = []
    frontier = [(start_type, start_id)]
    for _ in range(max_hops):
        nxt = []
        for (t, oid) in frontier:
            for link in metadata.list_links_for_type(t):
                try:
                    res = query_linked(t, oid, link["id"])
                except Exception:
                    continue
                src_key = add_node(t, oid)
                for r in res["rows"]:
                    tgt_pk = metadata.get_object_type(res["target_type"])["primary_key"]
                    nxt.append((res["target_type"], r.get(tgt_pk)))
                    tgt_key = add_node(res["target_type"], r.get(tgt_pk), r)
                    edges.append({"link": link["id"], "source": src_key, "target": tgt_key})
        frontier = nxt
        if not frontier:
            break
    return {"nodes": list(nodes.values()), "edges": edges, "hops": max_hops}
