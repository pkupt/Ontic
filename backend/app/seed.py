"""演示种子数据：建一张 Customer 对象 + 两个动作，并灌入样例行。

幂等：若对象类型已存在则跳过；仅在表为空时灌数据。用于让"导入表→建对象→
查询→执行动作"这条端到端主轴在本地一键可见。
"""
import json
from . import db, config
from .ontology import metadata


CUSTOMER_TYPE = {
    "id": "customer",
    "name": "Customer",
    "description": "示例客户对象，用于演示 Ontology 端到端链路",
    "backing_table": "ont__customer",
    "primary_key": "id",
    "properties": json.dumps([
        {"key": "id", "column": "id", "type": "integer", "title": "ID"},
        {"key": "name", "column": "name", "type": "string", "title": "姓名"},
        {"key": "email", "column": "email", "type": "string", "title": "邮箱"},
        {"key": "status", "column": "status", "type": "string", "title": "状态"},
        {"key": "age", "column": "age", "type": "integer", "title": "年龄"},
        {"key": "region", "column": "region", "type": "string", "title": "地区"},
    ]),
}

CREATE_ACTION = {
    "id": "create_customer",
    "name": "Create Customer",
    "description": "新建一个客户",
    "object_type": "customer",
    "operation": "create",
    "parameters": json.dumps([
        {"name": "name", "type": "string", "required": True},
        {"name": "email", "type": "string", "required": True},
        {"name": "status", "type": "string", "required": False},
        {"name": "age", "type": "integer", "required": False},
        {"name": "region", "type": "string", "required": False},
    ]),
}

DEACTIVATE_ACTION = {
    "id": "deactivate_customer",
    "name": "Deactivate Customer",
    "description": "将客户状态置为 inactive",
    "object_type": "customer",
    "operation": "update",
    "parameters": json.dumps([
        {"name": "id", "type": "integer", "required": True},
        {"name": "status", "type": "string", "required": False},
    ]),
}


def seed():
    metadata.init_metadata()
    # 幂等：对象类型已存在则跳过建表/灌数据
    if not metadata.get_object_type("customer"):
        metadata.create_object_type(CUSTOMER_TYPE)
        metadata.create_action(CREATE_ACTION)
        metadata.create_action(DEACTIVATE_ACTION)
        metadata.ensure_crud_actions("customer", json.loads(CUSTOMER_TYPE["properties"]))

        dconn = db.get_duckdb()
        dconn.execute(
            """
            CREATE TABLE IF NOT EXISTS ont__customer (
                id INTEGER PRIMARY KEY,
                name VARCHAR,
                email VARCHAR,
                status VARCHAR,
                age INTEGER,
                region VARCHAR
            )
            """
        )
        rows = dconn.execute("SELECT count(*) FROM ont__customer").fetchone()[0]
        if rows == 0:
            sample = [
                [1, "Alice Chen", "alice@example.com", "active", 34, "APAC"],
                [2, "Bob Liu", "bob@example.com", "active", 41, "EMEA"],
                [3, "Carol Wang", "carol@example.com", "inactive", 29, "APAC"],
                [4, "David Zhao", "david@example.com", "active", 52, "AMER"],
            ]
            dconn.executemany("INSERT INTO ont__customer VALUES (?,?,?,?,?,?)", sample)
        dconn.close()
        print("[seed] 已创建 customer 对象、动作并灌入 4 行样例数据。")

    # 幂等兜底：为所有已注册对象类型补齐 create/update/delete 标准动作，
    # 保证既有数据（CSV 接入 / 转换生成的）也具备完整 CRUD 写能力。
    for ot in metadata.list_object_types():
        metadata.ensure_crud_actions(ot["id"], json.loads(ot["properties"]), ot["primary_key"])

    # M2 演示：region 对象类型 + customer→region 链接（外键 = customer.region 引用 region.code）
    REGION_TYPE = {
        "id": "region",
        "name": "Region",
        "description": "地区对象，演示链接类型与图遍历",
        "backing_table": "ont__region",
        "primary_key": "code",
        "properties": json.dumps([
            {"key": "code", "column": "code", "type": "string", "title": "代码"},
            {"key": "name", "column": "name", "type": "string", "title": "名称"},
            {"key": "manager", "column": "manager", "type": "string", "title": "负责人"},
        ]),
    }
    if not metadata.get_object_type("region"):
        metadata.create_object_type(REGION_TYPE)
        metadata.ensure_crud_actions("region", json.loads(REGION_TYPE["properties"]), "code")
        dconn = db.get_duckdb()
        dconn.execute(
            "CREATE TABLE IF NOT EXISTS ont__region (code VARCHAR PRIMARY KEY, name VARCHAR, manager VARCHAR)"
        )
        if dconn.execute("SELECT count(*) FROM ont__region").fetchone()[0] == 0:
            dconn.executemany(
                "INSERT INTO ont__region VALUES (?,?,?)",
                [["APAC", "亚太", "Wang"], ["EMEA", "欧非中东", "Schmidt"], ["AMER", "美洲", "Garcia"]],
            )
        dconn.close()
    if not metadata.get_link_type("customer_region"):
        metadata.create_link_type({
            "id": "customer_region",
            "name": "Customer Region",
            "source_type": "customer",
            "target_type": "region",
            "source_fk": "region",
        })
        print("[seed] 已创建 region 对象类型与 customer→region 链接类型。")

    # S6 治理演示：一个受限用户，仅对 product 有读写权限，无权访问 customer。
    metadata.create_user("analyst", "analyst123", "analyst")
    metadata.grant("analyst", "product", "write")
    print("[seed] 已确保所有对象类型的 CRUD 动作齐备，并创建了受限用户 analyst。")

    # 通知中心初始内容（仅当活动日志为空时写入，保持幂等）
    conn = db.get_metadata_conn()
    has_activity = conn.execute("SELECT count(*) FROM activity").fetchone()[0] > 0
    conn.close()
    if not has_activity:
        types_n = len(metadata.list_object_types())
        for msg in [
            f"平台初始化完成：已注册 {types_n} 个对象类型、{len(metadata.list_link_types())} 个链接类型",
            "S6 治理演示就绪：受限用户 analyst 已创建（仅 product 读写）",
            "示例数据已灌入：customer（4 行）/ region（3 行）",
        ]:
            metadata.log_activity("system", msg)

    # M11 时空演示：city 类型（lat/lng）
    if not metadata.get_object_type("city"):
        metadata.create_object_type({
            "id": "city", "name": "City", "description": "城市坐标（时空查询演示）",
            "backing_table": "ont__city", "primary_key": "id",
            "properties": json.dumps([
                {"key": "id", "column": "id", "type": "integer", "title": "ID"},
                {"key": "name", "column": "name", "type": "string", "title": "城市"},
                {"key": "lat", "column": "lat", "type": "double", "title": "纬度"},
                {"key": "lng", "column": "lng", "type": "double", "title": "经度"},
            ]),
        })
        metadata.ensure_crud_actions("city", json.loads(
            metadata.get_object_type("city")["properties"]))
        dconn = db.get_duckdb()
        dconn.execute("CREATE TABLE IF NOT EXISTS ont__city (id INTEGER PRIMARY KEY, name VARCHAR, lat DOUBLE, lng DOUBLE)")
        if dconn.execute("SELECT count(*) FROM ont__city").fetchone()[0] == 0:
            dconn.executemany("INSERT INTO ont__city VALUES (?,?,?,?)", [
                [1, "北京", 39.90, 116.40], [2, "上海", 31.23, 121.47],
                [3, "广州", 23.13, 113.26], [4, "深圳", 22.54, 114.06],
                [5, "杭州", 30.27, 120.15], [6, "香港", 22.32, 114.17],
                [7, "成都", 30.67, 104.07], [8, "乌鲁木齐", 43.83, 87.62],
            ])
        dconn.close()
        print("[seed] 已创建 city 对象类型（时空查询演示，8 行）。")


if __name__ == "__main__":
    seed()
