# 谷仓 GoodCang API 字段映射文档

> 项目：GoodCang Overseas Warehouse Cost Intelligence
> 数据源：谷仓 GoodCang Open API
> 校准日期：2026-09-01（基于官方登录后的接口文档截图）

---

## 0. 接入说明

| 项 | 内容 |
| --- | --- |
| 生产域名 | `https://oms.goodcang.net`（base URL） |
| UAT 域名 | `https://uat-oms.eminxing.com`（联调测试） |
| 接口路径前缀 | `/public_open`（在 GOODCANG_BASE_URL 之后拼接） |
| 鉴权方式 | **HTTP Header 鉴权**（无 MD5 签名） |
| 必填 Header | `app-token: <AppToken>` 和 `app-key: <AppKey>` |
| Content-Type | `application/json`（统一 POST + JSON） |
| 响应风格 | V2 JSON：`{"code": 0, "message": "ok", "data": ...}`，`code=0` 表示成功 |
| 业务列表位置 | `data.list`（部分接口如 export 直接把内容放在 `data`） |
| 目标仓 | 德国海外仓（`GOODCANG_WAREHOUSE_CODE`） |
| 密钥管理 | 一律放 `.env`（`GOODCANG_APP_TOKEN` / `GOODCANG_APP_KEY`），禁止入库代码 |

**HTTP 状态码语义：**

| Code | 含义 | 处理 |
| --- | --- | --- |
| 200 | 成功 | 解析 `data` |
| 401 | TOKEN/KEY 错误 | 客户端配置问题，不重试 |
| 403 | 触发限流 | 不重试，由调用方退避 |
| 404 | 接口不存在 | 客户端配置错误，不重试 |
| 5xx | 系统异常 | 触发 tenacity 重试（最多 `GOODCANG_MAX_RETRY` 次） |

---

## 1. 接口一：`billing_list` — 账单列表

**URL**：`POST {BASE_URL}/public_open/finance/billing_list`
**用途**：拉取账单主列表，是「月度成本」的口径来源。

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `account_code` | String(20) | 是 | 客户代码（即 AppToken 对应账号） |
| `begin_bill_to_time` | String | 否 | 账单结束时间起，格式 `YYYY-MM-DD HH:MM:SS`，示例 `2021-04-12 00:00:00` |
| `end_bill_to_time` | String | 否 | 账单结束时间止 |
| `bill_number` | String(20) | 否 | 账单号（精确查询），示例 `B2021072902560029` |
| `page` | Int | 否 | 分页页码，默认 1 |
| `page_size` | Int | 否 | 分页条数，最大 200，默认 20 |

### 响应字段

```json
{
  "code": 0,
  "ask": "Success",
  "message": "success",
  "data": {
    "list": [
      {
        "bill_number": "B20260901G150560003",
        "account_code": "ACG1505604",
        "bill_from_time": "2026-08-01 00:00:00",
        "bill_to_time": "2026-08-31 23:59:59",
        "bill_file_path": "https://oms.goodcang.com/api/v1/protect_res/download_billing_file?path=...xlsx",
        "sign_body_name": "HONGKONG LITTLE MAGIC INTERNATIONAL TRADING LIMITED",
        "sign_business_type_list_text": "海外仓储",
        "service_body_name": "ETARGET LIMITED",
        "all_total": [
          { "currency_code": "EUR", "balance": "25869.46" },
          { "currency_code": "USD", "balance": "0" }
        ],
        "start_balance": [ { "currency_code": "EUR", "balance": "-13549.21" } ],
        "end_balance": [ { "currency_code": "EUR", "balance": "-19702.83" } ],
        "cash_back_balance": [ { "currency_code": "EUR", "balance": "0" } ]
      }
    ],
    "total": 45
  }
}
```

> **实调校准（2026-09-01）**：`all_total` / `start_balance` / `end_balance` /
> `cash_back_balance` 均为 **多币种数组**（共 19 种币种），并非单个对象。
> 每个元素是 `{currency_code, balance}`，`balance` 为字符串。欧洲仓业务应
> 优先取 `EUR` 的非零值。

### 字段映射

| 业务字段 | 谷仓字段 | 类型 | 落库表.字段 | 转换规则 |
| --- | --- | --- | --- | --- |
| 账单号 | `data.list[].bill_number` | string | `stg_bills.bill_number` | 主键/幂等键，UPSERT |
| 账号编码 | `data.list[].account_code` | string | `stg_bills.account_code` | 直存 |
| 账单开始 | `data.list[].bill_from_time` | datetime | `stg_bills.bill_from_time` | 统一 UTC 存储 |
| 账单结束 | `data.list[].bill_to_time` | datetime | `stg_bills.bill_to_time` | 统一 UTC 存储 |
| 账单总金额 | `data.list[].all_total[].balance`（EUR 优先） | decimal | `stg_bills.all_total` | String → NUMERIC(18,4) |
| 币种 | `data.list[].all_total[].currency_code`（非零优先） | string | `stg_bills.currency_code` | 直存 |
| 签约主体 | `data.list[].sign_body_name` | string | (raw_json) | 备份 |
| 业务类型 | `data.list[].sign_business_type_list_text` | string | (raw_json) | 备份 |
| 服务主体 | `data.list[].service_body_name` | string | (raw_json) | 备份 |

**派生字段**：

| 派生 | 规则 | 落库 |
| --- | --- | --- |
| `bill_month` | 由 `bill_to_time` 取 `YYYY-MM` | `stg_bills.bill_month` |
| `warehouse_code` | 优先取响应字段，否则由请求上下文补充 | `stg_bills.warehouse_code` |

---

## 2. 接口二：`billing_export` — 账单文件导出（base64）

**URL**：`POST {BASE_URL}/public_open/finance/billing_export`
**用途**：根据账单号下载账单文件，**返回 base64 字符串**（不是结构化 JSON）。

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `bill_number_list` | String[] | 是 | 账单号列表（最多 50 个），示例 `["B2021072902560029"]` |

### 响应

```json
{
  "code": 0,
  "message": "ok",
  "data": "BASE64_STRING_OF_XLSX_OR_ZIP"
}
```

> 单账单返回 xlsx 的 base64；多账单返回 zip 的 base64。V1 暂存 base64 原始字符串到 `stg_bill_fee_items.raw_json`，二期可解 xlsx 落费用行明细。

---

## 3. 接口三：`inventory_age_list` — 库存库龄列表

**URL**：`POST {BASE_URL}/public_open/inventory/inventory_age_list`
**用途**：获取系统中存在库龄的库龄信息（了解商品批次存放于仓库的周期时长）。

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | Int | 否 | 分页页码，默认 1 |
| `page_size` | Int | 否 | 分页条数，最大 200，默认 20 |
| `warehouse_code` | String(30) | 是（之一）| 区域仓库代码，如 `USEA`、`DE` |
| `warning_age_type` | String(enum) | 否 | 库龄预警枚举，参考 `_Enum/Inventory/InventoryAgeWarningTypeEnum` |
| `age_from` | Int | 否 | 库龄起始值（天） |
| `age_to` | Int | 否 | 库龄结束值（天） |
| `fifo_time_from` | String | 否 | 上架时间起始 `YYYY-MM-DD HH:MM:SS` |
| `fifo_time_to` | String | 否 | 上架时间结束 `YYYY-MM-DD HH:MM:SS` |
| `quantity_from` | Int | 否 | 在库库存起始值 |
| `quantity_to` | Int | 否 | 在库库存结束值 |
| `product_sku_list` | String[] | 否 | 商品编码列表（最多 50 个），示例 `["JS20201114-AAAAAAAAAAAAAAAAA"]` |
| `product_title` | String(100) | 否 | 商品中文名称（模糊匹配），示例 `"中国好产品"` |
| `product_title_en` | String(100) | 否 | 商品英文名称（模糊匹配），示例 `goodcang` |

### 响应字段

```json
{
  "code": 0,
  "message": "Success",
  "data": {
    "list": [
      {
        "iba_id": 17417338,
        "warehouse_code": "DE",
        "product_sku": "SLT0004",
        "product_barcode": "G15056-D9278239852",
        "iba_quantity": 34,
        "iba_fifo_time": "2025-04-22",
        "iba_warning_age": 0,
        "product_title": "万向水龙头升级款-三种出水方式白色",
        "product_title_en": "Faucet",
        "warehouse_desc": "德国区",
        "warehouse_age": 498,
        "expiration_date": ""
      }
    ],
    "total": 325
  }
}
```

> **实调校准（2026-09-01）**：字段前缀是 **`iba_`**（不是文档早期误写的 `lba_`）：
> `iba_id` / `iba_quantity` / `iba_fifo_time` / `iba_warning_age`。
> `warehouse_code=DE` 表示德国区，`warehouse_desc=德国区`。

### 字段映射

| 业务字段 | 谷仓字段 | 类型 | 落库表.字段 | 转换规则 |
| --- | --- | --- | --- | --- |
| SKU | `data.list[].product_sku` | string | `stg_inventory_age.sku` | 直存 |
| 商品名称（中） | `data.list[].product_title` | string | `stg_inventory_age.product_name` | 优先中 |
| 商品名称（英） | `data.list[].product_title_en` | string | (raw_json) | 备份 |
| 在库库存 | `data.list[].iba_quantity` | int | `stg_inventory_age.quantity` | 直存 |
| 库龄（天） | `data.list[].warehouse_age` | int | `stg_inventory_age.warehouse_age` | 直存 |
| 上架时间 | `data.list[].iba_fifo_time` | date | `stg_inventory_age.inbound_time` | 字符串转 date |
| 预警库龄 | `data.list[].iba_warning_age` | int | (raw_json) | 备份 |
| 仓库描述 | `data.list[].warehouse_desc` | string | (raw_json) | 备份 |
| 仓库编码 | `data.list[].warehouse_code` | string | `stg_inventory_age.warehouse_code` | 直存 |

**派生：年龄分桶**

| age_bucket | 区间（天） | 中文 |
| --- | --- | --- |
| `healthy` | 0–90 | 健康库存 |
| `watch` | 90–180 | 关注库存 |
| `stale` | 180–365 | 呆滞库存 |
| `critical` | 365+ | 严重呆滞库存 |

---

## 4. 接口四：`get_product_inventory` — 产品库存查询

**URL**：`POST {BASE_URL}/public_open/inventory/get_product_inventory`
**用途**：查询谷仓系统内商品库存信息。

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `page` | Int | 是 | 当前页，默认 1 |
| `pageSize` | Int | 是 | 每页数据条数，最大 200，默认 20（**驼峰命名**） |
| `warehouse_code` | String(32) | 是（之一）| 区域仓库代码 |
| `warehouse_code_arr` | String[] | 是（之一）| 区域仓库代码数组（**单次最多 20 个**） |
| `product_sku` | String(24) | 是（之一）| 商品 SKU |
| `product_sku_arr` | String[] | 是（之一）| 商品 SKU 数组（**单次最多 200 个**） |
| `batch_code` | String(enum) | 否 | 批次属性枚举，参考 `_Enum/Inventory/batchAttributeCodeEnum` |
| `batch_value_list` | String[] | 否 | 批次值数组（可指定多范围查询） |

### 响应字段

```json
{
  "code": 0,
  "message": "Success",
  "count": 325,
  "nextPage": 2,
  "pagination": "...",
  "data": [
    {
      "warehouse_code": "DE",
      "warehouse_desc": "德国区",
      "product_sku": "FRW0005",
      "product_barcode": "G15056-H8009215890",
      "product_title": "复古水龙头 陶瓷高款",
      "total_onway": 120,
      "transfer_onway": 0,
      "onway": "120",
      "pending": "0",
      "sellable": "149",
      "unsellable": "0",
      "reserved": "1",
      "stocking": "0",
      "shipped": "545",
      "pi_unsellable_reserved": 0,
      "pi_unsellable_shipped": 0,
      "pi_no_stock": "0",
      "pi_freeze": "0",
      "pi_warning_qty": "0",
      "tune_out": "0",
      "tune_in": "0",
      "sold_shared": "0",
      "product_sales_value": "0.00",
      "product_freeze_status": 0,
      "product_freeze_status_text": "正常"
    }
  ]
}
```

> **实调校准（2026-09-01）**：
> - ``data`` 字段直接是**数组**（不是 ``{list: [...]}`` 包裹）
> - 多数数量字段是**字符串**（``"120"``），解析时需转 int
> - 顶层有 ``count`` / ``nextPage`` / ``pagination`` 分页字段

### 字段映射

| 业务字段 | 谷仓字段 | 类型 | 落库表.字段 | 转换规则 |
| --- | --- | --- | --- | --- |
| SKU | `data[].product_sku` | string | `stg_inventory_status.sku` | 直存 |
| 仓库编码 | `data[].warehouse_code` | string | `stg_inventory_status.warehouse_code` | 直存 |
| 良品可售 | `data[].sellable` | string | `stg_inventory_status.sellable` | 字符串转 int |
| 不良品可售 | `data[].unsellable` | string | `stg_inventory_status.unsellable` | 字符串转 int |
| 良品待出库 | `data[].reserved` | string | `stg_inventory_status.reserved` | 字符串转 int |
| 良品已出库 | `data[].shipped` | string | (raw_json) | 暂存 |
| 海外在途 | `data[].onway` | string | `stg_inventory_status.onway` | 字符串转 int |
| 待上架 | `data[].pending` | string | (raw_json) | 备份 |
| 冻结数量 | `data[].pi_freeze` | string | (raw_json) | 备份 |
| 预警库存 | `data[].pi_warning_qty` | string | (raw_json) | 备份 |
| 缺货数量 | `data[].pi_no_stock` | string | (raw_json) | 备份 |
| 备货数量 | `data[].stocking` | string | (raw_json) | 备份 |

**派生**：库存压力等级（在分析引擎中计算）：

| pressure_level | 规则 |
| --- | --- |
| `critical` | `pi_warning_qty >= sellable`（预警库存 ≥ 可售） |
| `warning` | `pi_warning_qty > 0` 或 `onway > sellable` |
| `normal` | 其他 |

---

## 5. 接口 → 表 映射总览

| GoodCang 接口 | 用途 | 目标表 | 数据性质 | 幂等/唯一键 |
| --- | --- | --- | --- | --- |
| `billing_list` | 月度账单 | `stg_bills` | 账单（可修正） | `bill_number` |
| `billing_export` | 账单文件 base64 | `stg_bill_fee_items` | 二进制原文件 | `bill_number + fee_name='[export]'` |
| `inventory_age_list` | 库存年龄 | `stg_inventory_age` | 快照 | `snapshot_date + sku + warehouse_code` |
| `get_product_inventory` | 当前库存状态 | `stg_inventory_status` | 快照 | `snapshot_date + sku + warehouse_code` |

**下游分析产物**：

| 来源表 | 分析产物表 | 用途 |
| --- | --- | --- |
| `stg_bills` + `stg_bill_fee_items` | `mart_monthly_cost_summary` | 月度成本 / 费用结构 / 环比 |
| `stg_inventory_age` | `mart_risk_sku` | TOP20 风险 SKU |
| 以上全部 | `mart_monthly_reports` | 《德国海外仓成本健康报告》 |

---

## 6. 同步策略（已实现）

| 接口 | 频率 | 说明 |
| --- | --- | --- |
| `billing_list` | 每日（凌晨 02:00） | 拉最近 3 个月，UPSERT |
| `billing_export` | 每日 / 账单生成后 | 按 bill_number 拉 base64 文件 |
| `inventory_age_list` | 每日 | 全量快照（按 warehouse_code） |
| `get_product_inventory` | 每日 | 全量快照 |

---

## 7. 校准历史

- **2026-09-01（实调校准，4 接口真实连通）**：
  - 鉴权方式确认为 **HTTP Header**（非 MD5 签名）
  - 接口方法确认为 **POST + JSON**（非 GET + query）
  - 生产域名确认为 `https://oms.goodcang.net`（非 open.goodcang.com）
  - 4 个接口路径前缀为 `/public_open/`
  - `all_total` / `start_balance` / `end_balance` / `cash_back_balance` 均为 **19 币种数组**（非单个对象），优先取 EUR 非零值
  - 新增字段 `sign_body_name`（签约主体）/ `sign_business_type_list_text`（业务类型）/ `service_body_name`（服务主体）
  - `inventory_age_list` 字段前缀为 **`iba_`**（非 `lba_`）：`iba_id`/`iba_quantity`/`iba_fifo_time`/`iba_warning_age`
  - `get_product_inventory` 的 `data` 直接是**数组**（非 `{list}`），数量字段多为**字符串**
  - 德国区 `warehouse_code = DE`，仓库描述「德国区」
  - 实调账单：total=45 条（8 月账单），德国区库存库龄 total=325 条
- **2026-09-01**：基于官方文档截图完成首轮字段校准
  - 接口路径前缀为 `/public_open/`
  - `all_total` 是嵌套结构 `{balance, currency_code}`
  - `get_product_inventory` 分页参数是**驼峰** `pageSize`（不是 `page_size`）
  - 金额在响应中为 **String** 类型（用 `Decimal` 解析）
