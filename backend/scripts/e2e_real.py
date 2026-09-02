"""端到端真实数据验证（修正版）：分析 ACG1505603 + ACG1505604 两个主体。

流程：
1. 建 SQLite 文件库
2. 分页拉全账单（2 个 account_code）+ 库存库龄（分页）+ 库存状态
3. 落库（复用 SyncService 的 UPSERT 逻辑，但自己控制分页）
4. 按主体分组聚合费用 + 导出前端 JSON（两个主体分开展示）

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
# 用户指定的两个签约主体（含名称映射）
ACCOUNTS = ["ACG1505603", "ACG1505604"]
ACCOUNT_NAMES = {
    "ACG1505603": "NAIBA INTERNATIONAL GMBH",
    "ACG1505604": "HONGKONG LITTLE MAGIC INTERNATIONAL TRADING LIMITED",
}


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
        # bill_number -> (account_code, bill_month) 映射（从已落库账单反查）
        bn_meta = {
            b.bill_number: (b.account_code, b.bill_month)
            for b in db.scalars(select(StgBill)).all()
        }
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
            account_code, bill_month = bn_meta.get(bn, ("", ""))
            # 幂等：先删除该账单旧费用明细，避免重跑累积
            from sqlalchemy import delete
            db.execute(delete(StgBillFeeItem).where(StgBillFeeItem.bill_number == bn))
            for fr in fee_rows:
                # 归类时结合 fee_type + fee_name 一起匹配（英文格式运费在 Fee Type，明细在 Fee Details）
                cat = classify_fee(f"{fr.get('fee_type', '')} {fr['fee_name']}")
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

    # ---- 分析：按主体分组聚合费用 ----
    print("\n=== 按主体分组分析 ===")

    # 账单主表：bill_number -> account_code / bill_month / EUR 总额
    bill_rows = db.scalars(select(StgBill)).all()
    # 费用明细：bill_number -> 五大类金额
    fee_rows = db.scalars(select(StgBillFeeItem)).all()

    from collections import defaultdict
    from app.services.analysis_engine import AnalysisEngine
    CATS = ("storage", "inbound", "outbound", "transport", "other")
    CAT_LABELS = {
        "storage": "仓储费", "inbound": "入库费",
        "outbound": "出库操作费", "transport": "运输费", "other": "其他费用",
    }

    # 主体 -> 月 -> 五大类金额
    ac_month_fees: dict[str, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    # bill_number -> account_code
    bn_ac = {b.bill_number: b.account_code for b in bill_rows}
    # bill_number -> bill_month
    bn_month = {b.bill_number: b.bill_month for b in bill_rows}
    # bill_number -> EUR 总额（用于兜底/对账）
    bn_total = {b.bill_number: float(b.all_total or 0) for b in bill_rows}

    for fr in fee_rows:
        ac = bn_ac.get(fr.bill_number)
        if ac not in ACCOUNTS:
            continue
        m = fr.bill_month
        ac_month_fees[ac][m][fr.fee_category] += float(fr.amount or 0)

    # 为每个主体构建独立的 summary / trend / structure
    def build_account_block(ac):
        months = sorted(ac_month_fees[ac].keys())
        # 每个月的总成本 + 五大类
        monthly = []
        for m in months:
            fees = ac_month_fees[ac][m]
            total = sum(fees.values())
            # 如果费用明细全 0，用账单主表总额兜底
            if total == 0:
                # 找该主体该月的账单
                for b in bill_rows:
                    if b.account_code == ac and b.bill_month == m:
                        total = float(b.all_total or 0)
                        break
            monthly.append({"month": m, "total": total, "fees": dict(fees)})

        # 环比（与上一有账单的月份比，而非自然上月）
        trend = []
        prev_total = None
        for item in monthly:
            mom = None
            if prev_total is not None and prev_total > 0:
                mom = round((item["total"] - prev_total) / prev_total * 100, 2)
            trend.append({
                "month": item["month"],
                "total": round(item["total"], 2),
                "storage": round(item["fees"].get("storage", 0), 2),
                "inbound": round(item["fees"].get("inbound", 0), 2),
                "outbound": round(item["fees"].get("outbound", 0), 2),
                "transport": round(item["fees"].get("transport", 0), 2),
                "other": round(item["fees"].get("other", 0), 2),
                "mom_pct": mom,
            })
            prev_total = item["total"]

        # 最新一个月的 summary
        latest = monthly[-1] if monthly else None
        if latest:
            structure = [
                {"category": c, "label": CAT_LABELS[c],
                 "amount": round(latest["fees"].get(c, 0), 2)}
                for c in CATS
            ]
            summary = {
                "month": latest["month"],
                "total": round(latest["total"], 2),
                "mom_pct": trend[-1]["mom_pct"] if trend else None,
                "structure": structure,
            }
        else:
            summary = {"month": None, "total": 0, "mom_pct": None,
                       "structure": [{"category": c, "label": CAT_LABELS[c], "amount": 0} for c in CATS]}

        return {
            "account_code": ac,
            "account_name": ACCOUNT_NAMES.get(ac, ac),
            "summary": summary,
            "trend": trend,
            "bill_count": sum(1 for b in bill_rows if b.account_code == ac),
        }

    accounts_data = [build_account_block(ac) for ac in ACCOUNTS]

    # 库存健康与风险 SKU 是仓库级（不区分主体），仍用分析引擎
    eng = AnalysisEngine(db)
    health = eng.inventory_health(date(2026, 9, 1), WH)
    risk = eng.risk_sku_top(date(2026, 9, 1), WH, top=20)

    # 打印结果
    for ad in accounts_data:
        print(f"\n[{ad['account_code']}] {ad['account_name']}  账单 {ad['bill_count']} 条")
        print(f"  最新月 {ad['summary']['month']} 总成本: EUR {ad['summary']['total']}  环比: {ad['summary']['mom_pct']}%")
        for s in ad['summary']['structure']:
            print(f"    {s['label']}: EUR {s['amount']}")
        print(f"  趋势 {len(ad['trend'])} 个月")

    out = {
        "accounts": accounts_data,
        "health": health,
        "risk": risk,
    }

    out_path = os.path.abspath(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "preview", "real-data.json",
    ))
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("\n=== 汇总 ===")
    print(f"  账单 {n_bills} 条 / 费用明细 {n_fee} 条 / 库龄 {n_age} 条 / 库存状态 {n_status} 条")
    for ad in accounts_data:
        print(f"  {ad['account_code']}: 最新月 {ad['summary']['month']} 总成本 EUR {ad['summary']['total']}")
    print(f"  风险 SKU: {len(risk)} 条")
    print(f"  前端数据已导出: {out_path}")


if __name__ == "__main__":
    asyncio.run(run())
