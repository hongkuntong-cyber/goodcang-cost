"""端到端真实数据验证（修正版）：只关注 ACG1505601 + ACG1505604 两个主体。

流程：
1. 建 SQLite 文件库
2. 分页拉全账单（2 个 account_code）+ 库存库龄（分页）+ 库存状态
3. 落库（复用 SyncService 的 UPSERT 逻辑，但自己控制分页）
4. 分析引擎聚合 + 导出前端 JSON

用法（backend 目录下）：
    python scripts/e2e_real.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import date
from decimal import Decimal

os.environ["DATABASE_URL"] = "sqlite:///./e2e_real.db"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from sqlalchemy import create_engine, select  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.core.database import Base  # noqa: E402
from app.connectors.goodcang import GoodCangClient, GoodCangEndpoints  # noqa: E402
from app.connectors.goodcang.billing_parser import parse_billing_xlsx, classify_fee  # noqa: E402
from app.models import DimWarehouse, FeeCategoryMap, StgBill, StgBillFeeItem  # noqa: E402
from app.services.sync_service import SyncService  # noqa: E402
from app.services.analysis_engine import AnalysisEngine  # noqa: E402

WH = "DE"
ACCOUNTS = ["ACG1505601", "ACG1505604"]  # 用户指定的两个主体


def init_engine():
    engine = create_engine(os.environ["DATABASE_URL"], future=True)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False, future=True)


def seed(db):
    if not db.scalar(select(DimWarehouse).where(DimWarehouse.warehouse_code == WH)):
        db.add(DimWarehouse(
            warehouse_code=WH, warehouse_name="德国区", country_code="DE", currency_code="EUR"
        ))
    for kw, cat, pri in [
        ("仓储", "storage", 1), ("storage", "storage", 1),
        ("入库", "inbound", 1), ("inbound", "inbound", 1),
        ("出库", "outbound", 1), ("操作", "outbound", 1),
        ("运输", "transport", 1), ("transport", "transport", 1),
        ("派送", "transport", 1),
    ]:
        db.add(FeeCategoryMap(match_keyword=kw, fee_category=cat, priority=pri))
    db.commit()


async def run():
    engine, Sess = init_engine()
    db = Sess()
    seed(db)

    async with GoodCangClient() as client:
        ep = GoodCangEndpoints(client)
        svc = SyncService(db, client, ep)

        # ---- 1. 账单：按两个 account_code 分别拉（每页200足够覆盖）----
        n_bills = 0
        all_bill_numbers: list[str] = []
        for ac in ACCOUNTS:
            print(f"[账单] 拉取 {ac} ...")
            page = 1
            while True:
                resp = await client.call_raw_post(
                    "/public_open/finance/billing_list",
                    {"account_code": ac, "page": page, "page_size": 200},
                )
                rows = svc._extract_list_rows(resp)
                if not rows:
                    break
                for r in rows:
                    n_bills += svc._upsert_bill(r)
                    bn = r.get("bill_number")
                    if bn:
                        all_bill_numbers.append(bn)
                total = (resp.get("data") or {}).get("total", 0) if isinstance(resp.get("data"), dict) else 0
                if len(rows) < 200 or page * 200 >= total:
                    break
                page += 1
        db.commit()
        print(f"  账单落库 {n_bills} 条")

        # ---- 1.5 费用明细：逐个账单拉 xlsx 解析（Step 8）----
        print(f"[费用明细] 解析 {len(all_bill_numbers)} 个账单的 xlsx ...")
        # bill_number -> bill_month 映射（从已落库账单反查）
        bn_month = {b.bill_number: b.bill_month for b in db.scalars(select(StgBill)).all()}
        n_fee = 0
        for bn in all_bill_numbers:
            resp = await client.call_raw_post(
                "/public_open/finance/billing_export",
                {"bill_number_list": [bn]},
            )
            data_b64 = resp.get("data") if isinstance(resp, dict) else None
            if not data_b64:
                continue
            try:
                fee_rows = parse_billing_xlsx(data_b64)
            except Exception as e:  # noqa: BLE001
                print(f"    [跳过] {bn} xlsx 解析失败: {e}")
                continue
            bill_month = bn_month.get(bn, "")
            # 幂等：先删除该账单旧费用明细，避免重跑累积
            from sqlalchemy import delete
            db.execute(delete(StgBillFeeItem).where(StgBillFeeItem.bill_number == bn))
            for fr in fee_rows:
                cat = classify_fee(fr["fee_name"])
                # raw_json 里的 Decimal 无法被 JSON 序列化，单独转成 float 再存
                raw_json = {
                    k: (float(v) if isinstance(v, Decimal) else v)
                    for k, v in fr.items()
                }
                db.add(StgBillFeeItem(
                    bill_number=bn,
                    fee_name=fr["fee_name"],
                    fee_category=cat,
                    amount=fr["amount"],
                    currency_code=fr["currency"],
                    related_sku=None,
                    bill_month=bill_month,
                    raw_json=raw_json,
                ))
                n_fee += 1
        db.commit()
        print(f"  费用明细落库 {n_fee} 条")

        # ---- 2. 库存库龄：分页拉全 ----
        print("[库存库龄] 拉取 inventory_age_list (DE, 分页) ...")
        n_age = 0
        page = 1
        while True:
            resp = await client.call_raw_post(
                "/public_open/inventory/inventory_age_list",
                {"warehouse_code": WH, "page": page, "page_size": 200},
            )
            rows = svc._extract_list_rows(resp)
            if not rows:
                break
            for r in rows:
                sku = str(r.get("product_sku") or "")
                if not sku:
                    continue
                age = svc._to_int(r.get("warehouse_age"))
                from app.models import StgInventoryAge
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                values = {
                    "snapshot_date": date(2026, 9, 1), "sku": sku,
                    "product_name": r.get("product_title") or r.get("product_title_en"),
                    "quantity": svc._to_int(r.get("iba_quantity")),
                    "warehouse_age": age,
                    "inbound_time": svc._to_dt(r.get("iba_fifo_time")),
                    "age_bucket": __import__("app.services.sync_service", fromlist=["bucket_age"]).bucket_age(age),
                    "warehouse_code": r.get("warehouse_code") or WH,
                    "raw_json": r,
                }
                stmt = sqlite_insert(StgInventoryAge).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["snapshot_date", "sku", "warehouse_code"],
                    set_={k: v for k, v in values.items()
                          if k not in ("snapshot_date", "sku", "warehouse_code")},
                )
                db.execute(stmt)
                n_age += 1
            data = resp.get("data") or {}
            total = data.get("total", 0) if isinstance(data, dict) else 0
            if len(rows) < 200 or (total and n_age >= total):
                break
            page += 1
        db.commit()
        print(f"  库龄落库 {n_age} 条")

        # ---- 3. 库存状态：单页拉全（共192条）----
        print("[库存状态] 拉取 get_product_inventory (DE) ...")
        n_status = 0
        page = 1
        while True:
            resp = await client.call_raw_post(
                "/public_open/inventory/get_product_inventory",
                {"warehouse_code": WH, "page": page, "pageSize": 200},
            )
            rows = svc._extract_list_rows(resp)
            if not rows:
                break
            from app.models import StgInventoryStatus
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            for r in rows:
                sku = str(r.get("product_sku") or "")
                if not sku:
                    continue
                values = {
                    "snapshot_date": date(2026, 9, 1), "sku": sku,
                    "sellable": svc._to_int(r.get("sellable")),
                    "unsellable": svc._to_int(r.get("unsellable")),
                    "reserved": svc._to_int(r.get("reserved")),
                    "onway": svc._to_int(r.get("onway")),
                    "warehouse_code": r.get("warehouse_code") or WH,
                    "raw_json": r,
                }
                stmt = sqlite_insert(StgInventoryStatus).values(**values)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["snapshot_date", "sku", "warehouse_code"],
                    set_={k: v for k, v in values.items()
                          if k not in ("snapshot_date", "sku", "warehouse_code")},
                )
                db.execute(stmt)
                n_status += 1
            next_page = resp.get("nextPage") if isinstance(resp, dict) else False
            if not next_page:
                break
            page += 1
        db.commit()
        print(f"  状态落库 {n_status} 条")

    # ---- 分析 ----
    print("\n=== 运行分析引擎 ===")
    eng = AnalysisEngine(db)
    months = sorted(db.scalars(select(StgBill.bill_month).distinct()).all())
    print(f"账单月份分布: {months}")

    # 按月循环计算成本（这样趋势/环比才有完整数据）
    for m in months:
        eng.compute_monthly_cost(m, WH)

    target_month = "2026-08"
    cost = eng.compute_monthly_cost(target_month, WH)
    print(f"  2026-08 总成本(EUR): {cost.total_cost}  环比: {cost.mom_change_pct}%")

    structure = eng.cost_structure(target_month, WH)
    health = eng.inventory_health(date(2026, 9, 1), WH)
    risk = eng.risk_sku_top(date(2026, 9, 1), WH, top=20)
    report = eng.generate_report(target_month, WH)

    out = {
        "summary": {
            "month": target_month,
            "total": float(cost.total_cost),
            "mom_pct": float(cost.mom_change_pct) if cost.mom_change_pct is not None else None,
            "structure": [
                {"category": c, "label": eng._cat_label(c),
                 "amount": float(getattr(cost, f"{c}_fee"))}
                for c in ("storage", "inbound", "outbound", "transport", "other")
            ],
        },
        "trend": eng.cost_trend(WH, 12),
        "health": health,
        "risk": risk,
        "report": {"report_month": target_month, "title": report.title, "content_md": report.content_md},
    }

    out_path = os.path.abspath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "preview", "real-data.json",
    ))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== 汇总 ===")
    print(f"  账单 {n_bills} 条 / 库龄 {n_age} 条 / 库存状态 {n_status} 条")
    print(f"  2026-08 德国仓总成本: EUR {cost.total_cost}")
    print(f"  趋势点数: {len(out['trend'])} 个月")
    print(f"  风险 SKU: {len(risk)} 条")
    print(f"  前端数据已导出: {out_path}")


if __name__ == "__main__":
    asyncio.run(run())
