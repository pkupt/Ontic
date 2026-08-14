"""C3 市场安装包（对齐 marketplace 分区）：可安装 bundle。

包定义包含：对象类型定义、动作定义、应用定义。安装 = 逐一注册并记录；
卸载 = 删除包内应用与对象类型（及其数据表）。支持版本与已装状态查询。
"""
import datetime

from . import db
from . import ingestion, app_platform
from .ontology import metadata

# 内置包：对象类型定义沿用 create_object_type_from_def 的字段格式
PACKAGES = [
    {
        "id": "customer-mgmt",
        "name": "客户管理包",
        "version": "1.0.0",
        "category": "业务",
        "description": "Customer 对象类型 + 标准 CRUD 动作 + 客户仪表盘应用。",
        "object_types": [
            {
                "id": "lead", "name": "Lead", "description": "销售线索（市场包）",
                "primary_key": "id",
                "fields": [
                    {"key": "id", "type": "integer", "title": "ID"},
                    {"key": "name", "type": "string", "title": "姓名", "required": True},
                    {"key": "company", "type": "string", "title": "公司"},
                    {"key": "stage", "type": "string", "title": "阶段", "enum": ["new", "contacted", "qualified", "won"]},
                ],
            }
        ],
        "actions": [],
        "apps": [
            {"id": "pkg_lead_dash", "name": "线索仪表盘", "type": "dashboard", "object_type": "lead",
             "config": {"metric": {"field": "id", "agg": "count"}, "group_by": "stage", "limit": 8}},
        ],
    },
    {
        "id": "inventory",
        "name": "库存追踪包",
        "version": "0.9.0",
        "category": "供应链",
        "description": "Stock 对象类型 + 低库存视图应用（演示市场升级路径）。",
        "object_types": [
            {
                "id": "stock", "name": "Stock", "description": "库存记录（市场包）",
                "primary_key": "sku",
                "fields": [
                    {"key": "sku", "type": "string", "title": "SKU", "required": True, "pattern": "^[A-Z0-9-]+$"},
                    {"key": "name", "type": "string", "title": "品名"},
                    {"key": "qty", "type": "integer", "title": "数量"},
                    {"key": "warehouse", "type": "string", "title": "仓库", "enum": ["SH", "BJ", "GZ"]},
                ],
            }
        ],
        "actions": [],
        "apps": [
            {"id": "pkg_stock_view", "name": "低库存视图", "type": "view", "object_type": "stock",
             "config": {"where": {"op": "lt", "field": "qty", "value": 10}, "limit": 100}},
        ],
    },
]


def _now():
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def catalog():
    conn = db.get_metadata_conn()
    installed = {dict(r)["id"]: dict(r)["version"] for r in conn.execute("SELECT id, version FROM installed_packages").fetchall()}
    conn.close()
    out = []
    for p in PACKAGES:
        out.append({
            "id": p["id"], "name": p["name"], "version": p["version"], "category": p.get("category", ""),
            "description": p["description"],
            "installed": p["id"] in installed,
            "installed_version": installed.get(p["id"]),
            "types": len(p["object_types"]), "apps": len(p["apps"]),
        })
    return out


def install(package_id: str):
    pkg = next((p for p in PACKAGES if p["id"] == package_id), None)
    if not pkg:
        raise ValueError("包不存在")
    conn = db.get_metadata_conn()
    if conn.execute("SELECT 1 FROM installed_packages WHERE id=?", (package_id,)).fetchone():
        conn.close()
        raise ValueError("该包已安装")
    conn.close()
    created = {"types": [], "apps": []}
    for tdef in pkg["object_types"]:
        if metadata.get_object_type(tdef["id"]):
            raise ValueError(f"对象类型已存在，无法安装: {tdef['id']}")
        res = ingestion.create_object_type_from_def(tdef)
        created["types"].append(tdef["id"])
    for adef in pkg.get("actions", []):
        metadata.create_action(adef)
    for adef in pkg.get("apps", []):
        app_platform.create_app(adef)
        created["apps"].append(adef["id"])
    conn = db.get_metadata_conn()
    conn.execute("INSERT INTO installed_packages (id, name, version, installed_at) VALUES (?,?,?,?)",
                 (pkg["id"], pkg["name"], pkg["version"], _now()))
    conn.commit()
    conn.close()
    metadata.log_activity("marketplace", f"安装市场包 {pkg['id']} v{pkg['version']}")
    return {"package": package_id, "version": pkg["version"], "created": created}


def uninstall(package_id: str):
    pkg = next((p for p in PACKAGES if p["id"] == package_id), None)
    if not pkg:
        raise ValueError("包不存在")
    conn = db.get_metadata_conn()
    row = conn.execute("SELECT * FROM installed_packages WHERE id=?", (package_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("该包未安装")
    removed = {"apps": [], "types": []}
    for adef in pkg.get("apps", []):
        app_platform.delete_app(adef["id"])
        removed["apps"].append(adef["id"])
    for tdef in pkg["object_types"]:
        try:
            metadata.delete_object_type(tdef["id"])
            removed["types"].append(tdef["id"])
        except ValueError:
            pass
    conn = db.get_metadata_conn()
    conn.execute("DELETE FROM installed_packages WHERE id=?", (package_id,))
    conn.commit()
    conn.close()
    metadata.log_activity("marketplace", f"卸载市场包 {package_id}")
    return {"package": package_id, "removed": removed}
