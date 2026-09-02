"""原始层（stg_*）：直接来自 GoodCang API 的数据，含原始报文。

- stg_bills                : 月度账单主表（来源 billing_list）
- stg_bill_fee_items       : 账单费用明细（来源 billing_export）
- stg_inventory_age        : 库存年龄快照（来源 inventory_age_list）
- stg_inventory_status     : 当前库存状态快照（来源 get_product_inventory）

幂等策略：
- 账单：UPSERT by bill_number
- 库存：UPSERT by (snapshot_date, sku, warehouse_code)
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Date, DateTime, ForeignKey, JSON, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


# 用 JSONB（PostgreSQL 专属），更高效；非 PG 环境自动 fallback 到 JSON。
JSONType = JSONB().with_variant(JSON(), "sqlite")


class StgBill(Base):
    """月度账单主表。"""

    __tablename__ = "stg_bills"
    __table_args__ = (UniqueConstraint("bill_number", name="uk_stg_bills_number"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_number: Mapped[str] = mapped_column(String(64), nullable=False)
    account_code: Mapped[str | None] = mapped_column(String(64))
    bill_from_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bill_to_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bill_month: Mapped[str] = mapped_column(CHAR(7), nullable=False)  # YYYY-MM
    all_total: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    warehouse_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("dim_warehouse.warehouse_code", ondelete="SET NULL")
    )
    raw_json: Mapped[dict | None] = mapped_column(JSONType)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StgBillFeeItem(Base):
    """账单费用明细。fee_category 已归一化到五大类。"""

    __tablename__ = "stg_bill_fee_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_number: Mapped[str] = mapped_column(
        String(64), ForeignKey("stg_bills.bill_number", ondelete="CASCADE"), nullable=False
    )
    fee_name: Mapped[str] = mapped_column(String(128), nullable=False)
    fee_category: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    related_sku: Mapped[str | None] = mapped_column(String(64))
    bill_month: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(JSONType)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StgInventoryAge(Base):
    """库存年龄快照：时点数，按 (snapshot_date, sku, warehouse_code) 唯一。"""

    __tablename__ = "stg_inventory_age"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "sku", "warehouse_code", name="uk_age_snapshot"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(nullable=False, default=0)
    warehouse_age: Mapped[int] = mapped_column(nullable=False)  # 天
    inbound_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    age_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    warehouse_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("dim_warehouse.warehouse_code", ondelete="SET NULL")
    )
    raw_json: Mapped[dict | None] = mapped_column(JSONType)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StgInventoryStatus(Base):
    """当前库存状态快照：按 (snapshot_date, sku, warehouse_code) 唯一。"""

    __tablename__ = "stg_inventory_status"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date", "sku", "warehouse_code", name="uk_status_snapshot"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    sellable: Mapped[int] = mapped_column(nullable=False, default=0)
    unsellable: Mapped[int] = mapped_column(nullable=False, default=0)
    reserved: Mapped[int] = mapped_column(nullable=False, default=0)
    onway: Mapped[int] = mapped_column(nullable=False, default=0)
    warehouse_code: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("dim_warehouse.warehouse_code", ondelete="SET NULL")
    )
    raw_json: Mapped[dict | None] = mapped_column(JSONType)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )