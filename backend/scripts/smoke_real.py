"""谷仓 GoodCang Open API 真实连通性冒烟测试。

直接调用 billing_list 接口，验证：
1. HTTP Header 鉴权（app-token / app-key）是否被接受
2. base_url（oms.goodcang.net）与路径前缀是否正确
3. 返回的字段结构是否符合校准文档

用法：
    python smoke_real.py
"""
import json
import sys
import asyncio

import httpx

BASE_URL = "https://oms.goodcang.net"
APP_TOKEN = "9794777082acd40d71ac0c1857e58141"
APP_KEY = "7af09323165d1aec1c813f75befa0ea5"

PATH_BILLING_LIST = "/public_open/finance/billing_list"


async def main():
    headers = {
        "app-token": APP_TOKEN,
        "app-key": APP_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # 最小请求体：只传必填的 account_code 留空，先看鉴权是否通过
    # 若 account_code 必填，谷仓会返回业务 code 提示，我们据此修正
    body = {
        "page": 1,
        "page_size": 5,
    }

    url = BASE_URL + PATH_BILLING_LIST
    print("=" * 70)
    print(f"URL   : {url}")
    print(f"Method: POST")
    print(f"Headers(app-token/app-key): 已携带（脱敏）")
    print(f"Body  : {json.dumps(body, ensure_ascii=False)}")
    print("=" * 70)

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(url, json=body, headers=headers)
        except httpx.HTTPError as e:
            print(f"\n[FAIL] 网络错误：{e!r}")
            sys.exit(2)

    print(f"\nHTTP Status : {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type')}")
    print("-" * 70)
    print("响应体（前 2000 字符）：")
    text = resp.text
    print(text[:2000])
    print("-" * 70)

    # 尝试解析 JSON
    try:
        data = resp.json()
    except Exception:
        print("\n[WARN] 响应不是 JSON")
        sys.exit(3)

    code = data.get("code")
    message = data.get("message")
    print(f"\n业务 code   : {code}")
    print(f"业务 message: {message}")

    if code in (0, "0"):
        d = data.get("data") or {}
        lst = d.get("list") or []
        total = d.get("total")
        print(f"[OK] 调用成功，total={total}，本页 {len(lst)} 条")
        if lst:
            print("\n首条记录字段：")
            print(json.dumps(lst[0], ensure_ascii=False, indent=2)[:2000])
    else:
        print(f"\n[FAIL] 业务失败：code={code}, message={message}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
