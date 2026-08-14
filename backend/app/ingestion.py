"""接入与管道（S3）：把外部数据接入数据平面并自动注册为 Ontology 对象。

- ingest_csv: 上传 CSV → DuckDB 建表 → 自动推导属性 → 注册对象类型 + 创建动作。
  闭合「接入 → 转换 → 本体」主轴。
- transform_from_sql: 用一条 SELECT 派生新表并注册为对象类型（管道里的"转换"步骤）。
"""
import json
import os
import re
import tempfile
from . import db
from .ontology import metadata
from . import functions

_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def _map_type(duck_type: str) -> str:
    t = (duck_type or "").upper()
    if "BOOLEAN" in t or t == "BOOL":
        return "boolean"
    if "DOUBLE" in t or "FLOAT" in t or "DECIMAL" in t or "REAL" in t:
        return "double"
    if "INT" in t or "BIGINT" in t or "SMALLINT" in t or "TINYINT" in t:
        return "integer"
    return "string"


def _register_from_table(object_type_id: str, backing: str, description: str):
    dconn = db.get_duckdb()
    try:
        cols = dconn.execute(f'DESCRIBE "{backing}"').fetchall()
        cnt = dconn.execute(f'SELECT count(*) FROM "{backing}"').fetchone()[0]
    finally:
        dconn.close()

    props = []
    for c in cols:
        col_name = c[0]
        props.append(
            {"key": col_name, "column": col_name, "type": _map_type(c[1]), "title": col_name}
        )
    if not props:
        raise ValueError("派生表没有列，无法注册对象类型")

    metadata.create_object_type(
        {
            "id": object_type_id,
            "name": object_type_id,
            "description": description,
            "backing_table": backing,
            "primary_key": props[0]["key"],
            "properties": json.dumps(props),
        }
    )
    metadata.ensure_crud_actions(object_type_id, props, props[0]["key"])
    return {"object_type": object_type_id, "columns": len(props), "rows": cnt}


def ingest_csv(object_type_id: str, primary_key: str, file_bytes: bytes, filename: str):
    if not _ID_RE.match(object_type_id):
        raise ValueError("object_type_id 须以字母开头，仅含字母/数字/下划线")
    backing = f"ont__{object_type_id}"
    suffix = os.path.splitext(filename or "data.csv")[1] or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file_bytes)
        tmp.close()
        dconn = db.get_duckdb()
        try:
            dconn.execute(
                f"CREATE OR REPLACE TABLE \"{backing}\" AS SELECT * FROM read_csv_auto('{tmp.name}', header=true)"
            )
        finally:
            dconn.close()
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)
    return _register_from_table(
        object_type_id, backing, f"CSV 接入自动注册: {filename}"
    )


def transform_from_sql(name: str, sql: str):
    if not _ID_RE.match(name):
        raise ValueError("name 须以字母开头，仅含字母/数字/下划线")
    backing = f"ont__{name}"
    dconn = db.get_duckdb()
    try:
        functions.register_functions(dconn)  # 让转换 SQL 可用 ont_* 函数库
        dconn.execute(f'CREATE OR REPLACE TABLE "{backing}" AS {sql}')
    finally:
        dconn.close()
    return _register_from_table(name, backing, f"由 SQL 转换派生: {sql[:80]}")


# M3 可视化建模：从字段定义直接创建对象类型（无需写代码/种子）
_DUCK_TYPE = {"integer": "INTEGER", "double": "DOUBLE", "boolean": "BOOLEAN", "string": "VARCHAR", "date": "DATE", "timestamp": "TIMESTAMP", "geohash": "VARCHAR", "attachment": "VARCHAR"}


def create_object_type_from_def(payload: dict):
    oid = (payload.get("id") or "").strip()
    if not _ID_RE.match(oid):
        raise ValueError("对象类型 id 须以字母开头，仅含字母/数字/下划线")
    if metadata.get_object_type(oid):
        raise ValueError(f"对象类型已存在: {oid}")
    fields = payload.get("fields") or []
    if not fields:
        raise ValueError("至少需要一个字段")
    pk = (payload.get("primary_key") or fields[0]["key"]).strip()
    if not _ID_RE.match(pk):
        raise ValueError("主键 key 非法")

    cols, props = [], []
    for f in fields:
        key = (f.get("key") or "").strip()
        if not _ID_RE.match(key):
            raise ValueError(f"字段 key 非法: {key}")
        typ = f.get("type", "string")
        if typ not in _DUCK_TYPE:
            raise ValueError(f"不支持的字段类型: {typ}")
        col = f'"{key}" {_DUCK_TYPE[typ]}'
        if key == pk:
            col += " PRIMARY KEY"
        cols.append(col)
        item = {"key": key, "column": key, "type": typ, "title": f.get("title", key)}
        for k in ("required", "enum", "pattern", "sensitive"):
            if f.get(k):
                item[k] = f[k]
        props.append(item)

    backing = f"ont__{oid}"
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'CREATE TABLE IF NOT EXISTS "{backing}" ({", ".join(cols)})')
    finally:
        dconn.close()

    metadata.create_object_type({
        "id": oid,
        "name": payload.get("name", oid),
        "description": payload.get("description", "通过 Ontology Manager 可视化创建"),
        "backing_table": backing,
        "primary_key": pk,
        "properties": json.dumps(props),
        "project_id": payload.get("project_id"),
    })
    metadata.ensure_crud_actions(oid, props, pk)
    return {"object_type": oid, "columns": len(props), "backing_table": backing}


# ---- D2 对象类型导出 / 导入 / 克隆（备份与迁移） ----
def export_object_type(type_id: str, include_data: bool = True):
    ot = metadata.get_object_type(type_id)
    if not ot:
        raise ValueError("对象类型不存在")
    props = json.loads(ot["properties"])
    fields = []
    for p in props:
        f = {"key": p["key"], "type": p["type"], "title": p.get("title", p["key"])}
        for k in ("required", "enum", "pattern", "sensitive"):
            if p.get(k):
                f[k] = p[k]
        fields.append(f)
    definition = {
        "id": ot["id"], "name": ot.get("name"), "description": ot.get("description", ""),
        "primary_key": ot["primary_key"], "fields": fields,
    }
    rows = []
    if include_data:
        dconn = db.get_duckdb()
        try:
            cur = dconn.execute(f'SELECT * FROM "{ot["backing_table"]}"')
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            dconn.close()
    return {"definition": definition, "rows": rows}


def import_object_type(definition: dict, rows: list = None):
    res = create_object_type_from_def(definition)
    oid = res["object_type"]
    if rows:
        dconn = db.get_duckdb()
        try:
            cur = dconn.execute(f'SELECT * FROM "ont__{oid}" LIMIT 0')
            cols = [d[0] for d in cur.description]
            dconn.executemany(
                f'INSERT INTO "ont__{oid}" ({",".join(f'"{c}"' for c in cols)}) VALUES ({",".join(["?"]*len(cols))})',
                [[r.get(c) for c in cols] for r in rows],
            )
        finally:
            dconn.close()
    return {"object_type": oid, "rows": len(rows or [])}


def clone_object_type(src_id: str, new_id: str, include_data: bool = True):
    data = export_object_type(src_id, include_data)
    data["definition"]["id"] = new_id
    data["definition"]["name"] = data["definition"].get("name") or new_id
    res = import_object_type(data["definition"], data["rows"] if include_data else None)
    metadata.log_activity("type", f"克隆对象类型 {src_id} → {new_id}")
    return res
