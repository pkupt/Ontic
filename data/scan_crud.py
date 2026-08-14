"""完整性验证：逐模块 CRUD 闭环（C→R→U→D 实测）。"""
import json, urllib.request, urllib.error, uuid

BASE = "http://localhost:8000"
PASS, FAIL = [], []
T = lambda s: uuid.uuid4().hex[:6]  # 临时 id 后缀

def call(m, p, t, b=None, raw=False):
    h = {"Content-Type": "application/json"}
    if t: h["Authorization"] = f"Bearer {t}"
    req = urllib.request.Request(BASE+p, data=json.dumps(b).encode() if b is not None else None, headers=h, method=m)
    try:
        r = urllib.request.urlopen(req); return r.status, (r.read() if raw else json.loads(r.read() or b"{}"))
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read() or b"{}")
        except: return e.code, {}

def check(name, ok, extra=""):
    (PASS if ok else FAIL).append(name)
    print(f"  {'PASS' if ok else 'FAIL'} {name} {extra}")

tok = call("POST","/api/auth/login",None,{"username":"admin","password":"admin123"})[1]["access_token"]
H = tok

print("== 1. 对象类型 CRUD ==")
tid = "t_crud"
props = json.dumps([{"key":"id","column":"id","type":"integer","title":"ID"},{"key":"name","column":"name","type":"string","title":"名称"}])
s,_ = call("POST","/api/ontology/object-types",H,{"id":tid,"name":"CRUD测试","fields":[{"key":"id","type":"integer"},{"key":"name","type":"string"}],"primary_key":"id"})
check("创建类型", s==200, f"status={s}")
s,r = call("POST",f"/api/ontology/object-types/{tid}/properties",H,{"key":"age","type":"integer","title":"年龄"})
check("加属性(U)", s==200, str(r)[:50])
s,r = call("GET",f"/api/ontology/object-types/{tid}",H)
check("读类型(R)", s==200 and "age" in r["properties"], "props 含 age" if s==200 else str(r)[:40])
s,r = call("DELETE",f"/api/ontology/object-types/{tid}",H)
check("删类型(D)", s==200, str(r)[:40])

print("== 2. 动作 CRUD ==")
aid = "a_crud"
s,_ = call("POST","/api/ontology/actions",H,{"id":aid,"name":"测试动作","object_type":"customer","operation":"create","parameters":[{"name":"name","type":"string","required":True}]})
check("创建动作", s==200)
s,r = call("GET","/api/ontology/actions",H)
check("读动作(R)", any(a["id"]==aid for a in r))
s,r = call("POST",f"/api/ontology/actions/{aid}/execute",H,{"params":{"name":"临时客户x","code":"ZZZ9","email":"z@z.com"}})
check("执行动作", s==200, str(r)[:50])
s,_ = call("DELETE",f"/api/ontology/actions/{aid}",H)
check("删动作(D)", s==200)

print("== 3. 链接 CRUD ==")
lid = "l_crud"
s,_ = call("POST","/api/ontology/link-types",H,{"id":lid,"name":"链接测试","source_type":"customer","target_type":"region","source_fk":"region"})
check("创建链接", s==200)
s,r = call("GET","/api/ontology/object-types/customer/links",H)
check("读链接(R)", any(l["id"]==lid for l in r))
s,_ = call("DELETE",f"/api/ontology/link-types/{lid}",H)
check("删链接(D)", s==200)

print("== 4. 管道 CRUD ==")
pid = "p_crud"
s,_ = call("POST","/api/pipelines",H,{"id":pid,"name":"管道测试","steps":[{"target":"p_crud_out","sql":"SELECT * FROM ont__customer","name":"s1"}]})
check("创建管道", s==200, str(r)[:30] if s!=200 else "")
s,r = call("POST",f"/api/pipelines/{pid}/run",H,{})
check("运行管道", s==200, str(r)[:50])
s,_ = call("DELETE",f"/api/pipelines/{pid}",H)
check("删管道(D)", s==200)

print("== 5. 应用 CRUD ==")
apid = "app_crud"
s,_ = call("POST","/api/apps",H,{"id":apid,"name":"应用测试","type":"view","object_type":"customer","config":{"limit":10}})
check("创建应用", s==200)
s,r = call("GET",f"/api/apps/{apid}/render",H, raw=True)
check("渲染应用(R)", s==200 and len(r)>2000)
s,r = call("POST",f"/api/apps/{apid}/save",H,{"name":"应用测试改"})
check("更新应用(U)", s==200, str(r)[:50])
s,_ = call("DELETE",f"/api/apps/{apid}",H)
check("删应用(D)", s==200)

print("== 6. 监控 CRUD ==")
mid = "m_crud"
s,_ = call("POST","/api/monitors",H,{"id":mid,"name":"监控测试","object_type":"customer","metric":"count","op":"gt","threshold":100})
check("创建监控", s==200)
s,r = call("POST",f"/api/monitors/{mid}/check",H,{})
check("运行检查(R)", s==200, str(r)[:40])
s,_ = call("DELETE",f"/api/monitors/{mid}",H)
check("删监控(D)", s==200)

print("== 7. Chatbot CRUD ==")
cid = "cb_crud"
s,_ = call("POST","/api/chatbots",H,{"id":cid,"name":"机器人测试","instructions":"测试","tools":["query_object_set"]})
check("创建 Chatbot", s==200)
s,r = call("POST",f"/api/chatbots/{cid}/chat",H,{"message":"查 customer"})
check("运行 Chatbot(R)", s==200, str(r.get("tool"))[:30])
s,_ = call("DELETE",f"/api/chatbots/{cid}",H)
check("删 Chatbot(D)", s==200)

print("== 8. 分析 CRUD ==")
nid = "an_crud"
s,_ = call("POST","/api/analyses",H,{"id":nid,"name":"分析测试","steps":[{"type":"source","table":"customer"},{"type":"limit","n":5}]})
check("创建分析", s==200)
s,r = call("POST",f"/api/analyses/{nid}/run",H,{})
check("运行分析(R)", s==200, f"rows={r.get('count')}")
s,_ = call("DELETE",f"/api/analyses/{nid}",H)
check("删分析(D)", s==200)

print("== 9. 知识库 CRUD ==")
kid = "k_crud"
s,_ = call("POST","/api/knowledge",H,{"id":kid,"content":"测试知识条目","tags":["test"]})
check("添加知识", s==200)
s,r = call("POST","/api/knowledge/search",H,{"query":"测试知识","top_k":1})
check("检索知识(R)", s==200 and any(x["id"]==kid for x in r), str([x["id"] for x in r])[:40])
s,_ = call("DELETE",f"/api/knowledge/{kid}",H)
check("删知识(D)", s==200)

print("== 10. 项目 CRUD ==")
pj = "pj_crud"
s,_ = call("POST","/api/projects",H,{"id":pj,"name":"项目测试"})
check("创建项目", s==200)
s,r = call("GET","/api/projects",H)
check("读项目(R)", any(p["id"]==pj for p in r))
s,_ = call("DELETE",f"/api/projects/{pj}",H)
check("删项目(D)", s==200)

print("== 11. 权限 ABAC ==")
s,r = call("POST","/api/admin/grants",H,{"username":"analyst","object_type":"customer","permission":"read"})
check("授权(read)", s==200, str(r)[:40])
s,r = call("GET","/api/admin/grants",H)
check("读权限(R)", s==200)
s,_ = call("DELETE","/api/admin/grants",H,{"username":"analyst","object_type":"customer","permission":"read"})
check("撤销权限(D)", s==200)

print("== 12. 媒体 CRUD ==")
import io
boundary = "----c" + uuid.uuid4().hex
fn = f"t_{uuid.uuid4().hex[:6]}.txt"
body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fn}\"\r\nContent-Type: text/plain\r\n\r\nhello ontic\r\n--{boundary}--\r\n").encode()
req = urllib.request.Request(BASE+"/api/media/upload", data=body, method="POST",
    headers={"Authorization": f"Bearer {H}", "Content-Type": f"multipart/form-data; boundary={boundary}"})
try:
    r = urllib.request.urlopen(req); up = json.loads(r.read()); check("媒体上传(C)", True, str(up)[:50])
    media = up["name"]
    s,_ = call("GET","/api/media",H); check("媒体列表(R)", s==200)
    s,_ = call("DELETE",f"/api/media/{media}",H); check("媒体删除(D)", s==200)
except Exception as e:
    check("媒体上传(C)", False, str(e)[:60])

print("== 13. 时间序列 ==")
s,_ = call("POST","/api/ts/ingest",H,{"series_id":"cpu.test","entity":"n1","points":[["2026-08-01T00:00:00Z",10]]})
check("TS 写入(C)", s==200)
s,r = call("GET","/api/ts/query?series_id=cpu.test&entity=n1",H)
check("TS 查询(R)", s==200)
s,_ = call("DELETE","/api/ts/series/cpu.test?entity=n1",H)
check("TS 删除(D)", s==200)

print("== 14. 审批流 ==")
s,r = call("GET","/api/security/approvals?status=pending",H)
check("审批列表(R)", s==200, f"pending={len(r) if isinstance(r,list) else 0}")

print(f"\n======== 结果: {len(PASS)} PASS / {len(FAIL)} FAIL ========")
if FAIL: print("FAIL 项:", FAIL)
