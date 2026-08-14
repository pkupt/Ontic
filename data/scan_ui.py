"""完整性验证静态扫描：前端按钮死链 + api 路径对照后端路由。"""
import re

import os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 脚本在 data/，根在上一级
APP_JS = os.path.join(ROOT, "frontend", "assets", "app.js")
MAIN_PY = os.path.join(ROOT, "backend", "app", "main.py")

js = open(APP_JS, encoding="utf-8").read()
py = open(MAIN_PY, encoding="utf-8").read()

# 1. 前端定义的所有函数
defined = set(re.findall(r"^(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", js, re.M))
defined |= set(re.findall(r"const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=", js))
print(f"前端定义函数: {len(defined)}")

# 2. onclick 引用的函数
onclick_fns = set(re.findall(r"on(?:click|change|input|keydown|submit|focus|blur|load|search)=[\"']([A-Za-z_][A-Za-z0-9_]*)\(", js))
# 也抓模板字符串里的 onclick="fn(
onclick_fns |= set(re.findall(r"onclick=\"([A-Za-z_][A-Za-z0-9_]*)\(", js))
print(f"onclick 引用函数: {len(onclick_fns)}")

# 3. 死链：引用了但未定义的
dead = sorted(onclick_fns - defined)
print(f"\n=== 按钮死链（onclick 引用但未定义）: {len(dead)} ===")
for f in dead:
    # 找出引用位置
    for m in re.finditer(rf"(?:on(?:click|change)=\"|onclick=)[\"']?{re.escape(f)}\(", js):
        s = max(0, m.start() - 60)
        print(f"  - {f}  (…{js[s:m.start()+len(f)+10].strip()[-70:]})")

# 4. 前端 api 调用路径
api_paths = set(re.findall(r"api\([\"'](/api/[^\"']*?)[\"']", js))
api_paths |= set(re.findall(r"fetch\(API\s*\+\s*[\"'](/api/[^\"']*?)[\"']", js))
print(f"\n前端 api 路径: {len(api_paths)}")

# 5. 后端路由
routes = set(re.findall(r'@app\.(?:get|post|put|delete|patch)\("(/api/[^"]+)"\)', py))
print(f"后端路由: {len(routes)}")

# 6. api 路径与路由对照（把 {id} 参数归一）
def norm(p):
    return re.sub(r"\{[^}]+\}", "{x}", p)

route_norm = {norm(r) for r in routes}
unmatched = sorted({p for p in api_paths if norm(p) not in route_norm})
print(f"\n=== 前端调用的 API 无对应后端路由: {len(unmatched)} ===")
for p in unmatched:
    print(f"  - {p}")
