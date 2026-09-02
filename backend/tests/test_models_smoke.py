"""冒烟测试：验证 10 张表能在内存库里 create_all，并能基本 insert。
更多业务测试在 Step 5 / Step 7 补齐。
"""
import pytest
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import (
    DimWarehouse, FeeCategoryMap, MartMonthlyCostSummary, MartMonthlyReport,
    MartRiskSku, StgBill, StgBillFeeItem, StgInventoryAge, StgInventoryStatus, SyncLog,
)


def test_warehouse_table_create(session):
    wh = DimWarehouse(
        warehouse_code="DE1", warehouse_name="德国一仓",
        country_code="DE", currency_code="EUR", is_active=True,
    )
    session.add(wh); session.commit()
    rows = session.scalars(select(DimWarehouse)).all()
    assert len(rows) == 1 and rows[0].warehouse_code == "DE1"


def test_bill_and_fee_item_cascade(session):
    # 仓库 + 账单 + 费用明细
    session.add(DimWarehouse(warehouse_code="DE1", warehouse_name="德国一仓",
                             country_code="DE", currency_code="EUR"))
    bill = StgBill(
        bill_number="B20260801", bill_from_time=datetime(2026, 8, 1, tzinfo=timezone.utc),
        bill_to_time=datetime(2026, 8, 31, tzinfo=timezone.utc),
        bill_month="2026-08", all_total=1234.56, currency_code="EUR", warehouse_code="DE1",
    )
    session.add(bill); session.flush()
    session.add(StgBillFeeItem(
        bill_number=bill.bill_number, fee_name="仓储", fee_category="storage",
        amount=800, currency_code="EUR", bill_month="2026-08",
    ))
    session.commit()

    assert session.scalars(select(StgBill)).one().bill_number == "B20260801"
    assert session.scalars(select(StgBillFeeItem)).one().fee_category == "storage"


def test_inventory_age_unique_constraint(session):
    session.add(DimWarehouse(warehouse_code="DE1", warehouse_name="德国一仓",
                             country_code="DE", currency_code="EUR"))
    session.add(StgInventoryAge(snapshot_date=date(2026, 9, 1), sku="SKU1",
                                product_name="商品1", quantity=10, warehouse_age=400,
                                age_bucket="critical", warehouse_code="DE1"))
    session.commit()  # 第一条 OK

    # 第二条同 (snapshot_date, sku, warehouse_code) 应当被唯一约束阻止
    session.add(StgInventoryAge(snapshot_date=date(2026, 9, 1), sku="SKU1",
                                product_name="商品1-重名", quantity=5, warehouse_age=200,
                                age_bucket="stale", warehouse_code="DE1"))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    # 不同 sku 应允许
    session.add(StgInventoryAge(snapshot_date=date(2026, 9, 1), sku="SKU2",
                                product_name="商品2", quantity=3, warehouse_age=50,
                                age_bucket="healthy", warehouse_code="DE1"))
    session.commit()
    rows = session.scalars(select(StgInventoryAge)).all()
    assert len(rows) == 2


def test_monthly_report_jsonb_field(session):
    session.add(DimWarehouse(warehouse_code="DE1", warehouse_name="德国一仓",
                             country_code="DE", currency_code="EUR"))
    session.add(MartMonthlyReport(
        report_month="2026-08", warehouse_code="DE1",
        title="8月报告", cost_change={"total": 1234.5, "mom_pct": 3.2},
        content_md="# 报告", status="draft",
    ))
    session.commit()
    r = session.scalars(select(MartMonthlyReport)).one()
    assert r.cost_change["mom_pct"] == 3.2
    assert r.status == "draft"


def test_sync_log(session):
    session.add(SyncLog(task_name="sync_bills", endpoint="billing_list",
                        status="success", records_affected=10, message="ok"))
    session.commit()
    log = session.scalars(select(SyncLog)).one()
    assert log.status == "success"
    assert log.started_at is not None