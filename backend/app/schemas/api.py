"""API 响应的 Pydantic 模型（供 FastAPI 路由 + 前端消费）。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    app: str
    env: str


class CostTrendItem(BaseModel):
    month: str
    total: float
    storage: float
    transport: float
    mom_pct: float | None = None


class CostStructureItem(BaseModel):
    category: str
    label: str
    amount: float


class InventoryBucket(BaseModel):
    bucket: str
    label: str
    sku_count: int
    quantity: int
    qty_pct: float


class RiskSkuItem(BaseModel):
    rank: int
    sku: str
    product_name: str | None
    quantity: int
    warehouse_age: int
    age_bucket: str
    label: str


class MonthlyReportResponse(BaseModel):
    report_month: str
    title: str
    cost_change: dict[str, Any]
    cost_drivers: dict[str, Any]
    inventory_risk: dict[str, Any]
    recommendations: list[dict[str, str]]
    content_md: str
    status: str


class SyncResultResponse(BaseModel):
    bills: int
    fee_items: int
    inventory_age: int
    inventory_status: int