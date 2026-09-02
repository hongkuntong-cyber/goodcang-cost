"""分析引擎测试：成本汇总/结构/健康/风险SKU/报告。"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import (
    DimWarehouse, MartMonthlyCostSummary, MartMonthlyReport, MartRiskSku,
    StgBill, StgBillFeeItem, StgInventoryAge,
)
from app.services.analysis_engine import AnalysisEngine


@pytest.fixture()
def seeded(session):
    session.add(DimWarehouse(warehouse_code="DE1", warehouse_name="德国一仓",
                             country_code="DE", currency_code="EUR"))
    # 8月费用明细
    session.add(StgBillFeeItem(bill_number="B1", fee_name="仓储费", fee_category="storage",
                               amount=Decimal("1000"), currency_code="EUR", bill_month="2026-08"))
    session.add(StgBillFeeItem(bill_number="B1", fee_name="运输费", fee_category="transport",
                               amount=Decimal("500"), currency_code="EUR", bill_month="2026-08"))
    session.add(StgBillFeeItem(bill_number="B1", fee_name="出库操作费", fee_category="outbound",
                               amount=Decimal("300"), currency_code="EUR", bill_month="2026-08"))
    # 7月费用（用于环比）
    session.add(StgBillFeeItem(bill_number="B0", fee_name="仓储费", fee_category="storage",
                               amount=Decimal("800"), currency_code="EUR", bill_month="2026-07"))
    # 库存年龄
    session.add_all([
        StgInventoryAge(snapshot_date=date(2026, 9, 1), sku="SKU1", product_name="商品1",
                        quantity=100, warehouse_age=400, age_bucket="critical", warehouse_code="DE1"),
        StgInventoryAge(snapshot_date=date(2026, 9, 1), sku="SKU2", product_name="商品2",
                        quantity=50, warehouse_age=200, age_bucket="stale", warehouse_code="DE1"),
        StgInventoryAge(snapshot_date=date(2026, 9, 1), sku="SKU3", product_name="商品3",
                        quantity=30, warehouse_age=100, age_bucket="watch", warehouse_code="DE1"),
    ])
    session.commit()
    return session


def test_monthly_cost_and_mom(seeded):
    eng = AnalysisEngine(seeded)
    # 先算 7 月（作为环比基期）
    eng.compute_monthly_cost("2026-07", "DE1")
    row = eng.compute_monthly_cost("2026-08", "DE1")

    assert str(row.total_cost) == "1800.0000"  # 1000+500+300
    assert str(row.storage_fee) == "1000.0000"
    assert row.mom_change_pct is not None
    # 7月=800，8月=1800 → 环比 +125%
    assert float(row.mom_change_pct) == pytest.approx(125.0, abs=0.01)


def test_cost_structure(seeded):
    eng = AnalysisEngine(seeded)
    eng.compute_monthly_cost("2026-08", "DE1")
    s = eng.cost_structure("2026-08", "DE1")
    assert s["total"] == 1800.0
    cats = {i["category"]: i["amount"] for i in s["items"]}
    assert cats["storage"] == 1000.0
    assert cats["transport"] == 500.0
    assert cats["outbound"] == 300.0
    assert cats["inbound"] == 0.0


def test_inventory_health(seeded):
    eng = AnalysisEngine(seeded)
    h = eng.inventory_health(date(2026, 9, 1), "DE1")
    buckets = {b["bucket"]: b for b in h["buckets"]}
    assert buckets["critical"]["quantity"] == 100
    assert buckets["stale"]["quantity"] == 50
    assert buckets["watch"]["quantity"] == 30
    assert buckets["healthy"]["quantity"] == 0
    assert h["total_quantity"] == 180


def test_risk_sku_top(seeded):
    eng = AnalysisEngine(seeded)
    top = eng.risk_sku_top(date(2026, 9, 1), "DE1", top=20)
    # 库龄降序：SKU1(400) > SKU2(200) > SKU3(100)
    assert [r["sku"] for r in top] == ["SKU1", "SKU2", "SKU3"]
    assert top[0]["age_bucket"] == "critical"
    # 已物化
    persisted = seeded.scalars(select(MartRiskSku)).all()
    assert len(persisted) == 3
    assert persisted[0].risk_rank == 1


def test_generate_report(seeded):
    eng = AnalysisEngine(seeded)
    eng.compute_monthly_cost("2026-08", "DE1")
    report = eng.generate_report("2026-08", "DE1")
    assert report.title.startswith("德国海外仓成本健康报告")
    assert report.status == "published"
    assert report.content_md is not None and "成本变化" in report.content_md
    # 报告里有成本/库存风险/建议
    assert report.cost_change["total"] == 1800.0
    assert len(report.recommendations) >= 1