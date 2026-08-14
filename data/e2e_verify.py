import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
"""端到端闭环验证：本体创建→数据加载→灌入→实例化→可视化→智能体→消费→动作→回写。"""
import json
import urllib.request
import urllib.error

BASE = "http://localhost:8000"
PASS, FAIL = [], []


def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'} {name} {extra}")


def login(u, p):
    req = urllib.request.Request(
        f"{BASE}/api/auth/login", data=json.dumps({"username": u, "password": p}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req))["access_token"]


def call(method, path, token, body=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}


def upload_csv(token, object_type_id, csv_path):
    """multipart 上传 CSV 接入（模拟前端 connectors/ingest）。"""
    import uuid, os
    boundary = "----ontic" + uuid.uuid4().hex
    parts = []
    def field(name, value):
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    field("connector_type", "csv")
    field("object_type_id", object_type_id)
    field("primary_key", "id")
    field("config", "{}")
    fn = os.path.basename(csv_path)
    data = open(csv_path, "rb").read()
    parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fn}\"\r\nContent-Type: text/csv\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(f"{BASE}/api/connectors/ingest", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        r = urllib.request.urlopen(req)
        return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except Exception: return e.code, {}


admin = login("admin", "admin123")
H = {"Authorization": f"Bearer {admin}"}

print("=" * 60)
print("① 数据加载 + 灌入（CSV 连接器 → 自动注册对象类型）")
s, r = upload_csv(admin, "supplier", os.path.join(ROOT, "data", "demo", "supplier.csv"))
check("supplier CSV 接入", s == 200, str(r)[:80])
s, r = upload_csv(admin, "purchase_order", os.path.join(ROOT, "data", "demo", "purchase_order.csv"))
check("purchase_order CSV 接入", s == 200, str(r)[:80])

print("② 本体创建（自动 CRUD 动作 + 链接类型）")
s, acts = call("GET", "/api/ontology/actions", admin)
po_actions = [a["id"] for a in acts if a["object_type"] == "purchase_order"]
check("purchase_order CRUD 动作自动生成", any(x in po_actions for x in ("purchase_order__create", "purchase_order__update", "purchase_order__delete")), str(po_actions)[:80])
for lk in [{"id": "po_supplier", "name": "PO Supplier", "source_type": "purchase_order", "target_type": "supplier", "source_fk": "supplier_id"},
           {"id": "po_product", "name": "PO Product", "source_type": "purchase_order", "target_type": "product", "source_fk": "product_id"}]:
    s, r = call("POST", "/api/ontology/link-types", admin, lk)
    check(f"链接 {lk['id']} 创建", s == 200, str(r)[:60])

print("③ 实例化（查询 + 链接遍历）")
s, r = call("POST", "/api/ontology/object-types/purchase_order/count", admin, {})
check("purchase_order 灌入 10 行", r.get("total") == 10, f"total={r.get('total')}")
s, r = call("POST", "/api/ontology/object-types/purchase_order/query", admin,
            {"where": {"op": "eq", "field": "supplier_id", "value": 1}, "limit": 5})
check("按外键查询实例", s == 200 and len(r.get("rows", [])) >= 3, f"rows={len(r.get('rows', []))}")
s, r = call("GET", "/api/ontology/object-types/purchase_order/1/links/po_supplier", admin)
sup = r.get("rows") or []
check("链接遍历 PO#1 → supplier", s == 200 and sup and sup[0].get("name") == "华北供应", str(sup)[:60])

print("④ 可视化（Dashboard / Kanban / View 应用）")
apps = [("po_dash", "采购仪表盘", "dashboard", {"metric": {"field": "amount", "agg": "sum"}, "group_by": "status", "limit": 10}),
        ("po_board", "采购看板", "kanban", {"group_by": "status", "card_fields": ["id", "supplier_id", "amount", "status"]}),
        ("po_view", "采购视图", "view", {"limit": 50})]
for aid, aname, atyp, cfg in apps:
    s, r = call("POST", "/api/apps", admin, {"id": aid, "name": aname, "type": atyp, "object_type": "purchase_order", "config": cfg})
    check(f"应用 {aid}({atyp}) 创建", s == 200, str(r)[:50])
    if s == 200:
        s2, r2 = call("GET", f"/api/apps/{aid}/data", admin)
        check(f"应用 {aid} data", s2 == 200 and len(r2.get("rows", [])) > 0, f"rows={len(r2.get('rows', []))}")

print("⑤ 智能体创建 + 本体消费（AIP 识别新类型）")
s, r = call("POST", "/api/aip/threads", admin, {"name": "采购分析"})
tid = r.get("thread_id") or r.get("id")
check("AIP 会话创建", s == 200 and tid, f"tid={tid}")
s, r = call("POST", f"/api/aip/threads/{tid}/chat", admin, {"message": "查 purchase_order"})
check("AIP 识别新类型 purchase_order", s == 200 and r.get("tool") == "query_object_set", f"tool={r.get('tool')}")
s, r = call("POST", f"/api/aip/threads/{tid}/chat", admin, {"message": "查 supplier 和 purchase_order"})
check("AIP 链式查 supplier+purchase_order", s == 200 and r.get("tool") == "__multi__", f"tool={r.get('tool')}")
s, r = call("POST", f"/api/aip/threads/{tid}/chat", admin, {"message": "purchase_order 状态为 shipped 的"})
multi = r.get("reply", "") if s == 200 else ""
check("AIP 状态过滤查询", "shipped" in multi.lower() or r.get("tool") == "query_object_set", multi[:60])

print("⑥ 动作执行 + 数据回写")
s, r = call("POST", "/api/ontology/actions/purchase_order__update/execute", admin,
            {"params": {"id": 1, "status": "delivered"}})
check("执行 update 动作", s == 200, str(r)[:60])
s, r = call("POST", "/api/ontology/object-types/purchase_order/query", admin,
            {"where": {"op": "eq", "field": "id", "value": 1}, "limit": 1})
rows = r.get("rows", [])
check("回写验证 status=delivered", s == 200 and rows and rows[0].get("status") == "delivered", str(rows)[:70])
s, r = call("GET", "/api/activity", admin)
has_log = any("purchase_order#1" in (a.get("message") or "") for a in r)
check("变更历史含对象 id（purchase_order#1）", has_log)

print("=" * 60)
print(f"结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
if FAIL:
    print("FAIL 项:", FAIL)
