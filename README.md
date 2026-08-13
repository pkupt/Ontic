# Ontic

开源版 [Palantir Foundry](https://www.palantir.com/platforms/foundry/) 的**最小可用复刻**，
本体（Ontology）驱动思路的开源落地。导入一张表 → 在 Ontology 里定义对象 →
用类型安全 OSDK 查询 → 通过动作（Action）写回业务对象 → 前端 / Agent 直接操作业务语义。

> 状态：**S0–S7 + M1–M13 全部完成**（见 [FEATURE-AUDIT.md](./FEATURE-AUDIT.md) 对照 Foundry 文档索引的自查报告）。
> 非 Palantir 官方产品；"Foundry" 仅用于描述其复刻对象。

## 架构

```
请求 → FastAPI(鉴权 + ABAC) → Ontology 层
                            ├─ 元数据仓 (SQLite): 对象类型 / 链接 / 动作 / 授权 定义
                            ├─ 解析器 (对象集查询 → SQL 下推到 DuckDB)        ← 护城河
                            ├─ 动作引擎 (create/update/delete → SQL 下推)
                            ├─ OSDK 生成 (Python / TypeScript 客户端)
                            ├─ 应用构建 (Form / Dashboard / View / Workflow + 版本对比)
                            ├─ AIP (分析师 / 评估套件 / 模型用量 / 文档智能 / Playground)
                            └─ OMCP (MCP stdio 工具平面)
      数据平面: DuckDB (backing tables + 管道快照时间旅行)
      前端: 原生 JS SPA（零依赖，单文件 ~1400 行）
```

关键设计：**对象集查询不下拉全表到内存，而是翻译成参数化 SQL 直接打到数据平面（下推）**，
字段名经白名单校验，值全部参数化 —— 这正是 Foundry 聪明的地方，也是本项目的核心工程点。

## 功能矩阵（对齐 Foundry 文档索引 14 大分区）

| 分区 | 覆盖 |
|---|---|
| 本体系统 | 对象类型/属性(增删/敏感标记)/链接(外键+图遍历)/动作(CRUD+自定义) + OSDK 生成 + OMCP |
| 数据集成与管道 | 连接器框架(CSV/JSON/Parquet/REST/PG) + 多步 SQL 管道 + 函数库 + 数据流图 + 运行历史 + 快照回滚 |
| AI 能力 AIP | 聊天式 Agent(规则规划器/可选 LLM) + 评估套件 + 模型用量/服务日志 + 文档智能 + 模型对比 |
| 模型管理 | 模型目录(用量/版本) + 建模目标 + 训练占位 |
| 应用构建 | Form/Dashboard/View/Workflow 四类应用 + 版本对比 + 自包含 HTML 运行时 |
| 分析与 SQL | SQL 工作台(只读白名单) + 仪表盘聚合 + 对象集过滤 |
| 安全与治理 | ABAC(用户/授权) + 敏感数据扫描 + 审批流 + 留存策略 + 安全标记 + 字段脱敏 |
| 运维与监控 | 数据血缘图 + 监控规则 + 事件时间线 + 活动日志 |
| 数据能力 | 空间邻近查询 + 媒体存储 + 时间序列趋势 |
| 开发者 | OSDK + API 令牌 + API 参考 + 自定义端点 + 市场 |
| 发布与分发 | 市场模板 + 审批 |

完整自查报告见 [FEATURE-AUDIT.md](./FEATURE-AUDIT.md)（✅30 / 🟡24 / ⬜16 子分区粒度）。

## 用户如何运行（Quickstart）

### 方式 A：Docker（推荐，一条命令）
```bash
git clone <your-repo>/ontic.git
cd ontic
cp .env.example .env          # 可选，不改也能跑（默认 admin/admin123）
docker compose up -d --build
```
打开浏览器：**http://localhost:8080**
登录账号：`admin` / `admin123`（登录后请改密；端口/账号可在 `.env` 修改）

### 方式 B：本地 Python（无需 Docker）
```bash
cd ontic
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000
```
打开：**http://localhost:8000/api/health** 应返回 `{"status":"ok"}`；
前端在 **http://localhost:8000/**（或 8080 若用 compose）。

### 演示账号
| 账号 | 密码 | 权限 |
|---|---|---|
| `admin` | `admin123` | 全部对象类型（admin 全权） |
| `analyst` | `analyst123` | 仅对 `product` 有读写权限（ABAC 演示） |

> ⚠️ 以上为**演示默认值**，任何公开部署必须通过环境变量（`.env`）修改。

## 安全与敏感信息

- **所有密钥/密码均通过环境变量注入**（见 `.env.example`），代码库内无任何硬编码凭据；
  `data/`（SQLite 元数据 + DuckDB 数据平面 + 媒体）已被 `.gitignore` 排除，**不会进入版本库**。
- 生产部署必须设置：`ONTIC_SECRET_KEY`（JWT 签名，默认值仅用于本地开发）。
- 可选配置：
  | 变量 | 说明 |
  |---|---|
  | `ONTIC_LLM_API_KEY` / `ONTIC_LLM_BASE_URL` / `ONTIC_LLM_MODEL` | 启用真实 LLM（OpenAI 兼容：SiliconFlow/DeepSeek/vLLM/Ollama）。未配置时 AIP 自动降级为规则规划器，Playground 的 B 端返回占位 |
  | `ONTIC_TOKEN_TTL` | JWT 有效期（分钟，默认 1440） |
  | `ONTIC_ADMIN_USER` / `ONTIC_ADMIN_PASSWORD` | 初始管理员 |

## 核心 API（节选）
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | 登录拿 JWT |
| GET | `/api/me` | 当前用户与角色 |
| GET | `/api/ontology/object-types` | 列出**当前用户有权访问**的对象类型 |
| POST | `/api/ontology/object-types/{id}/query` | 对象集查询（下推，需 read 权限） |
| POST | `/api/ontology/actions/{id}/execute` | 执行动作（需 write 权限） |
| GET | `/api/ontology/osdk/{lang}` | 生成 OSDK（python / typescript） |
| POST | `/api/connectors/ingest` | 连接器接入（CSV/JSON/Parquet/REST/PG） |
| POST | `/api/pipelines/{id}/run` | 运行管道 |
| POST | `/api/aip/chat` | AIP 聊天 |
| POST | `/api/sql` | SQL 工作台（只读 + 表白名单） |
| GET | `/api/lineage` | 数据血缘图 |
| POST | `/api/security/scan` | 敏感数据扫描 |
| GET | `/api/apps` | 应用列表 |
| GET/POST | `/api/dev/tokens` | API 令牌管理 |

完整端点清单见开发者控制台「API 参考」（登录后在顶部「开发者」模块）。

## 项目结构
```
ontic/
├─ backend/
│  └─ app/                 # FastAPI 应用（16 个模块，~90 端点，20 张表）
│     ├─ ontology/         #   └─ 元数据 / 解析器(下推) / 动作 / OSDK  ← 护城河
│     ├─ aip*.py           # AIP 分析师 / 模型平台 / 评估 / 文档智能
│     ├─ app_platform.py   # 应用构建（Form/Dashboard/View/Workflow）
│     ├─ security_platform.py  # 扫描 / 审批 / 留存 / 标记
│     ├─ observability.py  # 血缘 / 监控
│     ├─ data_plane.py     # SQL 工作台 / 时空 / 媒体 / 自定义端点
│     └─ ...
├─ frontend/               # 原生 JS SPA（无构建步骤）
├─ docker-compose.yml / Dockerfile / Makefile
├─ FEATURE-AUDIT.md        # 对照 Foundry 文档索引的完整自查报告
└─ LICENSE (MIT)
```

## 路线图（已知缺口）
- 代码托管 / VS Code 扩展 / Python-Spark 等 Transforms
- 数据版本控制（检查点 / 全局分支；当前已有管道快照 + 回滚打底）
- 196 个专有连接器按注册表模式逐步补齐
- 资源管理器（Compass 类）

## 贡献
见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## License
[MIT](./LICENSE)。与 Palantir 无任何关联，非官方产品。
