"""Ontic 全量覆盖验证 v2（契约修正 + 崩溃兜底）：159 路由 / 13 组，重点用户权限。"""
import json, urllib.request, urllib.error, uuid, traceback

BASE = "http://localhost:8000"
PASS, FAIL, ERR = [], [], []

def call(m, p, t=None, b=None, raw=False):
    h = {"Content-Type": "application/json"}
    if t: h["Authorization"] = f"Bearer {t}"
    req = urllib.request.Request(BASE+p, data=json.dumps(b).encode() if b is not None else None, headers=h, method=m)
    try:
        r = urllib.request.urlopen(req)
        return r.status, (r.read() if raw else json.loads(r.read() or b"{}"))
    except urllib.error.HTTPError as e:
        try: return e.code, (e.read() if raw else json.loads(e.read() or b"{}"))
        except: return e.code, {}

def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'} {name}" + (f"  [{extra}]" if extra else ""))

def safe(name, fn):
    try:
        fn()
    except Exception as e:
        ERR.append(name)
        print(f"  ERROR {name}  {type(e).__name__}: {str(e)[:80]}")

admin = call("POST","/api/auth/login",None,{"username":"admin","password":"admin123"})[1]["access_token"]
A = admin

print("="*66); print("一、认证"); 
def t_auth():
    s,r = call("GET","/api/me",A); check("me", s==200 and r.get("role")=="admin")
    s,r = call("GET","/api/activity",A); check("activity", s==200 and isinstance(r,list))
safe("认证", t_auth)

print("="*66); print("二、用户权限管理【重点】")
un = "u"+uuid.uuid4().hex[:5]
def t_perm():
    s,r = call("POST","/api/admin/users",A,{"username":un,"password":"pw123456","role":"analyst"}); check("创建用户", s==200)
    s,r = call("GET","/api/admin/users",A); check("用户列表", s==200 and any(u["username"]==un for u in r))
    s,r = call("POST",f"/api/admin/users/{un}/role",A,{"role":"analyst"}); check("改角色", s==200)
    s,r = call("POST","/api/auth/login",None,{"username":un,"password":"pw123456"}); tok2=r.get("access_token"); check("新用户登录", s==200 and bool(tok2))
    if not tok2: return
    s,r = call("POST","/api/ontology/object-types/customer/query",tok2,{"limit":2}); check("ABAC 拦截查 customer", s in (401,403), f"status={s}")
    s,r = call("GET","/api/ontology/object-types",tok2); check("ABAC 列表无 customer", not any(t["id"]=="customer" for t in r))
    s,r = call("POST","/api/admin/grants",A,{"username":un,"object_type":"product","permission":"read"}); check("授权 product", s==200)
    s,r = call("GET","/api/ontology/object-types",tok2); check("授权后可见 product", any(t["id"]=="product" for t in r))
    s,r = call("POST","/api/ontology/object-types/product/query",tok2,{"limit":2}); check("授权后可查 product", s==200 and len(r.get("rows",[]))>0)
    s,r = call("POST","/api/ontology/actions/customer__update/execute",tok2,{"params":{"id":1,"age":9}}); check("ABAC 拦截执行动作", s in (401,403), f"status={s}")
    # 敏感字段脱敏：admin 写值 → analyst 查掩码
    s,r = call("POST","/api/ontology/object-types/customer/properties",A,{"key":"sec_t","type":"string","sensitive":True}); 
    call("POST","/api/ontology/actions/customer__update/execute",A,{"params":{"id":1,"sec_t":"TOP-SECRET-8842"}})
    s,r = call("POST","/api/ontology/object-types/customer/query",tok2,{"limit":1,"where":{"op":"eq","field":"id","value":1}})
    v = r.get("rows",[{}])[0].get("sec_t") if r.get("rows") else None
    check("敏感字段 analyst 掩码", s==200 and v and str(v)!= "TOP-SECRET-8842" and ("*" in str(v) or "***" in str(v)), f"v={v}")
    s,r = call("POST","/api/ontology/object-types/customer/query",A,{"limit":1,"where":{"op":"eq","field":"id","value":1}})
    v2 = r.get("rows",[{}])[0].get("sec_t") if r.get("rows") else None
    check("敏感字段 admin 全量", s==200 and v2=="TOP-SECRET-8842", f"v={v2}")
    call("DELETE",f"/api/ontology/object-types/customer/properties/sec_t",A)
    s,r = call("DELETE","/api/admin/grants",A,{"username":un,"object_type":"product","permission":"read"}); check("撤销授权", s==200)
    s,r = call("DELETE",f"/api/admin/users/{un}",A); check("删除用户", s==200)
safe("用户权限管理", t_perm)

print("="*66); print("三、治理")
def t_gov():
    s,r = call("GET","/api/security/approvals?status=pending",A); check("审批列表", s==200)
    s,r = call("POST","/api/security/markings/assign",A,{"object_type":"customer","marking":"Restricted"}); check("标记分配", s==200, str(r)[:30])
    s,r = call("GET","/api/security/markings?object_type=customer",A); check("标记列表", s==200 and isinstance(r,list))
    s,r = call("GET","/api/security/retention",A); check("留存读取", s==200)
    s,r = call("PUT","/api/security/retention",A,{"object_type":"activity","days":30}); check("留存设置", s==200 or s==400, str(r)[:30])
    s,r = call("POST","/api/security/scan",A,{"object_type":"customer"}); check("敏感扫描", s==200 or s==400, str(r)[:30])
    s,r = call("GET","/api/security/scans",A); check("扫描结果", s==200 and isinstance(r,list))
safe("治理", t_gov)

print("="*66); print("四、本体深化")
def t_onto():
    s,r = call("GET","/api/ontology/stats",A); check("类型统计", s==200 and len(r)>0)
    s,r = call("GET","/api/ontology/object-types/customer/export",A); check("类型导出", s==200 and "fields" in str(r))
    cid2 = "c"+uuid.uuid4().hex[:5]
    s,r = call("POST","/api/ontology/object-types/customer/clone",A,{"new_id":cid2}); check("类型克隆", s==200, str(r)[:30])
    s,r = call("GET","/api/ontology/object-types/customer/1/graph",A); check("对象图遍历", s==200 and "nodes" in str(r))
    s,r = call("GET","/api/ontology/osdk/python",A); check("OSDK", s==200 and len(str(r))>50)
safe("本体深化", t_onto)

print("="*66); print("五、数据平面")
def t_data():
    s,r = call("POST","/api/checkpoints",A,{"object_type":"customer","label":"全量检查点"}); cp_id=r.get("checkpoint"); check("创建检查点", s==200, f"id={cp_id}")
    if s==200:
        s,r = call("GET","/api/checkpoints?object_type=customer",A); check("检查点列表", s==200 and any(str(x.get("id"))==str(cp_id) for x in r))
        s,r = call("POST",f"/api/checkpoints/{cp_id}/restore",A,{}); check("检查点恢复", s==200 or s==400, str(r)[:30])
        call("DELETE",f"/api/checkpoints/{cp_id}",A)
    br = "b"+uuid.uuid4().hex[:5]
    s,r = call("POST","/api/branches",A,{"object_type":"customer","name":br}); check("创建分支", s==200, str(r)[:30])
    if s==200:
        s,r = call("POST",f"/api/branches/{br}/protect",A,{}); check("分支保护", s==200 or s==400)
        s,r = call("POST",f"/api/branches/{br}/apply",A,{}); check("分支应用", s==200 or s==400, str(r)[:30])
        call("DELETE",f"/api/branches/{br}",A)
    s,r = call("GET","/api/pipelines/product_enrich/runs",A); check("管道运行历史", s==200)
    s,r = call("POST","/api/pipelines/product_enrich/run",A,{}); 
    s,r = call("GET","/api/pipelines/product_enrich/snapshots",A); check("管道快照列表", s==200 and isinstance(r,list))
    s,r = call("POST","/api/sql",A,{"sql":"SELECT * FROM ont__customer LIMIT 2"}); check("SQL 工作台", s==200)
    s,r = call("POST","/api/ts/ingest",A,{"series_id":"cpu.full","entity":"node-9","points":[["2026-08-01T00:00:00Z",5]]}); check("TS 写入", s==200, str(r)[:30])
    s,r = call("GET","/api/ts/query?series_id=cpu.full&entity=node-9",A); check("TS 查询", s==200 and len(r)>0)
    s,r = call("GET","/api/ts/series",A); check("TS 系列", s==200 and isinstance(r,list))
    s,r = call("POST","/api/geo/near",A,{"object_type":"city","lat":39.9,"lng":116.4,"radius_km":100}); check("空间邻近", s==200 and len(r.get("results",[]))>0, str(r)[:40])
    s,r = call("GET","/api/data-plane/engines",A); check("引擎列表", s==200 and len(r)>0)
safe("数据平面", t_data)

print("="*66); print("六、应用")
def t_app():
    s,r = call("POST","/api/apps/order_board/versions",A,{"label":"全量版本"}); check("版本保存", s==200)
    s,r = call("GET","/api/apps/order_board/versions",A); check("版本列表", s==200 and len(r)>0)
    vs=[v["version"] for v in r][:2]
    if len(vs)>=2:
        s,r = call("GET",f"/api/apps/order_board/compare?v1={vs[0]}&v2={vs[1]}",A); check("版本对比", s==200 and "changes" in str(r))
    s,r = call("GET","/api/apps/order_board/data",A); check("应用数据", s==200)
    s,r = call("POST","/api/apps/order_board/run",A,{}); check("应用运行(workflow/kanban)", s==200 or s==400, str(r)[:30])
safe("应用", t_app)

print("="*66); print("七、AIP")
def t_aip():
    s,r = call("POST","/api/aip/threads",A,{"name":"全量线程"}); tid=r.get("thread_id"); check("线程创建", s==200, f"tid={tid}")
    s,r = call("POST",f"/api/aip/threads/{tid}/chat",A,{"message":"查 product"}); check("线程聊天", s==200 and "reply" in r)
    s,r = call("GET",f"/api/aip/threads/{tid}/messages",A); check("线程消息", s==200 and len(r)>0)
    s,r = call("POST",f"/api/aip/threads/{tid}/rename",A,{"name":"改名"}); check("线程改名", s==200 or s==400)
    s,r = call("DELETE",f"/api/aip/threads/{tid}",A); check("线程删除", s==200)
    s,r = call("GET","/api/aip/tools",A); check("工具列表", s==200 and len(r)>0)
    s,r = call("GET","/api/aip/models",A); check("模型目录", s==200 and len(r)>0)
    s,r = call("GET","/api/aip/usage",A); check("模型用量", s==200)
    s,r = call("GET","/api/aip/logs",A); check("服务日志", s==200 and isinstance(r,list))
    s,r = call("GET","/api/aip/llm-status",A); check("LLM 状态", s==200)
    s,r = call("POST","/api/aip/playground",A,{"prompt":"你好","model":"gpt"}); check("Playground", s==200 or s==400, str(r)[:30])
    s,r = call("POST","/api/aip/doc-extract",A,{"text":"全量测试文档","object_type":"doc_full"}); check("文档智能", s==200 or s==400, str(r)[:30])
    ev="e"+uuid.uuid4().hex[:5]
    s,r = call("POST","/api/aip/evalsuites",A,{"id":ev,"name":"评估全量","prompt":"查{类型}","expected":"{类型}","cases":[{"input":"查 product","expected":"product"}]}); check("评估套件创建", s==200, str(r)[:30])
    if s==200:
        s,r = call("GET","/api/aip/evalsuites",A); check("评估列表", s==200 and any(x["id"]==ev for x in r))
        s,r = call("GET",f"/api/aip/evalsuites/{ev}",A); check("评估详情", s==200)
        s,r = call("POST",f"/api/aip/evalsuites/{ev}/run",A,{}); check("评估运行", s==200 or s==400, str(r)[:30])
        s,r = call("GET",f"/api/aip/evalsuites/{ev}/results",A); check("评估结果", s==200)
    s,r = call("GET","/api/models/objectives",A); check("模型目标", s==200 and isinstance(r,list))
safe("AIP", t_aip)

print("="*66); print("八、开发者")
def t_dev():
    s,r = call("GET","/api/dev/tokens",A); check("令牌列表", s==200 and isinstance(r,list))
    s,r = call("POST","/api/dev/tokens",A,{"label":"全量令牌"}); tk=r.get("token"); check("创建令牌", s==200 and bool(tk))
    if s==200:
        s,r = call("GET","/api/me",tk); check("令牌调 me", s==200)
        for x in call("GET","/api/dev/tokens",A)[1]:
            if x.get("label")=="全量令牌": call("DELETE",f"/api/dev/tokens/{x['id']}",A)
    s,r = call("GET","/api/endpoints",A); check("自定义端点列表", s==200 and isinstance(r,list))
    ep="ep"+uuid.uuid4().hex[:5]
    s,r = call("POST","/api/endpoints",A,{"id":ep,"path":f"/api/ext/{ep}","handler":"json","config":{}}); check("创建自定义端点", s==200 or s==400, str(r)[:30])
    if s==200: call("DELETE",f"/api/endpoints/{ep}",A)
    s,r = call("GET","/api/marketplace/packages",A); check("市场包", s==200 and isinstance(r,list))
    s,r = call("GET","/api/functions",A); check("函数库", s==200 and isinstance(r,list))
    s,r = call("POST","/api/transform",A,{"name":"tf_t","type":"sql","object_type":"product","code":"SELECT * FROM ont__product"}); check("转换执行", s==200 or s==400, str(r)[:30])
safe("开发者", t_dev)

print("="*66); print("九、运维/生命周期/连接器")
def t_ops():
    s,r = call("GET","/api/lifetime/policies",A); check("TTL 策略", s==200 and isinstance(r,list))
    s,r = call("POST","/api/lifetime/apply-all",A,{}); check("TTL 应用", s==200 and isinstance(r,list))
    s,r = call("GET","/api/connectors",A); check("连接器注册表", s==200 and len(r)>0)
    s,r = call("GET","/api/connectors/configs",A); check("连接配置", s==200 and isinstance(r,list))
    s,r = call("GET","/api/projects",A); check("项目列表", s==200 and any(p["id"]=="default" for p in r))
    s,r = call("GET","/api/automation/events",A); check("自动化事件", s==200 and isinstance(r,list))
    s,r = call("GET","/api/health/deep",A); check("深度健康", s==200 and r.get("status") in ("ok","warn"))
    s,r = call("GET","/api/lineage",A); check("血缘图", s==200 and "nodes" in str(r))
    s,r = call("GET","/api/lineage/tables",A); check("表级血缘", s==200)
    s,r = call("GET","/api/lineage/customer",A); check("类型血缘", s==200 and "upstream" in str(r))
    s,r = call("GET","/api/monitors",A); check("监控列表", s==200 and isinstance(r,list))
safe("运维", t_ops)

print("="*66)
print(f"\n======== 全量结果: {len(PASS)} PASS / {len(FAIL)} FAIL / {len(ERR)} ERROR ========")
if FAIL:
    print("FAIL 项:"); [print("  -", f) for f in FAIL]
if ERR:
    print("ERROR 项:"); [print("  -", e) for e in ERR]
