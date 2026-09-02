"""同步服务离线测试：mock 客户端 + 内存库，验证落库、幂等、费用归类、分桶。

2026-09-01 校准：mock 数据结构对齐谷仓真实响应。
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
from sqlalchemy import select

from app.connectors.goodcang import GoodCangClient, GoodCangEndpoints
from app.models import (
    DimWarehouse,
    FeeCategoryMap,
    StgBill,
    StgBillFeeItem,
    StgInventoryAge,
)
from app.services.sync_service import SyncService, bucket_age


pytestmark = pytest.mark.asyncio


@pytest.fixture()
def seeded_wh(session):
    session.add(
        DimWarehouse(
            warehouse_code="DE1",
            warehouse_name="德国一仓",
            country_code="DE",
            currency_code="EUR",
        )
    )
    session.add(FeeCategoryMap(match_keyword="仓储", fee_category="storage", priority=1))
    session.add(FeeCategoryMap(match_keyword="运输", fee_category="transport", priority=1))
    session.commit()
    return session


def _client_with(handler) -> tuple[GoodCangClient, GoodCangEndpoints]:
    client = GoodCangClient()
    client._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=client.timeout
    )  # noqa: SLF001
    return client, GoodCangEndpoints(client)


# ---------------------------------------------------------------------------
# 真实谷仓响应结构（V2 风格）
# ---------------------------------------------------------------------------
def _billing_handler(request):
    """billing_list: data.list[]，每条含多币种数组 all_total[]（EUR 优先）。"""
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "ok",
            "data": {
                "list": [
                    {
                        "bill_number": "B20260801",
                        "account_code": "ACC1",
                        "bill_from_time": "2026-08-01 00:00:00",
                        "bill_to_time": "2026-08-31 23:59:59",
                        "all_total": [
                            {"currency_code": "RMB", "balance": "0"},
                            {"currency_code": "EUR", "balance": "1500.00"},
                            {"currency_code": "USD", "balance": "0"},
                        ],
                        "sign_body_name": "测试主体",
                        "sign_business_type_list_text": "海外仓储",
                        "service_body_name": "ETARGET LIMITED",
                        "warehouse_code": "DE1",
                    }
                ],
                "total": 1,
            },
        },
    )


def _fee_handler(request):
    """billing_export: data 是 base64 字符串（V1 暂存为 raw）。"""
    return httpx.Response(
        200,
        json={"code": 0, "message": "ok", "data": "VGVzdEZpbGVDb250ZW50"},
    )


def _age_handler(request):
    """inventory_age_list: data.list[]，字段为 iba_* 与 product_sku。"""
    return httpx.Response(
        200,
        json={
            "code": 0,
            "message": "ok",
            "data": {
                "list": [
                    {
                        "iba_id": 1,
                        "warehouse_code": "DE1",
                        "product_sku": "SKU1",
                        "product_barcode": "BAR1",
                        "iba_quantity": 10,
                        "iba_fifo_time": "2025-08-01",
                        "iba_warning_age": 30,
                        "product_title": "商品1",
                        "warehouse_desc": "德国一仓",
                        "warehouse_age": 400,
                    },
                    {
                        "iba_id": 2,
                        "warehouse_code": "DE1",
                        "product_sku": "SKU2",
                        "product_barcode": "BAR2",
                        "iba_quantity": 5,
                        "iba_fifo_time": None,
                        "iba_warning_age": 30,
                        "product_title": "商品2",
                        "warehouse_desc": "德国一仓",
                        "warehouse_age": 50,
                    },
                ],
                "total": 2,
            },
        },
    )


# ---------------------------------------------------------------------------
# 单元测试
# ---------------------------------------------------------------------------
async def test_bucket_age_boundaries():
    assert bucket_age(89) == "healthy"
    assert bucket_age(90) == "watch"
    assert bucket_age(179) == "watch"
    assert bucket_age(180) == "stale"
    assert bucket_age(364) == "stale"
    assert bucket_age(365) == "critical"


# ---------------------------------------------------------------------------
# 1. 账单
# ---------------------------------------------------------------------------
async def test_sync_bills_upsert(seeded_wh):
    client, ep = _client_with(_billing_handler)
    try:
        svc = SyncService(seeded_wh, client, ep)
        n1 = await svc.sync_bills(begin_bill_to_time="2026-08-01 00:00:00",
                                  end_bill_to_time="2026-08-31 23:59:59")
        n2 = await svc.sync_bills(begin_bill_to_time="2026-08-01 00:00:00",
                                  end_bill_to_time="2026-08-31 23:59:59")  # 幂等
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert n1 == 1 and n2 == 1
    bills = seeded_wh.scalars(select(StgBill)).all()
    assert len(bills) == 1
    assert str(bills[0].all_total) == "1500.0000"
    assert bills[0].currency_code == "EUR"
    assert bills[0].bill_month == "2026-08"


# ---------------------------------------------------------------------------
# 2. 费用明细（base64 落 raw_json）
# ---------------------------------------------------------------------------
async def test_sync_fee_items_saves_base64(seeded_wh):
    client, ep = _client_with(_fee_handler)
    try:
        svc = SyncService(seeded_wh, client, ep)
        n = await svc.sync_fee_items("B20260801")
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert n == 1
    items = seeded_wh.scalars(select(StgBillFeeItem)).all()
    assert len(items) == 1
    assert items[0].bill_number == "B20260801"
    assert "VGVzdEZpbGVDb250ZW50" in str(items[0].raw_json)


# ---------------------------------------------------------------------------
# 3. 库存库龄
# ---------------------------------------------------------------------------
async def test_sync_inventory_age_bucket(seeded_wh):
    client, ep = _client_with(_age_handler)
    try:
        svc = SyncService(seeded_wh, client, ep)
        n = await svc.sync_inventory_age(snapshot_date=date(2026, 9, 1))
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert n == 2
    rows = seeded_wh.scalars(select(StgInventoryAge)).all()
    by_sku = {r.sku: r.age_bucket for r in rows}
    assert by_sku["SKU1"] == "critical"  # 400 天
    assert by_sku["SKU2"] == "healthy"  # 50 天
    # product_sku 映射到 sku
    assert {r.sku for r in rows} == {"SKU1", "SKU2"}
    # product_title 映射到 product_name
    by_name = {r.sku: r.product_name for r in rows}
    assert by_name["SKU1"] == "商品1"
    # iba_quantity 映射到 quantity
    by_qty = {r.sku: r.quantity for r in rows}
    assert by_qty["SKU1"] == 10
    assert by_qty["SKU2"] == 5
