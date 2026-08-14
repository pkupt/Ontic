"""动作引擎（Action Engine）：类型化、带校验的写操作。

一个 Action 定义了对某对象类型的 create/update/delete 操作，参数经定义校验后
下推为 SQL 写回数据平面。这是 Ontology 让"应用与 Agent 直接改业务对象"的入口。
"""
import json
import re
from .. import db


def _coerce(val, typ):
    """把动作参数（通常来自表单/JSON 的字符串）按定义的类型做安全转换。"""
    if val is None or (isinstance(val, str) and val.strip() == ""):
        return None
    if typ == "integer":
        return int(val)
    if typ == "double":
        return float(val)
    if typ == "boolean":
        return str(val).strip().lower() in ("true", "1", "yes", "y")
    return str(val)


def _validate(meta: dict, key: str, v):
    """字段约束校验：必填 / 枚举 / 正则（属性定义中可选配置）。"""
    if meta.get("required") and (v is None or v == ""):
        raise ValueError(f"字段 {key} 必填")
    if meta.get("enum") and v is not None and v != "" and v not in meta["enum"]:
        raise ValueError(f"字段 {key} 必须是 {meta['enum']} 之一")
    if meta.get("pattern") and v is not None and v != "":
        if not re.match(meta["pattern"], str(v)):
            raise ValueError(f"字段 {key} 格式不合法（需匹配 {meta['pattern']}）")


def execute_action(action_id: str, params: dict):
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("动作不存在")
    action = dict(row)
    ot_row = conn.execute(
        "SELECT * FROM object_types WHERE id=?", (action["object_type"],)
    ).fetchone()
    conn.close()
    if not ot_row:
        raise ValueError("动作关联的对象类型不存在")

    ot = dict(ot_row)
    props = {p["key"]: p["column"] for p in json.loads(ot["properties"])}
    props_meta = {p["key"]: p for p in json.loads(ot["properties"])}
    backing = ot["backing_table"]
    pk = ot["primary_key"]
    aparams = json.loads(action["parameters"])

    for p in aparams:
        if p.get("required") and p["name"] not in params:
            raise ValueError(f"缺少必填参数: {p['name']}")

    dconn = db.get_duckdb()
    try:
        op = action["operation"]
        if op == "create":
            # 属性级必填校验（create 时必须提供）
            for key, meta in props_meta.items():
                if meta.get("required") and (key not in params or params.get(key) in (None, "")):
                    raise ValueError(f"字段 {key} 必填")
            cols, vals = [], []
            pk_provided = False
            for p in aparams:
                if p["name"] in params:
                    col = f'"{props[p["name"]]}"'
                    v = _coerce(params[p["name"]], p["type"])
                    _validate(props_meta.get(p["name"], {}), p["name"], v)
                    if v is None:
                        continue
                    cols.append(col)
                    vals.append(v)
                    if col == f'"{pk}"':
                        pk_provided = True
            if not pk_provided:
                nxt = dconn.execute(f'SELECT COALESCE(max("{pk}"),0)+1 FROM {backing}').fetchone()[0]
                cols.append(f'"{pk}"')
                vals.append(nxt)
            ph = ",".join(["?"] * len(vals))
            dconn.execute(
                f"INSERT INTO {backing} ({','.join(cols)}) VALUES ({ph})", vals
            )
            rid = dconn.execute(f'SELECT max("{pk}") FROM {backing}').fetchone()[0]
            return {"created": True, "id": rid}
        if op == "update":
            rid = _coerce(params.get("id"), "integer" if pk == "id" else _pk_type(aparams, pk))
            if rid is None:
                raise ValueError("update 动作需要 id 参数")
            set_cols, set_vals = [], []
            for p in aparams:
                if p["name"] in params and p["name"] != "id":
                    v = _coerce(params[p["name"]], p["type"])
                    _validate(props_meta.get(p["name"], {}), p["name"], v)
                    if v is None:
                        continue
                    set_cols.append(f'"{props[p["name"]]}"=?')
                    set_vals.append(v)
            if set_cols:
                dconn.execute(
                    f"UPDATE {backing} SET {','.join(set_cols)} WHERE \"{pk}\"=?",
                    set_vals + [rid],
                )
            return {"updated": True, "id": rid}
        if op == "delete":
            rid = _coerce(params.get("id"), "integer" if pk == "id" else _pk_type(aparams, pk))
            if rid is None:
                raise ValueError("delete 动作需要 id 参数")
            dconn.execute(f"DELETE FROM {backing} WHERE \"{pk}\"=?", [rid])
            return {"deleted": True, "id": rid}
        raise ValueError(f"不支持的操作: {op}")
    finally:
        dconn.close()


def _pk_type(aparams, pk):
    for p in aparams:
        if p["name"] == "id":
            return p["type"]
    return "integer"
