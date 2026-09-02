"""谷仓 GoodCang Open API 客户端：HTTP Header 鉴权 + 统一 POST 调用 + 重试。

设计要点
--------
1. 鉴权方式（2026-09-01 校准自官方文档）：
   - 谷仓采用 **HTTP Header 鉴权**，每次请求需携带两个 header：
     * ``app-token``  : AppToken（账号维度）
     * ``app-key``    : AppKey（账号维度）
   - 鉴权信息全部来自 .env（GOODCANG_APP_TOKEN / GOODCANG_APP_KEY），**绝不**硬编码。

2. HTTP 方法：所有业务接口均为 **POST**，请求体为 **JSON**（Content-Type: application/json）。
   不再使用 query 参数 / GET 方式（之前错误的默认）。

3. 响应统一为 V2 JSON 风格：
   ``{"code": 0, "message": "ok", "data": ...}``
   - ``code == 0`` 表示成功
   - ``code != 0`` 抛出 :class:`GoodCangAPIError`

4. HTTP 状态码语义：
   - 200 成功
   - 401 TOKEN/KEY 错误（客户端配置问题，不重试）
   - 403 触发限流（不重试，由调用方退避）
   - 404 接口不存在
   - 5xx  临时错误，触发 tenacity 重试最多 settings.goodcang_max_retry 次
"""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class GoodCangAPIError(RuntimeError):
    """谷仓业务异常（HTTP 4xx / 业务 code != 0 / 鉴权失败）。"""


class GoodCangClient:
    """谷仓 Open API 客户端（async）。

    鉴权使用 HTTP Header（app-token / app-key）；请求方法统一为 POST + JSON。
    """

    def __init__(
        self,
        *,
        timeout: int | None = None,
        max_retry: int | None = None,
    ) -> None:
        s = get_settings()
        self.base_url = s.goodcang_base_url.rstrip("/")
        self.app_token = s.goodcang_app_token
        self.app_key = s.goodcang_app_key
        self.timeout = timeout or s.goodcang_timeout
        self.max_retry = max_retry or s.goodcang_max_retry

        self._client: httpx.AsyncClient | None = None

    # ---- 生命周期 ----
    async def __aenter__(self) -> "GoodCangClient":
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ---- 内部：构造鉴权 header ----
    def _auth_headers(self) -> dict[str, str]:
        return {
            "app-token": self.app_token,
            "app-key": self.app_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ---- 内部：带重试的 POST 请求 ----
    async def _post(self, path: str, biz_body: Mapping[str, Any]) -> dict[str, Any]:
        assert self._client is not None, "use 'async with GoodCangClient()'"
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()

        async def _do() -> httpx.Response:
            resp = await self._client.post(url, json=dict(biz_body), headers=headers)
            return resp

        return await self._with_retry(url, _do)

    async def _with_retry(
        self,
        url: str,
        do: Callable[[], Awaitable[httpx.Response]],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_retry),
                wait=wait_exponential(multiplier=1, min=1, max=10),
                retry=retry_if_exception_type((httpx.HTTPError,)),
                reraise=True,
            ):
                with attempt:
                    try:
                        resp = await do()
                    except httpx.HTTPStatusError as e:
                        # 4xx 直接抛业务异常（不重试：401/403/404 都不是临时错误）
                        if 400 <= e.response.status_code < 500:
                            raise GoodCangAPIError(
                                f"client error {e.response.status_code}: "
                                f"{e.response.text[:300]}"
                            ) from e
                        # 5xx 触发 tenacity 重试
                        last_error = e
                        raise
        except GoodCangAPIError:
            # 直接重抛，不包装
            raise
        except httpx.HTTPError as e:
            logger.error(
                "GoodCang request failed after %s retries: %s %s",
                self.max_retry, url, e,
            )
            raise GoodCangAPIError(
                f"network error after {self.max_retry} retries: {e}"
            ) from (last_error or e)

        # 业务响应校验
        if resp.status_code != 200:
            raise GoodCangAPIError(
                f"http {resp.status_code}: {resp.text[:300]}"
            )

        try:
            body = resp.json()
        except Exception as e:  # noqa: BLE001
            raise GoodCangAPIError(
                f"non-json response: {resp.text[:300]}"
            ) from e

        # V2 JSON 风格：code=0 表示成功
        code = body.get("code")
        if code not in (0, "0"):
            raise GoodCangAPIError(
                f"GoodCang biz error code={code} message={body.get('message')}"
            )
        return body

    # ---- 公开：业务调用入口 ----
    async def call(
        self,
        path: str,
        biz_body: Mapping[str, Any],
        *,
        response_model: type[T] | None = None,
    ) -> dict[str, Any] | T:
        """统一的业务调用。

        - path          : 接口路径（相对于 base_url，例如 ``/public_open/finance/billing_list``）
        - biz_body      : 业务参数 JSON（不含鉴权信息，由 client 注入 header）
        - response_model: 可选 Pydantic 模型；若提供，则把 ``data`` 字段解析为该模型
        """
        body = await self._post(path, biz_body)

        if response_model is None:
            return body
        payload = body.get("data", body)
        try:
            return response_model.model_validate(payload)
        except Exception:  # noqa: BLE001
            logger.warning(
                "response validation failed for %s; returning raw data dict", path
            )
            return payload if isinstance(payload, dict) else body

    async def call_raw_post(self, path: str, biz_body: Mapping[str, Any]) -> dict[str, Any]:
        """调用接口并直接返回完整 JSON（包含 code/message/data）。

        用于不想做 model 解析的场景（如 binary base64 响应）。
        """
        return await self._post(path, biz_body)
