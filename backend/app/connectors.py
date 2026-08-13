"""连接器框架（M4）：可插拔接入外部数据源并自动注册为 Ontology 对象。

内置连接器：
- csv        ：上传 CSV 文件（read_csv_auto）
- json       ：上传 JSON 文件（read_json_auto）
- parquet    ：上传 Parquet 文件（read_parquet）
- rest       ：通过 HTTP 拉取 JSON（无需第三方库，使用标准库 urllib）
- postgres   ：通过 DuckDB postgres 扩展挂载远端表（需扩展+网络；失败会给出明确提示）

每个连接器在 REGISTRY 中声明自己的配置字段（供前端动态渲染表单），
run_* 函数把数据落进 DuckDB 后复用 ingestion 的注册逻辑。
"""
import json
import os
import tempfile
import urllib.request
from . import db, ingestion
from .ontology import metadata


# 连接器注册表：id -> {name, description, file_based(bool), fields:[{key,label,type}]}
REGISTRY = {
    "csv": {
        "name": "CSV 文件",
        "description": "上传 CSV（首行为表头），自动推导类型并注册对象类型。",
        "file_based": True,
        "fields": [],
    },
    "json": {
        "name": "JSON 文件",
        "description": "上传 JSON（数组或对象），自动展开为表并注册对象类型。",
        "file_based": True,
        "fields": [],
    },
    "parquet": {
        "name": "Parquet 文件",
        "description": "上传 Parquet 文件，零拷贝读入并注册对象类型。",
        "file_based": True,
        "fields": [],
    },
    "rest": {
        "name": "REST API",
        "description": "通过 HTTP GET 拉取 JSON 响应并注册为对象类型。",
        "file_based": False,
        "fields": [
            {"key": "url", "label": "API URL", "type": "text"},
            {"key": "json_path", "label": "JSON 路径(可选, 如 data.items)", "type": "text"},
            {"key": "method", "label": "方法(默认 GET)", "type": "text"},
        ],
    },
    "postgres": {
        "name": "PostgreSQL",
        "description": "挂载远端 Postgres 表（需 DuckDB postgres 扩展与网络）。",
        "file_based": False,
        "fields": [
            {"key": "host", "label": "主机", "type": "text"},
            {"key": "port", "label": "端口(默认5432)", "type": "text"},
            {"key": "dbname", "label": "数据库", "type": "text"},
            {"key": "user", "label": "用户", "type": "text"},
            {"key": "password", "label": "密码", "type": "password"},
            {"key": "table", "label": "表名", "type": "text"},
        ],
    },
}


def list_connectors():
    return [{"id": k, **v} for k, v in REGISTRY.items()]


def _load_file_via_sql(object_type_id: str, sql_from_file: str, tmp_path: str, description: str):
    """通用：用一条 DuckDB 读文件 SQL 建表并注册对象类型。"""
    backing = f"ont__{object_type_id}"
    dconn = db.get_duckdb()
    try:
        dconn.execute(f'CREATE OR REPLACE TABLE "{backing}" AS {sql_from_file}')
    finally:
        dconn.close()
    return ingestion._register_from_table(object_type_id, backing, description)


def run_csv(object_type_id: str, primary_key: str, file_bytes: bytes, filename: str):
    return ingestion.ingest_csv(object_type_id, primary_key, file_bytes, filename)


def run_json(object_type_id: str, file_bytes: bytes, filename: str):
    suffix = os.path.splitext(filename or "data.json")[1] or ".json"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file_bytes)
        tmp.close()
        sql = f"SELECT * FROM read_json_auto('{tmp.name}', format='auto', maximum_object_size=10000000)"
        return _load_file_via_sql(object_type_id, sql, tmp.name, f"JSON 接入: {filename}")
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def run_parquet(object_type_id: str, file_bytes: bytes, filename: str):
    suffix = os.path.splitext(filename or "data.parquet")[1] or ".parquet"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(file_bytes)
        tmp.close()
        sql = f"SELECT * FROM read_parquet('{tmp.name}')"
        return _load_file_via_sql(object_type_id, sql, tmp.name, f"Parquet 接入: {filename}")
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def run_rest(object_type_id: str, config: dict):
    url = config.get("url")
    if not url:
        raise ValueError("REST 连接器需要 url")
    method = (config.get("method") or "GET").upper()
    req = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read().decode("utf-8")
    parsed = json.loads(data)
    jpath = (config.get("json_path") or "").strip()
    if jpath:
        for seg in jpath.split("."):
            if seg:
                parsed = parsed[seg]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    try:
        json.dump(parsed, tmp)
        tmp.close()
        sql = f"SELECT * FROM read_json_auto('{tmp.name}', format='auto', maximum_object_size=10000000)"
        return _load_file_via_sql(object_type_id, sql, tmp.name, f"REST 接入: {url}")
    finally:
        if os.path.exists(tmp.name):
            os.unlink(tmp.name)


def run_postgres(object_type_id: str, config: dict):
    host = config.get("host"); port = config.get("port") or 5432
    dbname = config.get("dbname"); user = config.get("user")
    password = config.get("password"); table = config.get("table")
    if not all([host, dbname, user, table]):
        raise ValueError("Postgres 连接器需要 host/dbname/user/table")
    backing = f"ont__{object_type_id}"
    dconn = db.get_duckdb()
    try:
        dconn.execute("INSTALL postgres; LOAD postgres;")
        dconn.execute(
            f'CREATE OR REPLACE TABLE "{backing}" AS '
            f"SELECT * FROM postgres_scan('{host}:{port}', '{dbname}', '{user}', '{password}', '{table}')"
        )
    except Exception as e:
        raise ValueError(f"Postgres 接入失败（需 DuckDB postgres 扩展与网络）: {e}")
    finally:
        dconn.close()
    return ingestion._register_from_table(object_type_id, backing, f"Postgres 接入: {table}")


def dispatch(connector_type: str, object_type_id: str, primary_key: str = "id",
             file_bytes: bytes = None, filename: str = None, config: dict = None):
    if connector_type not in REGISTRY:
        raise ValueError(f"未知连接器: {connector_type}")
    if connector_type == "csv":
        return run_csv(object_type_id, primary_key, file_bytes, filename)
    if connector_type == "json":
        return run_json(object_type_id, file_bytes, filename)
    if connector_type == "parquet":
        return run_parquet(object_type_id, file_bytes, filename)
    if connector_type == "rest":
        return run_rest(object_type_id, config or {})
    if connector_type == "postgres":
        return run_postgres(object_type_id, config or {})
    raise ValueError("未实现")
