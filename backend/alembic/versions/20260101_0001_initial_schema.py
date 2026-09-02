"""initial schema: 10 tables (dim/stg/mart/ops)

Revision ID: 20260101_0001_initial_schema
Revises:
Create Date: 2026-01-01 00:00:00
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260101_0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- dim_warehouse ----
    op.create_table(
        "dim_warehouse",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("warehouse_code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("warehouse_name", sa.String(length=128), nullable=False),
        sa.Column("country_code", sa.CHAR(length=2), nullable=False),
        sa.Column("currency_code", sa.CHAR(length=3), nullable=False, server_default="EUR"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ---- fee_category_map ----
    op.create_table(
        "fee_category_map",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("match_keyword", sa.String(length=128), nullable=False),
        sa.Column("fee_category", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("remark", sa.String(length=255)),
    )

    # ---- stg_bills ----
    op.create_table(
        "stg_bills",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bill_number", sa.String(length=64), nullable=False),
        sa.Column("account_code", sa.String(length=64)),
        sa.Column("bill_from_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bill_to_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bill_month", sa.CHAR(length=7), nullable=False),
        sa.Column("all_total", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency_code", sa.CHAR(length=3), nullable=False),
        sa.Column("warehouse_code", sa.String(length=32)),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("bill_number", name="uk_stg_bills_number"),
        sa.ForeignKeyConstraint(["warehouse_code"], ["dim_warehouse.warehouse_code"], ondelete="SET NULL"),
    )
    op.create_index("ix_stg_bills_month", "stg_bills", ["bill_month"])
    op.create_index("ix_stg_bills_wh", "stg_bills", ["warehouse_code"])

    # ---- stg_bill_fee_items ----
    op.create_table(
        "stg_bill_fee_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bill_number", sa.String(length=64), nullable=False),
        sa.Column("fee_name", sa.String(length=128), nullable=False),
        sa.Column("fee_category", sa.String(length=32), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("currency_code", sa.CHAR(length=3), nullable=False),
        sa.Column("related_sku", sa.String(length=64)),
        sa.Column("bill_month", sa.CHAR(length=7), nullable=False),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["bill_number"], ["stg_bills.bill_number"], ondelete="CASCADE"),
    )
    op.create_index("ix_fee_bill", "stg_bill_fee_items", ["bill_number"])
    op.create_index("ix_fee_month_cat", "stg_bill_fee_items", ["bill_month", "fee_category"])
    op.create_index("ix_fee_sku", "stg_bill_fee_items", ["related_sku"])

    # ---- stg_inventory_age ----
    op.create_table(
        "stg_inventory_age",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=255)),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warehouse_age", sa.Integer(), nullable=False),
        sa.Column("inbound_time", sa.DateTime(timezone=True)),
        sa.Column("age_bucket", sa.String(length=16), nullable=False),
        sa.Column("warehouse_code", sa.String(length=32)),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("snapshot_date", "sku", "warehouse_code", name="uk_age_snapshot"),
        sa.ForeignKeyConstraint(["warehouse_code"], ["dim_warehouse.warehouse_code"], ondelete="SET NULL"),
    )
    op.create_index("ix_age_date", "stg_inventory_age", ["snapshot_date"])
    op.create_index("ix_age_sku", "stg_inventory_age", ["sku"])
    op.create_index("ix_age_bucket", "stg_inventory_age", ["snapshot_date", "age_bucket"])

    # ---- stg_inventory_status ----
    op.create_table(
        "stg_inventory_status",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("sellable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unsellable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("onway", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warehouse_code", sa.String(length=32)),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("snapshot_date", "sku", "warehouse_code", name="uk_status_snapshot"),
        sa.ForeignKeyConstraint(["warehouse_code"], ["dim_warehouse.warehouse_code"], ondelete="SET NULL"),
    )
    op.create_index("ix_status_date", "stg_inventory_status", ["snapshot_date"])
    op.create_index("ix_status_sku", "stg_inventory_status", ["sku"])

    # ---- mart_monthly_cost_summary ----
    op.create_table(
        "mart_monthly_cost_summary",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("bill_month", sa.CHAR(length=7), nullable=False),
        sa.Column("warehouse_code", sa.String(length=32), nullable=False),
        sa.Column("total_cost", sa.Numeric(18, 4), nullable=False),
        sa.Column("storage_fee", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("inbound_fee", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("outbound_fee", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("transport_fee", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("other_fee", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("currency_code", sa.CHAR(length=3), nullable=False),
        sa.Column("mom_change_pct", sa.Numeric(8, 2)),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("bill_month", "warehouse_code", name="uk_cost_month"),
        sa.ForeignKeyConstraint(["warehouse_code"], ["dim_warehouse.warehouse_code"], ondelete="RESTRICT"),
    )

    # ---- mart_risk_sku ----
    op.create_table(
        "mart_risk_sku",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("sku", sa.String(length=64), nullable=False),
        sa.Column("product_name", sa.String(length=255)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("warehouse_age", sa.Integer(), nullable=False),
        sa.Column("age_bucket", sa.String(length=16), nullable=False),
        sa.Column("risk_rank", sa.Integer(), nullable=False),
        sa.Column("warehouse_code", sa.String(length=32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["warehouse_code"], ["dim_warehouse.warehouse_code"], ondelete="RESTRICT"),
    )
    op.create_index("ix_risk_date", "mart_risk_sku", ["snapshot_date", "risk_rank"])

    # ---- mart_monthly_reports ----
    op.create_table(
        "mart_monthly_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("report_month", sa.CHAR(length=7), nullable=False),
        sa.Column("warehouse_code", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("cost_change", postgresql.JSONB()),
        sa.Column("cost_drivers", postgresql.JSONB()),
        sa.Column("inventory_risk", postgresql.JSONB()),
        sa.Column("recommendations", postgresql.JSONB()),
        sa.Column("content_md", sa.Text()),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("report_month", "warehouse_code", name="uk_report_month"),
        sa.ForeignKeyConstraint(["warehouse_code"], ["dim_warehouse.warehouse_code"], ondelete="RESTRICT"),
    )

    # ---- sync_logs ----
    op.create_table(
        "sync_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("task_name", sa.String(length=64), nullable=False),
        sa.Column("endpoint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("records_affected", sa.Integer()),
        sa.Column("message", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_sync_task", "sync_logs", ["task_name", "started_at"])


def downgrade() -> None:
    # 倒序删除，保持外键依赖安全
    op.drop_index("ix_sync_task", table_name="sync_logs")
    op.drop_table("sync_logs")
    op.drop_table("mart_monthly_reports")
    op.drop_index("ix_risk_date", table_name="mart_risk_sku")
    op.drop_table("mart_risk_sku")
    op.drop_table("mart_monthly_cost_summary")
    op.drop_index("ix_status_sku", table_name="stg_inventory_status")
    op.drop_index("ix_status_date", table_name="stg_inventory_status")
    op.drop_table("stg_inventory_status")
    op.drop_index("ix_age_bucket", table_name="stg_inventory_age")
    op.drop_index("ix_age_sku", table_name="stg_inventory_age")
    op.drop_index("ix_age_date", table_name="stg_inventory_age")
    op.drop_table("stg_inventory_age")
    op.drop_index("ix_fee_sku", table_name="stg_bill_fee_items")
    op.drop_index("ix_fee_month_cat", table_name="stg_bill_fee_items")
    op.drop_index("ix_fee_bill", table_name="stg_bill_fee_items")
    op.drop_table("stg_bill_fee_items")
    op.drop_index("ix_stg_bills_wh", table_name="stg_bills")
    op.drop_index("ix_stg_bills_month", table_name="stg_bills")
    op.drop_table("stg_bills")
    op.drop_table("fee_category_map")
    op.drop_table("dim_warehouse")