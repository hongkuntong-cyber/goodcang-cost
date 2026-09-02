"""维度与配置表：dim_warehouse、fee_category_map。

设计要点：
- dim_warehouse 多仓扩展：country_code / currency_code / is_active
- fee_category_map 把谷仓原始 fee_name 归类到五大类（仓储/入库/出库操作/运输/其他）
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CHAR, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DimWarehouse(Base):
    """仓库维度表。V1 主要用德国仓（DE）。"""

    __tablename__ = "dim_warehouse"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    warehouse_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    warehouse_name: Mapped[str] = mapped_column(String(128), nullable=False)
    country_code: Mapped[str] = mapped_column(CHAR(2), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="EUR")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FeeCategoryMap(Base):
    """费用归类映射表。

    把谷仓返回的原始 fee_name 关键字映射到五大费用类别：
    storage / inbound / outbound / transport / other
    """

    __tablename__ = "fee_category_map"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_keyword: Mapped[str] = mapped_column(String(128), nullable=False)
    fee_category: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    remark: Mapped[str | None] = mapped_column(String(255))