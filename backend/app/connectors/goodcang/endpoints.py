"""谷仓 4 个业务接口的高层封装。

接口路径与方法（2026-09-01 校准自官方文档）：

| 接口                 | HTTP | 路径                                            |
|----------------------|------|-------------------------------------------------|
| 账单列表             | POST | /public_open/finance/billing_list               |
| 账单导出（base64）   | POST | /public_open/finance/billing_export             |
| 库存库龄列表         | POST | /public_open/inventory/inventory_age_list       |
| 产品库存查询         | POST | /public_open/inventory/get_product_inventory    |

鉴权由 :class:`GoodCangClient` 通过 HTTP Header 自动注入（app-token / app-key）。
"""
from __future__ import annotations

import logging

from app.connectors.goodcang.client import GoodCangClient
from app.connectors.goodcang.schemas import (
    BillingExportRequest,
    BillingListRequest,
    InventoryAgeListRequest,
    ProductInventoryRequest,
)

logger = logging.getLogger(__name__)


class GoodCangEndpoints:
    """对 Step 4 同步任务暴露的 4 个接口（统一 POST + JSON）。"""

    PATH_BILLING_LIST = "/public_open/finance/billing_list"
    PATH_BILLING_EXPORT = "/public_open/finance/billing_export"
    PATH_INVENTORY_AGE_LIST = "/public_open/inventory/inventory_age_list"
    PATH_PRODUCT_INVENTORY = "/public_open/inventory/get_product_inventory"

    def __init__(self, client: GoodCangClient) -> None:
        self.client = client

    async def billing_list(self, req: BillingListRequest) -> dict:
        """获取月度账单列表（原始 dict，保留完整字段）。"""
        logger.info(
            "billing_list begin=%s end=%s account=%s page=%s",
            req.begin_bill_to_time, req.end_bill_to_time, req.account_code, req.page,
        )
        return await self.client.call(
            self.PATH_BILLING_LIST,
            req.model_dump(exclude_none=True),
        )

    async def billing_export(self, req: BillingExportRequest) -> dict:
        """下载账单文件（base64 字符串，在 data 字段中）。

        返回的 data 字段是 base64 编码的 xlsx/zip 字符串，调用方负责解码落盘。
        """
        logger.info("billing_export bill_number_list=%s", req.bill_number_list)
        return await self.client.call_raw_post(
            self.PATH_BILLING_EXPORT,
            req.model_dump(exclude_none=True),
        )

    async def inventory_age_list(self, req: InventoryAgeListRequest) -> dict:
        """获取库存库龄列表（每条含 warehouse_code / product_sku / lba_* 字段）。"""
        logger.info(
            "inventory_age_list warehouse=%s page=%s",
            req.warehouse_code, req.page,
        )
        return await self.client.call(
            self.PATH_INVENTORY_AGE_LIST,
            req.model_dump(exclude_none=True),
        )

    async def product_inventory(self, req: ProductInventoryRequest) -> dict:
        """获取产品库存（可用/锁定/在途/已出库 等库存分项）。"""
        logger.info(
            "product_inventory warehouse=%s sku=%s",
            req.warehouse_code, req.product_sku,
        )
        return await self.client.call(
            self.PATH_PRODUCT_INVENTORY,
            req.model_dump(exclude_none=True),
        )

    # ---- 便捷工厂 ----
    @classmethod
    def build(cls) -> "tuple[GoodCangClient, GoodCangEndpoints]":
        """构造一对 (client, endpoints)；调用方用 async with 管理生命周期。"""
        client = GoodCangClient()
        return client, cls(client)
