# 数据库设计文档

> 项目：GoodCang Overseas Warehouse Cost Intelligence
> 数据库：PostgreSQL 15+
> ORM：SQLAlchemy 2.x ｜ 迁移：Alembic

---

## 1. 设计目标与原则

1. **支撑三类核心分析**：月度成本、费用结构、库存健康。
2. **快照 + 留痕**：库存类为时点数，按抓取日期做快照；账单类按 `bill_number` 幂等更新；所有原始报文保留 `raw_json` 便于对账回溯。
3. **原始层 / 分析层分离**：API 拉取的原始数据（`stg_*`）与分析结果（`mart_*`）分表，分析层可重算、可扩展。
4. **可扩展**：费用归类、仓库维度、年龄分桶阈值均配置化，新增仓/新增费用类型不改表结构。
5. **幂等可重跑**：同步任务可安全重跑，不产生重复数据。

---

## 2. 数据分层总览

```
GoodCang Open API
      │  (Step 3 Connector / Step 4 同步任务)
      ▼
┌─────────────────────────────┐
│ 原始层 stg_*                 │  账单、费用明细、库存年龄、库存状态（含 raw_json）
└─────────────────────────────┘
      │  (Step 5 分析引擎)
      ▼
┌─────────────────────────────┐
│ 分析层 mart_*                │  月度成本汇总、风险SKU、月度报告
└─────────────────────────────┘
      │
      ▼
FastAPI → Vue3 Dashboard / 月度报告
```

维度/配置：`dim_warehouse`、`fee_category_map`
运维：`sync_logs`

---

## 3. 表结构明细

### 3.1 `dim_warehouse` — 仓库维度表

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| warehouse_code | VARCHAR(32) | NOT NULL, UNIQUE | 谷仓仓库编码 |
| warehouse_name | VARCHAR(128) | NOT NULL | 仓库名称 |
| country_code | CHAR(2) | NOT NULL | 国家码（德国 = `DE`） |
| currency_code | CHAR(3) | NOT NULL DEFAULT 'EUR' | 默认结算币种 |
| is_active | BOOLEAN | NOT NULL DEFAULT TRUE | 是否启用 |
| created_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 创建时间 |

> V1 仅启用德国仓（`country_code='DE'`），但结构上支持多仓扩展。

---

### 3.2 `stg_bills` — 账单主表（原始层）

来源接口：`billing_list`（获取月度账单）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| bill_number | VARCHAR(64) | NOT NULL, UNIQUE | 账单号（幂等键） |
| account_code | VARCHAR(64) | NULL | 客户/账号编码 |
| bill_from_time | TIMESTAMPTZ | NOT NULL | 账单开始时间 |
| bill_to_time | TIMESTAMPTZ | NOT NULL | 账单结束时间 |
| bill_month | CHAR(7) | NOT NULL | 归属月份 `YYYY-MM`（冗余，便于聚合） |
| all_total | NUMERIC(18,4) | NOT NULL | 账单总金额 |
| currency_code | CHAR(3) | NOT NULL | 币种 |
| warehouse_code | VARCHAR(32) | NULL → FK | 关联仓库（可空，便于先落库后归仓） |
| raw_json | JSONB | NULL | 原始报文 |
| synced_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 同步时间 |

**索引**：`uk_stg_bills_number(bill_number)` 唯一；`ix_stg_bills_month(bill_month)`；`ix_stg_bills_wh(warehouse_code)`

> **幂等策略**：以 `bill_number` 为唯一键 `UPSERT`（存在则更新金额/区间/原始报文）。

---

### 3.3 `stg_bill_fee_items` — 账单费用明细表（原始层）

来源接口：`billing_export`（获取账单费用明细）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| bill_number | VARCHAR(64) | NOT NULL → FK(stg_bills.bill_number) | 所属账单号 |
| fee_name | VARCHAR(128) | NOT NULL | 原始费用名称（谷仓返回） |
| fee_category | VARCHAR(32) | NOT NULL | 归类：`storage/inbound/outbound/transport/other` |
| amount | NUMERIC(18,4) | NOT NULL | 费用金额 |
| currency_code | CHAR(3) | NOT NULL | 币种 |
| related_sku | VARCHAR(64) | NULL | 关联 SKU（若明细到 SKU） |
| bill_month | CHAR(7) | NOT NULL | 归属月份（冗余，便于聚合） |
| raw_json | JSONB | NULL | 原始报文 |
| synced_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 同步时间 |

**索引**：`ix_fee_bill(bill_number)`；`ix_fee_month_cat(bill_month, fee_category)`；`ix_fee_sku(related_sku)`

> **费用归类**：`fee_category` 由 `fee_category_map` 映射得到，落库前完成归类。

---

### 3.4 `fee_category_map` — 费用归类映射表（配置）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| match_keyword | VARCHAR(128) | NOT NULL | 匹配关键字（对 fee_name 做包含/正则匹配） |
| fee_category | VARCHAR(32) | NOT NULL | 目标归类 `storage/inbound/outbound/transport/other` |
| priority | INT | NOT NULL DEFAULT 100 | 匹配优先级（小者优先） |
| remark | VARCHAR(255) | NULL | 备注 |

**五大费用归类（功能 B）**：

| fee_category | 中文 | 典型 fee_name 关键字（示例，需按真实数据校准） |
| --- | --- | --- |
| `storage` | 仓储费 | 仓储、仓租、storage、rent |
| `inbound` | 入库费 | 入库、上架、inbound、receiving |
| `outbound` | 出库操作费 | 出库、操作、拣货、打包、outbound、handling |
| `transport` | 运输费 | 运输、派送、运费、transport、shipping、freight |
| `other` | 其他费用 | 兜底（未匹配项） |

> **业务确认点**：谷仓真实 `fee_name` 关键字需用登录后的真实账单明细校准，本表支持随时增删改而无需改代码。

---

### 3.5 `stg_inventory_age` — 库存年龄快照表（原始层）

来源接口：`inventory_age_list`（库存年龄分析）。库存为时点数，按 `snapshot_date` 做快照。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| snapshot_date | DATE | NOT NULL | 快照日期（抓取日） |
| sku | VARCHAR(64) | NOT NULL | SKU |
| product_name | VARCHAR(255) | NULL | 商品名称 |
| quantity | INT | NOT NULL DEFAULT 0 | 库存数量 |
| warehouse_age | INT | NOT NULL | 库龄（天） |
| inbound_time | TIMESTAMPTZ | NULL | 入库时间 |
| age_bucket | VARCHAR(16) | NOT NULL | 年龄分桶（冗余，见下） |
| warehouse_code | VARCHAR(32) | NULL → FK | 仓库编码 |
| raw_json | JSONB | NULL | 原始报文 |
| synced_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 同步时间 |

**唯一约束**：`uk_age_snapshot(snapshot_date, sku, warehouse_code)`（同日同 SKU 同仓仅一条，可重跑）
**索引**：`ix_age_date(snapshot_date)`；`ix_age_sku(sku)`；`ix_age_bucket(snapshot_date, age_bucket)`

**年龄分桶规则（功能 C）**：

| age_bucket | 区间（天） | 中文 |
| --- | --- | --- |
| `healthy` | 0–90 | 健康库存 |
| `watch` | 90–180 | 关注库存 |
| `stale` | 180–365 | 呆滞库存 |
| `critical` | 365+ | 严重呆滞库存 |

---

### 3.6 `stg_inventory_status` — 当前库存状态快照表（原始层）

来源接口：`get_product_inventory`（当前库存状态）。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| snapshot_date | DATE | NOT NULL | 快照日期 |
| sku | VARCHAR(64) | NOT NULL | SKU |
| sellable | INT | NOT NULL DEFAULT 0 | 可售 |
| unsellable | INT | NOT NULL DEFAULT 0 | 不可售 |
| reserved | INT | NOT NULL DEFAULT 0 | 预留/占用 |
| onway | INT | NOT NULL DEFAULT 0 | 在途 |
| warehouse_code | VARCHAR(32) | NULL → FK | 仓库编码 |
| raw_json | JSONB | NULL | 原始报文 |
| synced_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 同步时间 |

**唯一约束**：`uk_status_snapshot(snapshot_date, sku, warehouse_code)`
**索引**：`ix_status_date(snapshot_date)`；`ix_status_sku(sku)`

---

### 3.7 `mart_monthly_cost_summary` — 月度成本汇总表（分析层）

由分析引擎按账单 + 费用明细物化，驱动 Dashboard「月度成本分析 / 费用结构」。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| bill_month | CHAR(7) | NOT NULL | 月份 `YYYY-MM` |
| warehouse_code | VARCHAR(32) | NOT NULL | 仓库编码 |
| total_cost | NUMERIC(18,4) | NOT NULL | 月度总成本 |
| storage_fee | NUMERIC(18,4) | NOT NULL DEFAULT 0 | 仓储费 |
| inbound_fee | NUMERIC(18,4) | NOT NULL DEFAULT 0 | 入库费 |
| outbound_fee | NUMERIC(18,4) | NOT NULL DEFAULT 0 | 出库操作费 |
| transport_fee | NUMERIC(18,4) | NOT NULL DEFAULT 0 | 运输费 |
| other_fee | NUMERIC(18,4) | NOT NULL DEFAULT 0 | 其他费用 |
| currency_code | CHAR(3) | NOT NULL | 币种 |
| mom_change_pct | NUMERIC(8,2) | NULL | 环比变化 %（相对上月） |
| computed_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 计算时间 |

**唯一约束**：`uk_cost_month(bill_month, warehouse_code)`（可重算覆盖）

---

### 3.8 `mart_risk_sku` — 风险 SKU 排行快照表（分析层）

排序规则：**第一库存年龄（desc），第二库存数量（desc）**，取 TOP20。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| snapshot_date | DATE | NOT NULL | 快照日期 |
| sku | VARCHAR(64) | NOT NULL | SKU |
| product_name | VARCHAR(255) | NULL | 商品名称 |
| quantity | INT | NOT NULL | 库存数量 |
| warehouse_age | INT | NOT NULL | 库龄（天） |
| age_bucket | VARCHAR(16) | NOT NULL | 年龄分桶 |
| risk_rank | INT | NOT NULL | 风险名次（1 = 最高风险） |
| warehouse_code | VARCHAR(32) | NOT NULL | 仓库编码 |
| computed_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 计算时间 |

**索引**：`ix_risk_date(snapshot_date, risk_rank)`

---

### 3.9 `mart_monthly_reports` — 月度报告表（分析层）

《德国海外仓成本健康报告》。

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| report_month | CHAR(7) | NOT NULL | 报告月份 `YYYY-MM` |
| warehouse_code | VARCHAR(32) | NOT NULL | 仓库编码 |
| title | VARCHAR(255) | NOT NULL | 报告标题 |
| cost_change | JSONB | NULL | 成本变化（总成本/环比/趋势） |
| cost_drivers | JSONB | NULL | 费用原因（结构占比/主要驱动项） |
| inventory_risk | JSONB | NULL | 库存风险（分桶占比/风险SKU） |
| recommendations | JSONB | NULL | 优化建议 |
| content_md | TEXT | NULL | 报告正文（Markdown） |
| status | VARCHAR(16) | NOT NULL DEFAULT 'draft' | `draft/published` |
| generated_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 生成时间 |

**唯一约束**：`uk_report_month(report_month, warehouse_code)`

---

### 3.10 `sync_logs` — 数据同步日志表（运维）

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| id | BIGSERIAL | PK | 自增主键 |
| task_name | VARCHAR(64) | NOT NULL | 任务名（如 `sync_bills`） |
| endpoint | VARCHAR(64) | NOT NULL | 来源接口 |
| status | VARCHAR(16) | NOT NULL | `running/success/failed` |
| records_affected | INT | NULL | 处理记录数 |
| message | TEXT | NULL | 结果/错误信息 |
| started_at | TIMESTAMPTZ | NOT NULL DEFAULT now() | 开始时间 |
| finished_at | TIMESTAMPTZ | NULL | 结束时间 |

**索引**：`ix_sync_task(task_name, started_at)`

---

## 4. 关系总览（ER 摘要）

```
dim_warehouse 1 ──── n stg_bills
stg_bills     1 ──── n stg_bill_fee_items
dim_warehouse 1 ──── n stg_inventory_age
dim_warehouse 1 ──── n stg_inventory_status
dim_warehouse 1 ──── n mart_monthly_cost_summary
dim_warehouse 1 ──── n mart_risk_sku
dim_warehouse 1 ──── n mart_monthly_reports
fee_category_map （配置表，逻辑关联 stg_bill_fee_items.fee_category）
sync_logs（独立运维表）
```

---

## 5. 关键设计决策

| 决策点 | 方案 | 理由 |
| --- | --- | --- |
| 账单幂等 | `bill_number` 唯一 + UPSERT | 账单可重发/修正，避免重复 |
| 库存数据 | 按 `snapshot_date` 快照 | 库存是时点数，需保留历史做趋势 |
| 费用归类 | 独立 `fee_category_map` 配置表 | 谷仓费用名多变，归类规则可在线调整不改代码 |
| 金额精度 | `NUMERIC(18,4)` | 财务金额，避免浮点误差 |
| 币种 | 每行保留 `currency_code` | 德国仓默认 EUR，但留多币种扩展 |
| 原始报文 | `raw_json` (JSONB) | 对账、排错、字段演进兼容 |
| 环比字段 | 物化 `mom_change_pct` | 查询快，前端无需重算 |

---

## 6. 可扩展性预留

- **多仓**：所有业务表带 `warehouse_code`，新增仓仅需在 `dim_warehouse` 加记录。
- **新增费用类型**：改 `fee_category_map`，不动表结构。
- **年龄阈值**：分桶规则后续可抽到配置表（当前为代码常量 + 落库冗余）。
- **新数据源**：沿用 `stg_*` 原始层 + `mart_*` 分析层模式横向扩展。

---

## 7. 待确认（业务/数据）

1. 谷仓各接口**真实返回字段名**（登录开放平台后校准，见 `api-field-mapping.md`）。
2. `billing_export` 明细是否到 **SKU 粒度**（影响 `related_sku` 与费用归因精度）。
3. 德国仓账单的**币种**是否固定 EUR，是否存在跨币种账单。
