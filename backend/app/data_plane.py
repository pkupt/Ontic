"""M11 数据平面增强：SQL 工作台 / 时空查询 / 媒体存储 / 引擎信息。

对齐 Foundry 数据能力原型：
  - SQL 工作台（80151836 / 87629022）：只读 SELECT 直接打到 DuckDB，
    白名单限制表（仅 ont__ 前缀的注册对象类型表），返回列/行/耗时。
  - 时空查询（Geospatial）：对含 lat/lng 的对象类型做半径内邻近查询（Haversine）。
  - 媒体/附件（Attachment）：文件上传、列表、按名访问（存 data/media）。
  - 数据平面引擎：当前 DuckDB；Iceberg / Trino 列为规划（文档化可扩展点）。
"""
import time
import math
import re
import json
import datetime
from pathlib import Path

from . import db, config
from .ontology import metadata

_FROM_RE = re.compile(r"\bfrom\s+([`\"\[]?)([a-zA-Z_][a-zA-Z0-9_]*)\1", re.IGNORECASE)
MAX_ROWS = 500


def run_sql(sql: str):
    s = (sql or "").strip()
    if not s.lower().startswith("select"):
        raise ValueError("仅支持只读 SELECT 查询")
    if ";" in s:
        raise ValueError("不支持多语句 / 分号")
    # 表白名单：仅允许已注册对象类型的 backing table（ont__xxx）或管道快照表（ont__xxx__snap_<id>）
    tables = {m.group(2) for m in _FROM_RE.finditer(s)}
    if not tables:
        raise ValueError("查询必须包含 FROM 表")
    known = {ot["backing_table"] for ot in metadata.list_object_types()}
    snap_re = re.compile(r"^ont__.+__(snap_\d+|ckpt_\d+|branch_[a-zA-Z0-9_]+)$")
    for t in tables:
        if t not in known and not snap_re.match(t):
            raise ValueError(f"表不在白名单内: {t}（仅可查询已注册对象类型表或版本快照/检查点/分支表）")
    dconn = db.get_duckdb()
    try:
        t0 = time.time()
        cur = dconn.execute(s)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchmany(MAX_ROWS)]
        elapsed = round((time.time() - t0) * 1000, 1)
    finally:
        dconn.close()
    return {"columns": cols, "rows": rows, "count": len(rows), "elapsed_ms": elapsed, "limited": len(rows) >= MAX_ROWS}


def _haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def geo_near(type_id: str, lat: float, lng: float, radius_km: float = 50.0):
    """在含 lat/lng 字段的对象类型上做半径内邻近查询。"""
    ot = metadata.get_object_type(type_id)
    if not ot:
        raise ValueError("对象类型不存在")
    props = json.loads(ot["properties"])
    lat_col = next((p["column"] for p in props if "lat" in p["key"].lower() or p["key"] in ("lat", "latitude")), None)
    lng_col = next((p["column"] for p in props if "lng" in p["key"].lower() or p["key"] in ("lon", "longitude", "lng")), None)
    if not lat_col or not lng_col:
        raise ValueError("该对象类型没有 lat/lng 坐标字段")
    name_col = next((p["column"] for p in props if p["type"] == "string" and p["key"] not in (lat_col, lng_col)), None)
    dconn = db.get_duckdb()
    try:
        cur = dconn.execute(f'SELECT * FROM {ot["backing_table"]}')
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        dconn.close()
    results = []
    for r in rows:
        v1, v2 = r.get(lat_col), r.get(lng_col)
        try:
            d = _haversine(float(v1), float(v2), lat, lng)
        except (TypeError, ValueError):
            continue
        if d <= radius_km:
            results.append({
                "id": r.get(ot["primary_key"]),
                "name": r.get(name_col) if name_col else None,
                "distance_km": round(d, 2),
            })
    results.sort(key=lambda x: x["distance_km"])
    return {"object_type": type_id, "center": {"lat": lat, "lng": lng}, "radius_km": radius_km,
            "count": len(results), "results": results}


MEDIA_DIR = config.DATA_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


def save_media(filename: str, data: bytes):
    safe = Path(filename or "file").name
    target = MEDIA_DIR / safe
    target.write_bytes(data)
    return {"name": safe, "size": len(data), "path": str(target)}


def list_media():
    out = []
    for f in sorted(MEDIA_DIR.iterdir()):
        if f.is_file():
            out.append({"name": f.name, "size": f.stat().st_size, "modified": f.stat().st_mtime})
    return out


def engines():
    return [
        {"id": "duckdb", "name": "DuckDB", "status": "active", "note": "默认数据平面（列式分析，物化 ont__* 表）"},
        {"id": "iceberg", "name": "Apache Iceberg", "status": "planned", "note": "规划：DuckDB iceberg 扩展读取开放表格式"},
        {"id": "trino", "name": "Trino", "status": "planned", "note": "规划：联邦查询引擎接入"},
    ]


# ---- 自定义 API 端点（custom-endpoints）：只读 SQL → 开放 REST 端点 ----
def create_endpoint(defn: dict):
    """创建自定义端点：SQL 只读校验通过后存入 endpoints 表。"""
    eid = (defn.get("id") or "").strip()
    path = (defn.get("path") or "").strip()
    method = (defn.get("method") or "GET").upper()
    sql = (defn.get("sql") or "").strip()
    if not eid or not path or not sql:
        raise ValueError("id / path / sql 必填")
    if not path.startswith("/custom/"):
        raise ValueError("自定义端点路径必须以 /custom/ 开头")
    if method not in ("GET", "POST"):
        raise ValueError("仅支持 GET/POST")
    run_sql(sql)  # 创建即校验（只读 + 表白名单）
    conn = db.get_metadata_conn()
    conn.execute(
        "INSERT OR REPLACE INTO endpoints (id, path, method, sql, description, created) VALUES (?,?,?,?,?,?)",
        (eid, path, method, sql, defn.get("description", ""),
         datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    conn.commit()
    conn.close()
    return {"ok": True, "id": eid, "path": path, "method": method}


def list_endpoints():
    conn = db.get_metadata_conn()
    rows = conn.execute("SELECT id, path, method, sql, description, created FROM endpoints ORDER BY path").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_endpoint(eid: str):
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM endpoints WHERE id=?", (eid,))
    conn.commit()
    conn.close()


def register_endpoint(app, ep: dict):
    """把一条自定义端点动态注册到 FastAPI（启动时 + 创建时调用）。"""
    from fastapi import Depends
    from .main import get_current_user  # 复用统一鉴权（惰性导入避免循环）

    def _handler(user: str = Depends(get_current_user)):
        try:
            return run_sql(ep["sql"])
        except ValueError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=str(e))

    app.add_api_route(ep["path"], _handler, methods=[ep["method"]], tags=["custom"])
    # 关键：动态路由排在最后（SPA catch-all 之后），必须移到 catch-all 之前才会被命中
    routes = app.router.routes
    catch = next((i for i, r in enumerate(routes) if getattr(r, "path", "") == "/{full_path:path}"), None)
    if catch is not None and routes[-1] is not routes[catch]:
        route = routes.pop()
        routes.insert(catch, route)


def delete_media(name: str):
    """删除媒体文件（路径穿越防护：仅允许文件名）。"""
    import os
    if "/" in name or "\\" in name or ".." in name:
        raise ValueError("非法文件名")
    p = MEDIA_DIR / name
    if not p.is_file():
        raise ValueError("媒体不存在")
    try:
        p.unlink()
    except OSError as e:
        raise ValueError(f"删除失败（文件系统拒绝）：{e}") from e
    return {"ok": True, "deleted": name}
