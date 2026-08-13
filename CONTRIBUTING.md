# 贡献指南（Contributing）

感谢你对 **Ontic** 感兴趣。这是一个开源版 Palantir Foundry 的本体驱动数据平台复刻，
我们欢迎各类贡献。

## 开发约定

- **后端**：Python 3.12+，FastAPI；依赖在 `backend/requirements.txt`，用虚拟环境安装。
- **前端**：原生 JS SPA（无构建步骤），放在 `frontend/`。
- **数据平面**：DuckDB（backing tables）；元数据仓：SQLite。
- **核心工程点**：对象集查询 **SQL 下推** + **字段白名单** + **参数化查询**（防注入）。
  任何新增查询/写路径都必须保持「字段白名单 + 值参数化」，不要拼接用户输入到 SQL。

## 本地起环境

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000
```

## 提交前检查

1. 服务能启动：`curl localhost:8000/api/health` 返回 `{"status":"ok"}`。
2. 登录 + 查询 + 动作 端到端可用（见 README 的 curl 示例）。
3. 新增 API 请在 `main.py` 加 `get_current_user` 依赖，写操作需走动作引擎（不要裸写 SQL）。
4. 权限相关改动：默认 admin 全权，普通用户按 `grants` 表裁定（见 `metadata.can_access`）。

## 代码结构

| 层 | 文件 | 职责 |
|---|---|---|
| 配置 | `app/config.py` | 环境变量（前缀 `ONTIC_`，含密钥/端口/管理员） |
| 安全 | `app/security.py` | PBKDF2 密码哈希 + JWT |
| 本体 | `app/ontology/metadata.py` | 对象类型/动作/授权 定义与初始化 |
| 本体 | `app/ontology/resolver.py` | 对象集查询 → SQL 下推（护城河） |
| 本体 | `app/ontology/actions.py` | 动作引擎（create/update/delete 下推） |
| 本体 | `app/ontology/osdk.py` | OSDK 类型安全客户端生成 |
| 接入 | `app/ingestion.py` | CSV 接入 + SQL 转换 → 自动注册对象类型 |
| 应用 | `app/app_builder.py` | 单文件 CRUD 应用生成 |
| Agent | `app/aip.py` / `app/omcp.py` | 聊天 Agent + OMCP(stdio) 工具平面 |

## 行为准则

- 不要引入与 Palantir 商标冲突的命名或宣称官方关系。
- 优先用开源组件拼装；自研重心放在 Ontology 层（本项目差异化所在）。

提交 PR 时请简要说明：改动动机、影响范围、如何验证。
