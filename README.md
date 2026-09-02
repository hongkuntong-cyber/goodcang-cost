# GoodCang Overseas Warehouse Cost Intelligence

> 谷仓海外仓成本健康分析系统（德国海外仓 · 企业内部使用）

基于谷仓 GoodCang Open API 数据，自动分析**德国海外仓**的每月成本结构、费用变化趋势与库存老化风险，并自动生成月度成本健康报告。

---

## 一、项目简介

本系统面向企业内部业务负责人（非技术角色），把谷仓海外仓分散的账单与库存数据，加工成「看得懂、能决策」的成本健康看板与月度报告。

系统只做**成本与库存健康**分析，不做采购成本、利润、销售预测。

### 系统要回答的三个问题

1. **每个月海外仓花了多少钱？** —— 月度总成本与环比变化
2. **钱主要花在哪里？** —— 费用结构（仓储 / 入库 / 出库操作 / 运输 / 其他）
3. **哪些库存正在造成长期仓储压力？** —— 库存年龄分布与 TOP20 风险 SKU

---

## 二、功能范围（V1）

| 模块 | 功能 | 说明 |
| --- | --- | --- |
| A | 月度成本分析 | 本月总成本、环比变化、近 12 个月成本趋势、成本结构占比 |
| B | 费用结构分析 | 仓储费 / 入库费 / 出库操作费 / 运输费 / 其他费用 五大类 |
| C | 库存健康分析 | 按库存年龄分桶：0–90 健康 / 90–180 关注 / 180–365 呆滞 / 365+ 严重呆滞 |
| D | 风险 SKU 排行 | 排序：第一库存年龄、第二库存数量；输出 TOP20 风险 SKU |
| E | 自动月度报告 | 生成《德国海外仓成本健康报告》：成本变化、费用原因、库存风险、优化建议 |

### 明确不做（V1 范围外）

- ❌ 产品采购成本
- ❌ 利润分析
- ❌ 销售预测
- ❌ 自动清仓建议

> 原因：当前数据源不含这些数据，避免误导决策。

---

## 三、技术栈

| 层 | 技术 | 说明 |
| --- | --- | --- |
| 后端 | Python 3.11+ / FastAPI | REST API、数据同步、分析引擎 |
| 数据库 | PostgreSQL 15+ | 账单 / 库存 / 分析结果持久化 |
| ORM / 迁移 | SQLAlchemy 2.x / Alembic | 模型与版本化迁移 |
| 前端 | Vue 3 / ECharts / Vite | 成本健康 Dashboard |
| 部署 | Docker / docker-compose | 一键编排 db + backend + frontend |

**架构原则**：轻量化企业应用、分层清晰（Connector → Repository → Service → API）、模块可扩展。

---

## 四、项目结构

```
goodcang-cost-intelligence/
├── README.md                       # 本文件
├── docker-compose.yml              # 一键编排：db + backend + frontend
├── .env.example                    # 根级环境变量示例（数据库等）
├── .gitignore
│
├── docs/                           # 设计文档
│   ├── database-design.md          # 数据库设计文档
│   └── api-field-mapping.md        # 谷仓 API 字段映射文档
│
├── backend/                        # FastAPI 后端
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── .env.example                # 后端敏感配置示例（GoodCang AppToken/AppKey）
│   ├── alembic/                    # 数据库迁移
│   │   └── versions/
│   ├── app/
│   │   ├── main.py                 # 应用入口
│   │   ├── core/                   # 配置 / 数据库连接 / 日志
│   │   ├── connectors/
│   │   │   └── goodcang/           # 谷仓 API 连接器（client/endpoints/schemas）
│   │   ├── models/                 # SQLAlchemy ORM 模型
│   │   ├── schemas/                # Pydantic 模型（API 出入参）
│   │   ├── repositories/           # 数据访问层
│   │   ├── services/               # 业务逻辑 / 分析引擎
│   │   ├── api/routes/             # REST 路由
│   │   └── tasks/                  # 数据同步任务
│   └── tests/
│
└── frontend/                       # Vue3 + ECharts 前端
    ├── Dockerfile
    ├── package.json
    └── src/
        ├── api/                    # 后端接口封装
        ├── views/                  # 页面（成本/费用/库存/风险/报告）
        ├── components/             # 图表等组件
        ├── store/                  # 状态管理
        └── router/                 # 路由
```

---

## 五、快速开始

> 完整跑通需先完成 Step 2–6 的代码。以下为最终启动方式预览。

```bash
# 1. 复制环境变量模板并填入真实配置（见“六、配置”）
cp .env.example .env
cp backend/.env.example backend/.env

# 2. 一键启动（PostgreSQL + 后端 + 前端）
docker-compose up -d --build

# 3. 访问
# 前端 Dashboard:  http://localhost:8080
# 后端 API 文档:   http://localhost:8000/docs
```

---

## 六、配置（敏感信息）

> **安全红线：API Key / AppToken / AppKey 一律不写入代码，统一走 `.env`，`.env` 不提交 git。**

| 变量 | 说明 | 获取方式 |
| --- | --- | --- |
| `GOODCANG_APP_TOKEN` | 谷仓开放平台 AppToken | GWC OMS → 我的 → 开发者信息 → 选海外仓 |
| `GOODCANG_APP_KEY` | 谷仓开放平台 AppKey | 同上 |
| `GOODCANG_BASE_URL` | 接口网关地址 | 开放平台（UAT / 正式） |
| `GOODCANG_WAREHOUSE_CODE` | 目标仓（德国仓）编码 | OMS 仓库列表 |
| `DATABASE_URL` | PostgreSQL 连接串 | 本地/容器 |

详见 `backend/.env.example`。

---

## 七、开发路线图

| Step | 内容 | 状态 |
| --- | --- | --- |
| 1 | 项目结构 + README + 数据库设计 + API 字段映射文档 | ✅ |
| 2 | 数据库模型实现（SQLAlchemy + Alembic） | ✅ |
| 3 | 谷仓 GoodCang API Connector | ✅ |
| 4 | 数据同步任务 | ✅ |
| 5 | 分析引擎（成本/费用/库存健康/风险SKU/月度报告） | ✅ |
| 6 | Dashboard 前端页面（Vue3 + ECharts） | ✅ |
| 7 | 测试与优化 + Docker 整体验证 | ✅ |

---

## 八、文档索引

- [数据库设计文档](docs/database-design.md)
- [谷仓 API 字段映射文档](docs/api-field-mapping.md)

---

## 九、数据安全与合规

1. 所有密钥通过 `.env` 注入，代码中**禁止硬编码**。
2. `.env` 已加入 `.gitignore`，不会进入版本库。
3. 原始 API 报文以 JSON 留痕（`raw_json`），便于对账与回溯。
4. 仅对接企业内部授权账号，数据不出内网。
