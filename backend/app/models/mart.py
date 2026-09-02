"""分析层（mart_*）：由分析引擎物化的结果，供前端查询。

- mart_monthly_cost_summary : 月度成本汇总 + 五大费用分项 + 环比
- mart_risk_sku            : 风险 SKU 排行快照（TOP20）
- mart_monthly_reports     : 《德国海外仓成本健康报告》
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CHAR, Date, DateTime, ForeignKey, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


JSONType = JSONB().with_variant(JSON(), "sqlite")


class MartMonthlyCostSummary(Base):
    """月度成本汇总（物化）。"""

    __tablename__ = "mart_monthly_cost_summary"
    __table_args__ = (
        UniqueConstraint("bill_month", "warehouse_code", name="uk_cost_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_month: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    warehouse_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("dim_warehouse.warehouse_code", ondelete="RESTRICT"), nullable=False
    )
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    storage_fee: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    inbound_fee: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    outbound_fee: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    transport_fee: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    other_fee: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    mom_change_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MartRiskSku(Base):
    """风险 SKU 排行（按 库龄desc + 数量desc，TOP20）。"""

    __tablename__ = "mart_risk_sku"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    product_name: Mapped[str | None] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(nullable=False)
    warehouse_age: Mapped[int] = mapped_column(nullable=False)
    age_bucket: Mapped[str] = mapped_column(String(16), nullable=False)
    risk_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    warehouse_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("dim_warehouse.warehouse_code", ondelete="RESTRICT"), nullable=False
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MartMonthlyReport(Base):
    """月度报告：《德国海外仓成本健康报告》。"""

    __tablename__ = "mart_monthly_reports"
    __table_args__ = (
        UniqueConstraint("report_month", "warehouse_code", name="uk_report_month"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    report_month: Mapped[str] = mapped_column(CHAR(7), nullable=False)
    warehouse_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("dim_warehouse.warehouse_code", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    cost_change: Mapped[dict | None] = mapped_column(JSONType)
    cost_drivers: Mapped[dict | None] = mapped_column(JSONType)
    inventory_risk: Mapped[dict | None] = mapped_column(JSONType)
    recommendations: Mapped[dict | None] = mapped_column(JSONType)
    content_md: Mapped[str | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )