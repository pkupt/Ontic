# Ontic 端到端闭环验证报告

> 生成时间：2026-08-14 ｜ 验证方式：全新业务域"供应商采购"从零实测（API 全链路）

## 一、闭环验证总览（9 环节全链路）

用全新业务域 `supplier + purchase_order` 从零走通，**21 项断言全部 PASS**：

| # | 环节 | 实测内容 | 结果 |
|---|---|---|---|
| ① | **数据加载** | CSV 连接器接入 supplier.csv（5 行）/ purchase_order.csv（10 行） | ✅ |
| ② | **数据灌入** | 自动注册对象类型 + 属性 + **自动生成 CRUD 动作**（create/update/delete） | ✅ |
| ③ | **本体创建** | 链接类型 po_supplier / po_product（外键模型） | ✅ |
| ④ | **实例化** | 对象查询（按外键过滤）+ 链接遍历（PO#1 → 华北供应） | ✅ |
| ⑤ | **可视化** | Dashboard（按状态聚合）/ Kanban（按状态分列）/ View 应用创建 + 数据 | ✅ |
| ⑥ | **智能体创建** | AIP 会话 Threads 创建 | ✅ |
| ⑦ | **本体消费** | AIP 自然语言查询新类型（purchase_order）+ 链式查询（supplier 和 purchase_order）+ 状态过滤 | ✅ |
| ⑧ | **动作执行** | `purchase_order__update` 执行（status → delivered） | ✅ |
| ⑨ | **数据回写** | 回查验证 status=delivered + 变更历史含对象 id（purchase_order#1） | ✅ |

**结论：上线后可跑通整体流程。** 闭环从"一张 CSV"到"智能体消费 + 动作回写"全部贯通，无断点。

## 二、验证中发现并修复的断点

**🔴 AIP 类型解析缺陷（真实产品缺陷）**
- **现象**：`查 purchase_order` 被解析为查询 `order`（purchase_order 含 order 子串，顺序遍历先命中）
- **根因**：`aip.py` 的 `_resolve_type/_resolve_types` 用子串匹配且无优先级，长 id 被短 id 截胡
- **修复**：**最长匹配优先**（id 匹配权重 > name 匹配）+ **去子串嵌套**（purchase_order 命中时不再命中 order）
- **验证**：`查 purchase_order` → 10 行 ✓；`查 order` → 15 行 ✓；链式 `__multi__` ✓

## 三、演示数据（上线即见）

| 对象类型 | 数据 | 用途 |
|---|---|---|
| customer | 8 行 | 本体端到端基础演示 |
| product | 9 行 | 产品目录 |
| order | 15 行 | 订单（customer→order→product 多跳链接） |
| region / city | 3 / 8 行 | 链接 + 时空查询 |
| **supplier** | 5 行 | 本闭环新增：供应商 |
| **purchase_order** | 10 行 | 本闭环新增：采购订单（→supplier/→product） |

已建演示应用：`po_dash`（采购仪表盘）/ `po_board`（采购看板）/ `po_view`（采购视图）。

## 四、对标 Palantir（差距与已对齐）

| 维度 | Palantir | Ontic 现状 | 差距 |
|---|---|---|---|
| 数据加载 | Data Connection 目录 + 196 连接器 | CSV/JSON/Parquet/REST/PG 5 类 + SQL 工作台 | 连接器数量（按注册表模式可扩） |
| 本体创建 | Ontology Manager（类型/链接/动作/约束） | 对象类型/属性(敏感/必填/枚举/正则)/链接/动作 全支持 | ✅ 基本对齐 |
| 实例化 | 对象详情页 + 对象卡片 + 关系图 | 对象抽屉（卡片属性 + 放射关系图 + 跨应用打开） | ✅ 已对齐 |
| 可视化 | Workshop 应用 + Contour 画布 | 5 类应用（Form/Dashboard/View/Workflow/Kanban） | Contour 画布分析未做 |
| 智能体 | AIP Agent（tool calling 编排） | 分析师（Threads + 链式 + 自动图表 + 可选 LLM）+ OMCP | 工具集可再扩（写回/审批工具） |
| 动作执行 | Actions + 审批 + 自动运行 | 动作引擎 + 风险审批 + 事件触发器 | ✅ 已对齐 |
| 数据回写 | 动作写回 + 数据集版本 | 动作写回 + 变更历史 + 快照/检查点 | 字段级加密未做 |

**核心护城河（本体层）已闭环**：查询 SQL 下推 / 链接图遍历 / 动作引擎 / OSDK / OMCP 全部可用。

## 五、演示路径（前端怎么走）

1. **数据** → 连接器 → 上传 CSV → 自动生成对象类型 + CRUD 动作
2. **本体** → 打开 purchase_order → 属性/动作/链接/数据 tab（关系图、看板、查询）
3. **应用** → 打开 po_board（看板按状态分列）→ 点卡片看详情
4. **AIP** → 分析师 → 新建会话 → 问"查 purchase_order"/"supplier 状态为 active 的"
5. **动作回写** → 本体 → 数据 tab → 点任意行开抽屉 → 执行动作 → 变更历史留痕

## 六、验证脚本

`data/e2e_verify.py`（可重复执行：上传 CSV → 建链 → 建应用 → 智能体 → 动作 → 回写，21 断言）。
