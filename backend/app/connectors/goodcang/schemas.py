"""谷仓 4 个接口的请求/响应 Pydantic 模型（2026-09-01 校准自官方文档）。

字段命名规则：
- 全部使用截图中的真实英文字段名（如 bill_number / lba_quantity / lba_warning_age 等）。
- 金额相关字段在谷仓是 **String** 类型，解析为 ``Decimal``，避免浮点误差。
- 响应统一 V2 风格 ``{"code": 0, "message": "ok", "data": ...}``。
- 业务列表放在 ``data.list`` 字段下，部分接口外层是 list（export 返回 base64 字符串）。
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, List

from pydantic import BaseModel, ConfigDict, Field


# ===========================================================================
# 通用响应外壳
# ===========================================================================
class GoodCangResponse(BaseModel):
    """谷仓 V2 JSON 风格响应外壳。"""

    model_config = ConfigDict(extra="ignore")

    code: int | str | None = Field(default=None, description="0 成功，其他失败")
    message: str | None = None
    data: Any = None


# ===========================================================================
# 1. billing_list — 账单列表
# ===========================================================================
class BillingListRequest(BaseModel):
    """POST /public_open/finance/billing_list 请求体。"""

    model_config = ConfigDict(extra="ignore")

    account_code: str | None = Field(
        default=None, description="客户代码（可选，3-20 位，如 ACG1505603；不传则拉全部客户）"
    )
    begin_bill_to_time: str | None = Field(
        default=None, description="账单结束时间起，格式 YYYY-MM-DD HH:MM:SS"
    )
    end_bill_to_time: str | None = Field(
        default=None, description="账单结束时间止，格式 YYYY-MM-DD HH:MM:SS"
    )
    bill_number: str | None = Field(default=None, description="账单号（精确查询）", max_length=20)
    page: int = Field(default=1, ge=1, description="分页页码")
    page_size: int = Field(default=20, ge=1, le=200, description="分页条数（最大 200）")


class BalanceItem(BaseModel):
    """金额对象（含 balance + currency_code）。"""

    model_config = ConfigDict(extra="ignore")

    balance: Decimal | None = Field(default=None, description="金额（String 转 Decimal）")
    currency_code: str | None = Field(default=None, description="币种，如 CZK")


class BillItem(BaseModel):
    """单条账单主记录。

    注意（2026-09-01 实调校准）：all_total / start_balance / end_balance /
    cash_back_balance 均为 **多币种数组**（每个元素 {currency_code, balance}），
    共 19 种币种（RMB/USD/EUR/GBP/...），欧洲仓业务应优先取 EUR 非零值。
    """

    model_config = ConfigDict(extra="ignore")

    account_code: str | None = Field(default=None)
    all_total: List[BalanceItem] = Field(
        default_factory=list, description="账单总金额（多币种数组）"
    )
    bill_file_path: str | None = Field(default=None, description="账单文件地址（FILE_PATH）")
    bill_from_time: datetime | str | None = Field(default=None, description="账单开始日期")
    bill_number: str = Field(description="账单号（示例：B20260901G150560003）")
    bill_to_time: datetime | str | None = Field(default=None, description="账单结束日期")
    sign_body_name: str | None = Field(default=None, description="签约主体名称")
    sign_business_type_list_text: str | None = Field(default=None, description="业务类型（如 海外仓储/中转代发）")
    service_body_name: str | None = Field(default=None, description="服务主体名称")
    cash_back_balance: List[BalanceItem] = Field(
        default_factory=list, description="返现金额（多币种数组）"
    )
    end_balance: List[BalanceItem] = Field(
        default_factory=list, description="期末余额（多币种数组）"
    )
    start_balance: List[BalanceItem] = Field(
        default_factory=list, description="期初余额（多币种数组）"
    )
    total: int | None = Field(default=None, description="总记录数")


class BillingListData(BaseModel):
    """``data`` 字段（list + total）。"""

    model_config = ConfigDict(extra="ignore")

    list: List[BillItem] = Field(default_factory=list)
    total: int | None = None


# ===========================================================================
# 2. billing_export — 账单导出（base64 字符串）
# ===========================================================================
class BillingExportRequest(BaseModel):
    """POST /public_open/finance/billing_export 请求体。"""

    model_config = ConfigDict(extra="ignore")

    bill_number_list: List[str] = Field(
        default_factory=list, description="账单号列表（String[]，最多 50 个）", max_length=50
    )


# 响应 data 是 base64 字符串（在 GoodCangResponse.data 字段里原样取）
# 说明：将 base64 字符串解码后是 xlsx（单账单）或 zip（多账单压缩包）


# ===========================================================================
# 3. inventory_age_list — 库存库龄列表
# ===========================================================================
class InventoryAgeListRequest(BaseModel):
    """POST /public_open/inventory/inventory_age_list 请求体。"""

    model_config = ConfigDict(extra="ignore")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200, description="最大 200")
    warehouse_code: str | None = Field(
        default=None, description="区域仓库代码（必填之一：USEA / DE 等）", max_length=30
    )
    warning_age_type: str | None = Field(
        default=None, description="库龄预警枚举（_Enum/Inventory/InventoryAgeWarningTypeEnum）"
    )
    age_from: int | None = Field(default=None, description="库龄起始值（天）")
    age_to: int | None = Field(default=None, description="库龄结束值（天）")
    fifo_time_from: str | None = Field(
        default=None, description="上架时间起始（YYYY-MM-DD HH:MM:SS）"
    )
    fifo_time_to: str | None = Field(
        default=None, description="上架时间结束（YYYY-MM-DD HH:MM:SS）"
    )
    quantity_from: int | None = Field(default=None, description="在库库存起始值")
    quantity_to: int | None = Field(default=None, description="在库库存结束值")
    product_sku_list: List[str] | None = Field(
        default=None, description="商品编码列表（String[]，最多 50 个）", max_length=50
    )
    product_title: str | None = Field(default=None, description="商品中文名称（模糊）", max_length=100)
    product_title_en: str | None = Field(
        default=None, description="商品英文名称（模糊）", max_length=100
    )


class InventoryAgeItem(BaseModel):
    """库存库龄单条记录。

    注意（2026-09-01 实调校准）：字段前缀是 **iba_**（不是 lba_）：
    - iba_id / iba_quantity / iba_fifo_time / iba_warning_age
    - warehouse_age 表示库龄（天）
    """

    model_config = ConfigDict(extra="ignore")

    iba_id: int | None = Field(default=None, description="库龄记录 ID")
    warehouse_code: str | None = Field(default=None, description="区域仓库代码（如 DE）")
    product_sku: str = Field(description="商品 SKU")
    product_barcode: str | None = Field(default=None, description="商品条码")
    iba_quantity: int | None = Field(default=None, description="在库库存")
    iba_fifo_time: str | None = Field(default=None, description="上架时间（YYYY-MM-DD）")
    iba_warning_age: int | None = Field(default=None, description="预警库龄（天）")
    product_title: str | None = Field(default=None, description="商品中文名称")
    product_title_en: str | None = Field(default=None, description="商品英文名称")
    warehouse_desc: str | None = Field(default=None, description="仓库名称（如 德国区）")
    warehouse_age: int | None = Field(default=None, description="库龄（天）")
    expiration_date: str | None = Field(default=None, description="过期日期")


class InventoryAgeListData(BaseModel):
    """``data`` 字段（list + total）。"""

    model_config = ConfigDict(extra="ignore")

    list: List[InventoryAgeItem] = Field(default_factory=list)
    total: int | None = None


# ===========================================================================
# 4. get_product_inventory — 产品库存查询
# ===========================================================================
class ProductInventoryRequest(BaseModel):
    """POST /public_open/inventory/get_product_inventory 请求体。

    注意：截图里字段名是 ``pageSize``（驼峰），不是 ``page_size``。
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    page: int = Field(default=1, ge=1, description="当前页")
    pageSize: int = Field(
        default=20, ge=1, le=200, description="每页条数（驼峰命名，最大 200）"
    )
    warehouse_code: str | None = Field(default=None, description="区域仓库代码", max_length=32)
    warehouse_code_arr: List[str] | None = Field(
        default=None, description="区域仓库代码数组（批量查询）", max_length=20
    )
    product_sku: str | None = Field(default=None, description="商品 SKU", max_length=24)
    product_sku_arr: List[str] | None = Field(
        default=None, description="商品 SKU 数组（最多 200）", max_length=200
    )
    batch_code: str | None = Field(
        default=None, description="批次属性枚举（_Enum/Inventory/batchAttributeCodeEnum）"
    )
    batch_value_list: List[str] | None = Field(
        default=None, description="批次值数组（可指定多范围查询）"
    )


class ProductInventoryItem(BaseModel):
    """产品库存单条记录。

    注意（2026-09-01 实调校准）：
    - 该接口 ``data`` 字段直接是**数组**（不是 ``{list: [...]}`` 包裹）
    - 大部分数量字段是**字符串**（如 ``"120"``），部分为 int；统一兼容
    - 顶层还有 ``count`` / ``nextPage`` / ``pagination`` 分页字段
    """

    model_config = ConfigDict(extra="ignore")

    warehouse_code: str | None = Field(default=None, description="区域仓库代码")
    warehouse_desc: str | None = Field(default=None, description="仓库描述")
    product_sku: str | None = Field(default=None, description="商品 SKU")
    product_barcode: str | None = Field(default=None, description="商品条码")
    product_title: str | None = Field(default=None, description="商品名称")
    total_onway: int | str | None = Field(default=None, description="在途总数量（海外+中转+已出库在途）")
    transfer_onway: int | str | None = Field(default=None, description="中转在途数量")
    onway: int | str | None = Field(default=None, description="海外在途数量")
    pending: int | str | None = Field(default=None, description="待上架数量")
    sellable: int | str | None = Field(default=None, description="良品可售数量")
    unsellable: int | str | None = Field(default=None, description="不良品可售数量")
    reserved: int | str | None = Field(default=None, description="良品待出库数量")
    shipped: int | str | None = Field(default=None, description="良品已出库数量")
    pi_unsellable_reserved: int | str | None = Field(default=None, description="不良品待出库数量")
    pi_unsellable_shipped: int | str | None = Field(default=None, description="不良品已出库数量")
    pi_freeze: int | str | None = Field(default=None, description="冻结数量")
    pi_warning_qty: int | str | None = Field(default=None, description="预警库存数量")
    pi_no_stock: int | str | None = Field(default=None, description="缺货数量")
    stocking: int | str | None = Field(default=None, description="备货数量")
    tune_out: int | str | None = Field(default=None, description="调出数量")
    tune_in: int | str | None = Field(default=None, description="调入数量")
    sold_shared: int | str | None = Field(default=None, description="共享销量")
    product_sales_value: str | None = Field(default=None, description="商品销售金额")
    product_freeze_status: int | str | None = Field(default=None, description="商品冻结状态枚举")
    product_freeze_status_text: str | None = Field(default=None, description="商品冻结状态名称")


class ProductInventoryData(BaseModel):
    """``data`` 字段。"""

    model_config = ConfigDict(extra="ignore")

    list: List[ProductInventoryItem] = Field(default_factory=list)
    count: int | None = None
    total: int | None = None
