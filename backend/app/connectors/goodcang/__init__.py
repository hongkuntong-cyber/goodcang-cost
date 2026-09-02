"""谷仓 GoodCang Open Platform 连接器。

模块结构：
- client    : 底层 HTTP 客户端（HTTP Header 鉴权、统一 POST + JSON、超时、重试）
- schemas   : 四个接口的请求/响应 Pydantic 模型
- endpoints : 四个接口的高层方法（带结构化返回）

所有方法都是 async，且失败会按配置自动重试（5xx 触发，4xx 不重试）。
"""
from app.connectors.goodcang.client import GoodCangAPIError, GoodCangClient
from app.connectors.goodcang.endpoints import GoodCangEndpoints
from app.connectors.goodcang.schemas import (
    BillItem,
    BillingExportRequest,
    BillingListData,
    BillingListRequest,
    InventoryAgeItem,
    InventoryAgeListData,
    InventoryAgeListRequest,
    ProductInventoryData,
    ProductInventoryItem,
    ProductInventoryRequest,
)

__all__ = [
    "GoodCangClient",
    "GoodCangAPIError",
    "GoodCangEndpoints",
    "BillItem",
    "BillingListRequest",
    "BillingListData",
    "BillingExportRequest",
    "InventoryAgeItem",
    "InventoryAgeListRequest",
    "InventoryAgeListData",
    "ProductInventoryItem",
    "ProductInventoryRequest",
    "ProductInventoryData",
]
