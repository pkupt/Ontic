# Ontic 安全审计与工程现状报告

> 生成时间：2026-08-14 ｜ 对照 Foundry 文档索引（14 大分区 / 1408 篇）

---

## 一、工程现状

Ontic 是 Palantir Foundry 思路的开源复刻，**本体（Ontology）层为核心护城河**。

### 规模
| 维度 | 数据 |
|---|---|
| 后端模块 | 21 个 Python 模块 |
| REST 端点 | ~120 个 |
| 数据表 | 26 张（SQLite 元数据 + DuckDB 数据平面） |
| 前端 | 单文件 SPA，~2200 行 JS |
| 依赖 | 5 个（fastapi/uvicorn/duckdb/pyjwt/python-multipart），零前端构建 |
| 代码仓库 | git main 分支，首发提交 `2bbecd8`（后续迭代未提交） |

### 完成度（对照 Foundry 14 大分区）
- ✅ 已实现 32 子分区（46%）
- 🟡 部分实现 22 子分区（31%）
- ⬜ 未实现 14 子分区（20%）

**已贯通的里程碑**：S0–S7（MVP）+ M1–M13（深化）+ 迭代路径 A/B/C/D 四组。

| 层 | 能力 |
|---|---|
| **本体** | 对象类型 / 属性（增删 + 敏感脱敏 + 必填/枚举/正则校验）/ 链接（外键 + 图遍历）/ 动作（CRUD + 自定义 + 风险审批）/ 对象集查询 SQL 下推（白名单 + 参数化 + 保留字引号）/ OSDK / OMCP |
| **数据** | 连接器（CSV/JSON/Parquet/REST/PG）/ 多步管道（SQL + Python Transform）/ 函数库 / 运行历史 / 快照时间旅行 + 回滚 / 检查点 + 分支（含保护策略）/ 时间序列 / 空间查询 / 媒体 / SQL 工作台 / Compass 资源管理器 |
| **AIP** | 分析师（会话 Threads + 链式 Agent + 自动图表）/ 评估套件 / 模型用量 + 服务日志 / Playground（可接真实 LLM）/ 文档智能 |
| **应用** | Form / Dashboard / View / Workflow + 版本对比 + 自包含 HTML 运行时 |
| **治理** | ABAC / 敏感扫描 / 审批流（风险动作 + 分支保护）/ 留存 / 安全标记 / 字段脱敏 |
| **运维** | 血缘图（类型级 + 表级）/ 监控规则 / 深度健康检查 / 事件时间线 |
| **开发者** | OSDK / API 令牌 / API 参考 / 自定义端点 / 市场（可安装包）/ 类型导出导入克隆 |

---

## 二、漏洞扫描结果

### 扫描范围
依赖项 CVE / SQL 注入 / 路径遍历 / 认证授权 / CORS / XSS / RCE / 密钥管理 / 信息泄露。

### 🔴 CRITICAL（已修复）

**V1. Python Transforms 任意代码执行 (RCE)**
- **位置**：`transforms_python.py:91` `exec()` 执行用户提交代码；注册/运行端点无 admin 限制
- **影响**：任意认证用户（含受限 analyst）可注册 Python 代码，服务端 `exec` 执行 → 读文件系统 / 删数据 / 执行系统命令
- **修复**：
  1. exec 加**受限 builtins 沙箱**（移除 `__import__`/`open`/`exec`/`eval`/`compile`/`globals`/`getattr` 等危险函数，仅注入 `math`/`json`/`re`/`datetime` 等安全模块）
  2. 注册 / 运行 / 删除端点加 `require_admin`
  3. 执行异常统一捕获返回 400
- **验证**：`__import__('os').system(...)` 被拦（NameError）✓ ｜ `open('/etc/passwd')` 被拦 ✓ ｜ 正常 transform 仍可用 ✓ ｜ analyst 注册 403 ✓

### 🔴 HIGH（已修复）

**V2. Postgres 连接器 SQL 注入**
- **位置**：`connectors.py:149` 把用户提供的 host/dbname/user/password/table 直接 f-string 拼接到 `postgres_scan` SQL
- **影响**：可注入任意 SQL（如 `table = "x'); DROP TABLE ont__customer;--"`）
- **修复**：注入字符黑名单（禁 `'` `"` `;` `\` `--`）+ 端口数字校验
- **验证**：注入 payload 被拦 ✓ ｜ 正常标识符（含 IP/schema.table）通过 ✓

### 🟠 HIGH（已加告警）

**V3. JWT 默认密钥**
- **位置**：`config.py` `SECRET_KEY = "dev-secret-change-me-in-prod"`
- **影响**：生产不改密钥 → 攻击者可伪造任意 JWT 登录 admin
- **修复**：启动时检测默认值并 `warnings.warn` 告警（开源工具不阻断启动，仅强提示）
- **验证**：启动日志出现告警 ✓

**V4. 默认弱密码 admin/admin123**
- **修复**：启动时检测默认弱密码并告警
- **验证**：启动日志出现告警 ✓

### 🟡 MEDIUM（已修复）

**V5. CORS 全开**
- **位置**：`main.py` `allow_origins=["*"]`
- **影响**：任意网站可跨域调用 API（配合 Bearer token，CSRF 风险低但信息泄露存在）
- **修复**：改为可配置白名单（`ONTIC_CORS_ORIGINS` 环境变量，默认本机 3000/5173）
- **验证**：`Access-Control-Allow-Origin` 不再返回 `*` ✓

**V6. SQL 标识符拼接（中风险）**
- **位置**：`resolver.py` / `actions.py` 多处 f-string 拼接表名/列名
- **现状**：表名/列名来自元数据层（非用户直接输入），且字段 key 已用保留字双引号包裹；SQL 工作台有表白名单 + 禁分号
- **建议**：长期应加标识符白名单校验（当前风险可控）

### 🟢 已确认安全（无需修复）

| 项 | 防护措施 |
|---|---|
| 媒体路径遍历 | `Path(name).name` 去除 `../` ✓ |
| 前端 XSS | `esc()` 函数覆盖全部 innerHTML 拼接，无未转义模板 ✓ |
| SQL 工作台 | 表白名单（仅 `ont__*`）+ 禁分号 + 快照/分支表放行 ✓ |
| 认证覆盖 | 全部端点 `Depends(get_current_user)`，管理端 `require_admin` ✓ |
| 密码存储 | 哈希存储（非明文）✓ |
| 敏感字段 | 非 admin 查询掩码（首尾 2 字符）✓ |

### 剩余风险（文档标注，非代码修复）

1. **纯 Python exec 沙箱非完美**：受限 builtins 大幅降低风险，但纯 Python 难做 100% 沙箱。**生产环境应容器化隔离**执行 Python Transforms（README 已标注）。
2. **无速率限制**：未防暴力破解。建议生产前置反向代理（nginx/traefik）加速率限制。
3. **无 HTTPS**：单机本地工具默认 HTTP，生产应前置 TLS 终结。

### 依赖项
| 包 | 版本 | 已知 CVE |
|---|---|---|
| fastapi | 0.141.1 | 无高危 |
| uvicorn | 0.52.2 | 无高危 |
| duckdb | 1.5.5 | 无高危 |
| pyjwt | 2.13.0 | 无高危 |
| starlette | 1.6.0 | 无高危 |

依赖精简（仅 5 个），攻击面小。

---

## 三、下一步迭代方向

基于 foundry_docs 未深度覆盖分区的挖掘（autopilot / automate / cross-app-interactivity / custom-widgets / contour），规划两组：

### E 组 · 自动化与视图（对齐 autopilot / automate）
| 项 | 依据 | 内容 | 价值 |
|---|---|---|---|
| E1 事件触发器 | autopilot/automation-events | 监控规则命中 → 自动执行动作/通知 + 事件历史可观测（成功/失败/逐对象 trace） | ⭐⭐⭐ |
| E2 看板视图 | autopilot/kanban-board-view | 按状态字段分列的对象看板（新增应用类型 kanban） | ⭐⭐ |
| E3 依赖图视图 | autopilot/dependency-graph | 对象类型依赖关系可视化（复用血缘图引擎） | ⭐⭐ |

### F 组 · 应用深化（对齐 cross-app-interactivity / custom-widgets / contour）
| 项 | 依据 | 内容 | 价值 |
|---|---|---|---|
| F1 跨应用交互 | cross-app-interactivity/overview | 对象抽屉"在相关应用中打开" + 应用间传递对象上下文 | ⭐⭐⭐ |
| F2 自定义组件 | custom-widgets/core-concepts | 应用运行时加时间范围筛选器 / 对象选择器 / 图表组件 | ⭐⭐ |
| F3 Contour 画布分析 | contour/core-concepts | 节点式数据分析画布（输入→转换→输出节点连线） | ⭐⭐ |

### 明确不做（路线图标注）
- 代码仓库 / VS Code 扩展（依赖真实执行环境，超出本地单机范围）
- Spark Transforms（依赖 Spark 集群）
- private-link / peer-manager（网络域管理，超出本地单机）

---

## 四、开源前检查清单

- [x] 全库扫描无硬编码凭据（`.env.example` 全占位）
- [x] 测试期 API token 已撤销
- [x] `.gitignore` 排除 `data/`（元数据 DB + DuckDB + 媒体 + 令牌表）
- [x] `.gitattributes` 统一 LF
- [x] RCE 沙箱 + admin 限制
- [x] SQL 注入防护
- [x] CORS 白名单
- [x] JWT / 弱密码启动告警
- [ ] **提交本轮安全修复到 git**（当前改动未提交）
- [ ] 生产部署文档补安全配置（SECRET_KEY / ADMIN_PASSWORD / CORS / 反向代理）
