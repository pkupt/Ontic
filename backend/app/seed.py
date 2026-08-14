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

    # ---- 补充 demo 数据：product + order + 多跳链接（让本体实例化与链接可视化有充足素材）----
    PRODUCT_TYPE = {
        "id": "product", "name": "Product", "description": "产品对象（订单关联）",
        "backing_table": "ont__product", "primary_key": "id",
        "properties": json.dumps([
            {"key": "id", "column": "id", "type": "integer", "title": "ID"},
            {"key": "name", "column": "name", "type": "string", "title": "名称"},
            {"key": "category", "column": "category", "type": "string", "title": "品类"},
            {"key": "price", "column": "price", "type": "double", "title": "价格"},
            {"key": "stock", "column": "stock", "type": "integer", "title": "库存"},
            {"key": "status", "column": "status", "type": "string", "title": "状态", "enum": ["active", "inactive"]},
        ]),
    }
    if not metadata.get_object_type("product"):
        metadata.create_object_type(PRODUCT_TYPE)
        metadata.ensure_crud_actions("product", json.loads(PRODUCT_TYPE["properties"]))
        dconn = db.get_duckdb()
        dconn.execute(
            "CREATE TABLE IF NOT EXISTS ont__product (id INTEGER PRIMARY KEY, name VARCHAR, category VARCHAR, price DOUBLE, stock INTEGER, status VARCHAR)"
        )
        _prod_rows = [
            [1, "Foundry Starter", "软件", 9800.0, 120, "active"],
            [2, "Ontic Pro", "软件", 19800.0, 85, "active"],
            [3, "数据集成套件", "服务", 35000.0, 40, "active"],
            [4, "AIP 分析师", "软件", 8800.0, 200, "active"],
            [5, "安全审计包", "服务", 42000.0, 25, "active"],
            [6, "管道构建器", "软件", 12800.0, 95, "active"],
            [7, "运维监控", "软件", 6800.0, 150, "inactive"],
            [8, "培训认证", "服务", 5800.0, 300, "active"],
            [9, "开发者工具包", "软件", 3800.0, 220, "active"],
            [10, "企业支持", "服务", 88000.0, 15, "active"],
        ]
        dconn.executemany("INSERT INTO ont__product VALUES (?,?,?,?,?,?)", _prod_rows)
        dconn.close()
        print("[seed] 已创建 product 对象类型（10 行）。")
    else:
        # 已存在：确保 category/status 列 + 补齐 id 4-10（order 需要关联到这些产品）
        dconn = db.get_duckdb()
        cols = {r[1] for r in dconn.execute("PRAGMA table_info(ont__product)").fetchall()}
        for col, typ in (("category", "VARCHAR"), ("status", "VARCHAR")):
            if col not in cols:
                try:
                    dconn.execute(f"ALTER TABLE ont__product ADD COLUMN {col} {typ}")
                except Exception:
                    pass
        # ALTER 后重新查列，按现有列动态对齐插入
        avail = [r[1] for r in dconn.execute("PRAGMA table_info(ont__product)").fetchall()]
        existing = {r[0] for r in dconn.execute("SELECT id FROM ont__product").fetchall()}
        for pdata in [
            {"id":4,"name":"AIP 分析师","category":"软件","price":8800.0,"stock":200,"status":"active"},
            {"id":5,"name":"安全审计包","category":"服务","price":42000.0,"stock":25,"status":"active"},
            {"id":6,"name":"管道构建器","category":"软件","price":12800.0,"stock":95,"status":"active"},
            {"id":7,"name":"运维监控","category":"软件","price":6800.0,"stock":150,"status":"inactive"},
            {"id":8,"name":"培训认证","category":"服务","price":5800.0,"stock":300,"status":"active"},
            {"id":9,"name":"开发者工具包","category":"软件","price":3800.0,"stock":220,"status":"active"},
            {"id":10,"name":"企业支持","category":"服务","price":88000.0,"stock":15,"status":"active"},
        ]:
            if pdata["id"] not in existing:
                use = [c for c in avail if c in pdata]
                ph = ",".join(["?"] * len(use))
                dconn.execute(f"INSERT INTO ont__product ({','.join(use)}) VALUES ({ph})", [pdata[c] for c in use])
        dconn.close()
        print(f"[seed] product 已存在，补齐至 {len(existing | {4,5,6,7,8,9,10})} 行。")

    ORDER_TYPE = {
        "id": "order", "name": "Order", "description": "订单对象（关联客户与产品，多跳链接演示）",
        "backing_table": "ont__order", "primary_key": "id",
        "properties": json.dumps([
            {"key": "id", "column": "id", "type": "integer", "title": "ID"},
            {"key": "customer_id", "column": "customer_id", "type": "integer", "title": "客户ID"},
            {"key": "product_id", "column": "product_id", "type": "integer", "title": "产品ID"},
            {"key": "amount", "column": "amount", "type": "double", "title": "金额"},
            {"key": "qty", "column": "qty", "type": "integer", "title": "数量"},
            {"key": "status", "column": "status", "type": "string", "title": "状态", "enum": ["pending", "paid", "shipped", "done"]},
        ]),
    }
    if not metadata.get_object_type("order"):
        metadata.create_object_type(ORDER_TYPE)
        metadata.ensure_crud_actions("order", json.loads(ORDER_TYPE["properties"]))
        dconn = db.get_duckdb()
        dconn.execute(
            "CREATE TABLE IF NOT EXISTS ont__order (id INTEGER PRIMARY KEY, customer_id INTEGER, product_id INTEGER, amount DOUBLE, qty INTEGER, status VARCHAR)"
        )
        _order_rows = [
            [1, 1, 1, 9800.0, 1, "done"], [2, 1, 4, 17600.0, 2, "shipped"],
            [3, 2, 2, 19800.0, 1, "paid"], [4, 2, 6, 12800.0, 1, "paid"],
            [5, 3, 8, 11600.0, 2, "pending"], [6, 3, 9, 7600.0, 2, "pending"],
            [7, 4, 3, 35000.0, 1, "done"], [8, 4, 5, 42000.0, 1, "shipped"],
            [9, 1, 10, 88000.0, 1, "paid"], [10, 2, 9, 3800.0, 1, "done"],
            [11, 3, 1, 9800.0, 1, "shipped"], [12, 4, 4, 8800.0, 1, "pending"],
            [13, 1, 6, 12800.0, 1, "done"], [14, 2, 8, 5800.0, 1, "paid"],
            [15, 4, 2, 19800.0, 1, "shipped"],
        ]
        dconn.executemany("INSERT INTO ont__order VALUES (?,?,?,?,?,?)", _order_rows)
        dconn.close()
        print("[seed] 已创建 order 对象类型（15 行）。")
    else:
        # 已存在：补齐 qty/status 列 + 补缺失订单行（动态列对齐）
        dconn = db.get_duckdb()
        cols = {r[1] for r in dconn.execute("PRAGMA table_info(ont__order)").fetchall()}
        for col, typ in (("qty", "INTEGER"), ("status", "VARCHAR")):
            if col not in cols:
                try:
                    dconn.execute(f"ALTER TABLE ont__order ADD COLUMN {col} {typ}")
                except Exception:
                    pass
        avail = [r[1] for r in dconn.execute("PRAGMA table_info(ont__order)").fetchall()]
        existing = {r[0] for r in dconn.execute("SELECT id FROM ont__order").fetchall()}
        for pdata in [
            {"id":1,"customer_id":1,"product_id":1,"amount":9800.0,"qty":1,"status":"done"},
            {"id":2,"customer_id":1,"product_id":4,"amount":17600.0,"qty":2,"status":"shipped"},
            {"id":3,"customer_id":2,"product_id":2,"amount":19800.0,"qty":1,"status":"paid"},
            {"id":4,"customer_id":2,"product_id":6,"amount":12800.0,"qty":1,"status":"paid"},
            {"id":5,"customer_id":3,"product_id":8,"amount":11600.0,"qty":2,"status":"pending"},
            {"id":6,"customer_id":3,"product_id":9,"amount":7600.0,"qty":2,"status":"pending"},
            {"id":7,"customer_id":4,"product_id":3,"amount":35000.0,"qty":1,"status":"done"},
            {"id":8,"customer_id":4,"product_id":5,"amount":42000.0,"qty":1,"status":"shipped"},
            {"id":9,"customer_id":1,"product_id":10,"amount":88000.0,"qty":1,"status":"paid"},
            {"id":10,"customer_id":2,"product_id":9,"amount":3800.0,"qty":1,"status":"done"},
            {"id":11,"customer_id":3,"product_id":1,"amount":9800.0,"qty":1,"status":"shipped"},
            {"id":12,"customer_id":4,"product_id":4,"amount":8800.0,"qty":1,"status":"pending"},
            {"id":13,"customer_id":1,"product_id":6,"amount":12800.0,"qty":1,"status":"done"},
            {"id":14,"customer_id":2,"product_id":8,"amount":5800.0,"qty":1,"status":"paid"},
            {"id":15,"customer_id":4,"product_id":2,"amount":19800.0,"qty":1,"status":"shipped"},
        ]:
            if pdata["id"] not in existing:
                use = [c for c in avail if c in pdata]
                ph = ",".join(["?"] * len(use))
                dconn.execute(f"INSERT INTO ont__order ({','.join(use)}) VALUES ({ph})", [pdata[c] for c in use])
        n = dconn.execute("SELECT count(*) FROM ont__order").fetchone()[0]
        dconn.close()
        print(f"[seed] order 已存在，补齐至 {n} 行。")

    # 链接：order→customer（order.customer_id 引用 customer.id）
    if not metadata.get_link_type("order_customer"):
        metadata.create_link_type({
            "id": "order_customer", "name": "Order Customer",
            "source_type": "order", "target_type": "customer", "source_fk": "customer_id",
        })
    # 链接：order→product（order.product_id 引用 product.id）
    if not metadata.get_link_type("order_product"):
        metadata.create_link_type({
            "id": "order_product", "name": "Order Product",
            "source_type": "order", "target_type": "product", "source_fk": "product_id",
        })
    # city→region 链接（时空+地区关联，丰富图探索）
    if not metadata.get_link_type("city_region"):
        metadata.create_link_type({
            "id": "city_region", "name": "City Region",
            "source_type": "city", "target_type": "region", "source_fk": "name",
        })
    _lk_n = len(metadata.list_link_types())
    if _lk_n > 1:
        print(f"[seed] 链接类型已就绪（共 {_lk_n} 个：customer→region / order→customer / order→product / city→region）。")


if __name__ == "__main__":
    seed()
