"""离线测试：用 httpx MockTransport 拦截 4 个接口，验证 header 鉴权 + POST + JSON body。

不依赖外网与真实凭据，运行稳定。验证：
1. 每次请求都带 app-token / app-key header
2. 统一走 POST + JSON body
3. 路径为 /public_open/...
4. 业务 code != 0 抛 GoodCangAPIError
5. 4xx 立即抛业务异常，不重试
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.connectors.goodcang import (
    BillingExportRequest,
    BillingListRequest,
    GoodCangClient,
    GoodCangEndpoints,
    InventoryAgeListRequest,
    ProductInventoryRequest,
)


def _ok(payload):
    """构造谷仓 V2 风格成功响应。"""
    return httpx.Response(200, json={"code": 0, "message": "ok", "data": payload})


def _make_mock_client() -> tuple[GoodCangClient, list[dict]]:
    """构造把 httpx 拦截为 MockTransport 的 GoodCangClient。"""
    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # POST 形态：body 是 JSON；header 含 app-token/app-key
        body: dict = {}
        if request.content:
            try:
                body = json.loads(request.content.decode("utf-8"))
            except Exception:  # noqa: BLE001
                body = {}
        captured.append({
            "url": str(request.url),
            "method": request.method,
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": body,
        })

        url = str(request.url)
        if "/public_open/finance/billing_list" in url:
            return _ok({
                "list": [{
                    "bill_number": "B20260801",
                    "account_code": "ACC1",
                    "bill_from_time": "2026-08-01 00:00:00",
                    "bill_to_time": "2026-08-31 23:59:59",
                    "all_total": {"balance": "1234.56", "currency_code": "EUR"},
                    "warehouse_code": "DE1",
                }],
                "total": 1,
            })
        if "/public_open/finance/billing_export" in url:
            return _ok("BASE64FILECONTENT==")
        if "/public_open/inventory/inventory_age_list" in url:
            return _ok({
                "list": [{
                    "warehouse_code": "DE1",
                    "product_sku": "SKU1",
                    "lba_quantity": 10,
                    "lba_fifo_time": "2025-08-01",
                    "lba_warning_age": 30,
                    "product_title": "商品1",
                    "product_title_en": "Product 1",
                    "warehouse_desc": "德国仓",
                    "warehouse_age": 400,
                    "expiration_date": "2027-01-01",
                }],
                "total": 1,
            })
        if "/public_open/inventory/get_product_inventory" in url:
            return _ok({
                "list": [{
                    "warehouse_code": "DE1",
                    "warehouse_desc": "德国仓",
                    "product_sku": "SKU1",
                    "product_title": "商品1",
                    "total_onway": 20,
                    "transfer_onway": 5,
                    "onway": 12,
                    "pending": 1,
                    "sellable": 100,
                    "unsellable": 5,
                    "reserved": 3,
                    "pi_unavailable_reserved": 0,
                    "shipped": 7,
                    "pi_unavailable_shipped": 0,
                    "pi_freeze": 0,
                    "product_freeze_status": "1",
                    "product_freeze_status_text": "正常",
                    "pi_warning_qty": 10,
                    "pi_no_stock": 0,
                    "stocking": 0,
                }],
                "count": 1,
                "total": 1,
            })
        return httpx.Response(404, json={"code": 404, "message": "unknown path"})

    transport = httpx.MockTransport(handler)
    client = GoodCangClient()
    # 直接设内部 _client 跳过 async with（测试用）
    client._client = httpx.AsyncClient(transport=transport, timeout=client.timeout)  # noqa: SLF001
    return client, captured


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# 1. Header 鉴权验证
# ---------------------------------------------------------------------------
async def test_app_token_and_app_key_in_headers():
    """每次请求都自动注入 app-token + app-key header。"""
    client, captured = _make_mock_client()
    try:
        ep = GoodCangEndpoints(client)
        await ep.billing_list(BillingListRequest(account_code="ACC1"))
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert captured[0]["headers"].get("app-token") == client.app_token
    assert captured[0]["headers"].get("app-key") == client.app_key
    assert captured[0]["headers"].get("content-type") == "application/json"


# ---------------------------------------------------------------------------
# 2. billing_list
# ---------------------------------------------------------------------------
async def test_billing_list_uses_post_and_correct_path():
    client, captured = _make_mock_client()
    try:
        ep = GoodCangEndpoints(client)
        resp = await ep.billing_list(BillingListRequest(
            account_code="ACC1",
            begin_bill_to_time="2026-08-01 00:00:00",
            end_bill_to_time="2026-08-31 23:59:59",
        ))
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert captured[0]["method"] == "POST"
    assert "/public_open/finance/billing_list" in captured[0]["url"]
    assert captured[0]["body"]["account_code"] == "ACC1"
    # 响应 V2 结构：data.list[]
    assert resp["data"]["list"][0]["bill_number"] == "B20260801"


# ---------------------------------------------------------------------------
# 3. billing_export (base64 file)
# ---------------------------------------------------------------------------
async def test_billing_export_returns_base64_string():
    client, captured = _make_mock_client()
    try:
        ep = GoodCangEndpoints(client)
        resp = await ep.billing_export(BillingExportRequest(
            bill_number_list=["B20260801"]
        ))
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert captured[0]["method"] == "POST"
    assert "/public_open/finance/billing_export" in captured[0]["url"]
    assert resp["data"] == "BASE64FILECONTENT=="


# ---------------------------------------------------------------------------
# 4. inventory_age_list
# ---------------------------------------------------------------------------
async def test_inventory_age_list_uses_post_and_correct_path():
    client, captured = _make_mock_client()
    try:
        ep = GoodCangEndpoints(client)
        resp = await ep.inventory_age_list(InventoryAgeListRequest(
            warehouse_code="DE1"
        ))
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert captured[0]["method"] == "POST"
    assert "/public_open/inventory/inventory_age_list" in captured[0]["url"]
    assert captured[0]["body"]["warehouse_code"] == "DE1"
    assert resp["data"]["list"][0]["warehouse_age"] == 400
    assert resp["data"]["list"][0]["product_sku"] == "SKU1"


# ---------------------------------------------------------------------------
# 5. get_product_inventory
# ---------------------------------------------------------------------------
async def test_product_inventory_uses_post_and_pageSize_camel():
    client, captured = _make_mock_client()
    try:
        ep = GoodCangEndpoints(client)
        resp = await ep.product_inventory(ProductInventoryRequest(
            warehouse_code="DE1"
        ))
    finally:
        await client._client.aclose()  # noqa: SLF001

    assert captured[0]["method"] == "POST"
    assert "/public_open/inventory/get_product_inventory" in captured[0]["url"]
    # pageSize 是驼峰命名（不是 page_size）
    assert "pageSize" in captured[0]["body"]
    assert resp["data"]["list"][0]["sellable"] == 100
    assert resp["data"]["list"][0]["onway"] == 12
    assert resp["data"]["list"][0]["pi_freeze"] == 0


# ---------------------------------------------------------------------------
# 6. 业务错误响应
# ---------------------------------------------------------------------------
async def test_biz_error_raises():
    """业务返回 code != 0 应当抛 GoodCangAPIError。"""
    def handler(request):
        return httpx.Response(200, json={"code": 999, "message": "biz failed", "data": None})

    client = GoodCangClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=client.timeout)  # noqa: SLF001
    try:
        from app.connectors.goodcang.client import GoodCangAPIError
        ep = GoodCangEndpoints(client)
        with pytest.raises(GoodCangAPIError):
            await ep.billing_list(BillingListRequest(account_code="ACC1"))
    finally:
        await client._client.aclose()  # noqa: SLF001


# ---------------------------------------------------------------------------
# 7. 4xx HTTP 错误
# ---------------------------------------------------------------------------
async def test_4xx_raises_biz_error():
    """401/403/404 等 4xx 不重试，直接抛业务异常。"""
    def handler(request):
        return httpx.Response(401, text="Unauthorized")

    client = GoodCangClient(max_retry=1)  # 减少重试时间
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=client.timeout)  # noqa: SLF001
    try:
        from app.connectors.goodcang.client import GoodCangAPIError
        ep = GoodCangEndpoints(client)
        with pytest.raises(GoodCangAPIError) as exc:
            await ep.billing_list(BillingListRequest(account_code="BAD"))
        assert "401" in str(exc.value)
    finally:
        await client._client.aclose()  # noqa: SLF001


# ---------------------------------------------------------------------------
# 8. V1 鉴权方式（MD5 签名）已彻底移除
# ---------------------------------------------------------------------------
async def test_no_signature_param_in_request():
    """鉴权已改为 HTTP Header，请求体里不应该有 sign / app_token / timestamp 字段。"""
    client, captured = _make_mock_client()
    try:
        ep = GoodCangEndpoints(client)
        await ep.billing_list(BillingListRequest(account_code="ACC1"))
    finally:
        await client._client.aclose()  # noqa: SLF001

    body = captured[0]["body"]
    assert "sign" not in body
    assert "app_token" not in body
    assert "timestamp" not in body
