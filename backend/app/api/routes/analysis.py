"""分析相关 API 路由：成本 / 结构 / 库存健康 / 风险SKU / 报告。"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.services.analysis_engine import AnalysisEngine
from app.models import MartMonthlyCostSummary

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _wh(db: Session) -> str:
    """当前目标仓（德国仓）。"""
    return get_settings().goodcang_warehouse_code


def _latest_month(db: Session, wh: str) -> str | None:
    from sqlalchemy import select
    return db.scalar(
        select(MartMonthlyCostSummary.bill_month)
        .where(MartMonthlyCostSummary.warehouse_code == wh)
        .order_by(MartMonthlyCostSummary.bill_month.desc())
        .limit(1)
    )


@router.get("/cost/summary")
def cost_summary(bill_month: str | None = Query(default=None), db: Session = Depends(get_db)):
    """月度成本总览：总成本 + 环比 + 五大类。"""
    wh = _wh(db)
    month = bill_month or _latest_month(db, wh)
    if not month:
        raise HTTPException(404, "no cost data yet, run sync first")
    eng = AnalysisEngine(db)
    structure = eng.cost_structure(month, wh)
    mom = db.scalar(
        __import__("sqlalchemy").select(MartMonthlyCostSummary.mom_change_pct)
        .where(MartMonthlyCostSummary.bill_month == month,
               MartMonthlyCostSummary.warehouse_code == wh)
    )
    return {
        "month": month,
        "total": structure["total"],
        "mom_pct": float(mom) if mom is not None else None,
        "structure": structure["items"],
    }


@router.get("/cost/trend")
def cost_trend(months: int = Query(default=12, ge=1, le=36), db: Session = Depends(get_db)):
    """近 N 个月成本趋势。"""
    wh = _wh(db)
    eng = AnalysisEngine(db)
    return {"warehouse": wh, "trend": eng.cost_trend(wh, months)}


@router.get("/inventory/health")
def inventory_health(snapshot_date: str | None = Query(default=None), db: Session = Depends(get_db)):
    """库存健康分桶。"""
    wh = _wh(db)
    eng = AnalysisEngine(db)
    if snapshot_date:
        snap = date.fromisoformat(snapshot_date)
    else:
        from sqlalchemy import select
        from app.models import StgInventoryAge
        snap = db.scalar(
            select(StgInventoryAge.snapshot_date)
            .where(StgInventoryAge.warehouse_code == wh)
            .order_by(StgInventoryAge.snapshot_date.desc()).limit(1)
        )
    if not snap:
        raise HTTPException(404, "no inventory data yet")
    return eng.inventory_health(snap, wh)


@router.get("/inventory/risk-sku")
def risk_sku(snapshot_date: str | None = Query(default=None), top: int = Query(default=20, ge=1, le=100),
             db: Session = Depends(get_db)):
    """风险 SKU 排行。"""
    wh = _wh(db)
    eng = AnalysisEngine(db)
    if snapshot_date:
        snap = date.fromisoformat(snapshot_date)
    else:
        from sqlalchemy import select
        from app.models import StgInventoryAge
        snap = db.scalar(
            select(StgInventoryAge.snapshot_date)
            .where(StgInventoryAge.warehouse_code == wh)
            .order_by(StgInventoryAge.snapshot_date.desc()).limit(1)
        )
    if not snap:
        raise HTTPException(404, "no inventory data yet")
    return {"snapshot_date": snap.isoformat(), "items": eng.risk_sku_top(snap, wh, top)}


@router.get("/report/monthly")
def monthly_report(report_month: str | None = Query(default=None), db: Session = Depends(get_db)):
    """月度报告（若无则现场生成）。"""
    wh = _wh(db)
    eng = AnalysisEngine(db)
    month = report_month or _latest_month(db, wh)
    if not month:
        raise HTTPException(404, "no cost data yet")
    report = eng.generate_report(month, wh)
    return {
        "report_month": report.report_month,
        "title": report.title,
        "cost_change": report.cost_change,
        "cost_drivers": report.cost_drivers,
        "inventory_risk": report.inventory_risk,
        "recommendations": report.recommendations,
        "content_md": report.content_md,
        "status": report.status,
    }