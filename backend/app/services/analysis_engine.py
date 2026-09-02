"""分析引擎：把原始层(stg_*) 聚合为分析层(mart_*) 及报告。

覆盖功能 A/B/C/D/E：
- A 月度成本分析：本月总成本、环比、12 月趋势、成本结构
- B 费用结构分析：五大类费用
- C 库存健康分析：库龄分桶
- D 风险 SKU 排行：库龄 desc + 数量 desc，TOP20
- E 自动月度报告：《德国海外仓成本健康报告》
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    MartMonthlyCostSummary, MartMonthlyReport, MartRiskSku,
    StgBill, StgBillFeeItem, StgInventoryAge, StgInventoryStatus,
)

logger = logging.getLogger(__name__)

FEE_CATEGORIES = ("storage", "inbound", "outbound", "transport", "other")
BUCKET_LABELS = {
    "healthy": "健康库存",
    "watch": "关注库存",
    "stale": "呆滞库存",
    "critical": "严重呆滞库存",
}
CURRENCY_SYMBOLS = {
    "EUR": "€",
    "CNY": "¥",
    "USD": "$",
    "GBP": "£",
}


class AnalysisEngine:
    """分析引擎。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---------- A/B：月度成本汇总 ----------
    def compute_monthly_cost(self, bill_month: str, warehouse_code: str) -> MartMonthlyCostSummary:
        """聚合某月某仓的成本（总 + 五大类）。"""
        fee_rows = self.db.scalars(
            select(StgBillFeeItem).where(
                StgBillFeeItem.bill_month == bill_month,
            )
        ).all()

        totals: dict[str, Decimal] = defaultdict(Decimal)
        for r in fee_rows:
            totals[r.fee_category] += r.amount

        # 如果费用明细缺失，退回到账单主表总额兜底
        total_cost = sum(totals.values(), Decimal("0"))
        if total_cost == 0:
            bills = self.db.scalars(
                select(StgBill).where(StgBill.bill_month == bill_month)
            ).all()
            total_cost = sum((b.all_total for b in bills), Decimal("0"))

        # 计算环比
        mom_pct = self._mom_change(bill_month, warehouse_code, total_cost)

        row = MartMonthlyCostSummary(
            bill_month=bill_month,
            warehouse_code=warehouse_code,
            total_cost=total_cost,
            storage_fee=totals["storage"],
            inbound_fee=totals["inbound"],
            outbound_fee=totals["outbound"],
            transport_fee=totals["transport"],
            other_fee=totals["other"],
            currency_code="EUR",
            mom_change_pct=mom_pct,
        )
        # UPSERT
        self.db.execute(delete(MartMonthlyCostSummary).where(
            MartMonthlyCostSummary.bill_month == bill_month,
            MartMonthlyCostSummary.warehouse_code == warehouse_code,
        ))
        self.db.add(row)
        self.db.commit()
        return row

    def _mom_change(self, bill_month: str, warehouse_code: str, current: Decimal) -> Decimal | None:
        """环比：与上月总成本比较。"""
        prev_month = self._prev_month(bill_month)
        prev = self.db.scalar(
            select(MartMonthlyCostSummary.total_cost).where(
                MartMonthlyCostSummary.bill_month == prev_month,
                MartMonthlyCostSummary.warehouse_code == warehouse_code,
            )
        )
        if prev is None or prev == 0:
            return None
        return ((current - prev) / prev * 100).quantize(Decimal("0.01"))

    def cost_trend(self, warehouse_code: str, months: int = 12) -> list[dict[str, Any]]:
        """近 N 个月成本趋势。"""
        rows = self.db.scalars(
            select(MartMonthlyCostSummary)
            .where(MartMonthlyCostSummary.warehouse_code == warehouse_code)
            .order_by(MartMonthlyCostSummary.bill_month.desc())
            .limit(months)
        ).all()
        rows = sorted(rows, key=lambda r: r.bill_month)
        return [
            {"month": r.bill_month, "total": float(r.total_cost),
             "storage": float(r.storage_fee), "transport": float(r.transport_fee),
             "mom_pct": float(r.mom_change_pct) if r.mom_change_pct is not None else None}
            for r in rows
        ]

    def cost_structure(self, bill_month: str, warehouse_code: str) -> dict[str, Any]:
        """本月费用结构（五大类占比）。"""
        row = self.db.scalar(
            select(MartMonthlyCostSummary).where(
                MartMonthlyCostSummary.bill_month == bill_month,
                MartMonthlyCostSummary.warehouse_code == warehouse_code,
            )
        )
        if row is None:
            return {"total": 0, "items": []}
        items = [
            {"category": c, "label": self._cat_label(c),
             "amount": float(getattr(row, f"{c}_fee"))}
            for c in FEE_CATEGORIES
        ]
        return {"total": float(row.total_cost), "items": items}

    # ---------- C：库存健康 ----------
    def inventory_health(self, snapshot_date: date, warehouse_code: str) -> dict[str, Any]:
        """库存健康分桶汇总。"""
        rows = self.db.scalars(
            select(StgInventoryAge).where(
                StgInventoryAge.snapshot_date == snapshot_date,
                StgInventoryAge.warehouse_code == warehouse_code,
            )
        ).all()
        buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {"sku_count": 0, "quantity": 0})
        for r in rows:
            b = buckets[r.age_bucket]
            b["sku_count"] += 1
            b["quantity"] += r.quantity
        result = []
        for b in ("healthy", "watch", "stale", "critical"):
            result.append({
                "bucket": b, "label": BUCKET_LABELS[b],
                "sku_count": buckets[b]["sku_count"],
                "quantity": buckets[b]["quantity"],
            })
        total_qty = sum(x["quantity"] for x in result)
        for x in result:
            x["qty_pct"] = round(x["quantity"] / total_qty * 100, 2) if total_qty else 0
        return {"snapshot_date": snapshot_date.isoformat(), "total_quantity": total_qty, "buckets": result}

    # ---------- D：风险 SKU 排行 ----------
    def risk_sku_top(self, snapshot_date: date, warehouse_code: str, top: int = 20) -> list[dict[str, Any]]:
        """风险 SKU 排行：库龄 desc，数量 desc。"""
        rows = self.db.scalars(
            select(StgInventoryAge).where(
                StgInventoryAge.snapshot_date == snapshot_date,
                StgInventoryAge.warehouse_code == warehouse_code,
            )
        ).all()
        # 只保留有风险的（非 healthy）
        risky = [r for r in rows if r.age_bucket != "healthy"]
        risky.sort(key=lambda r: (r.warehouse_age, r.quantity), reverse=True)

        # 物化到 mart_risk_sku
        self.db.execute(delete(MartRiskSku).where(
            MartRiskSku.snapshot_date == snapshot_date,
            MartRiskSku.warehouse_code == warehouse_code,
        ))
        result = []
        for i, r in enumerate(risky[:top], start=1):
            self.db.add(MartRiskSku(
                snapshot_date=snapshot_date, sku=r.sku, product_name=r.product_name,
                quantity=r.quantity, warehouse_age=r.warehouse_age,
                age_bucket=r.age_bucket, risk_rank=i, warehouse_code=warehouse_code,
            ))
            result.append({
                "rank": i, "sku": r.sku, "product_name": r.product_name,
                "quantity": r.quantity, "warehouse_age": r.warehouse_age,
                "age_bucket": r.age_bucket, "label": BUCKET_LABELS[r.age_bucket],
            })
        self.db.commit()
        return result

    # ---------- E：月度报告 ----------
    def generate_report(self, report_month: str, warehouse_code: str) -> MartMonthlyReport:
        """生成《德国海外仓成本健康报告》。"""
        cost = self.db.scalar(
            select(MartMonthlyCostSummary).where(
                MartMonthlyCostSummary.bill_month == report_month,
                MartMonthlyCostSummary.warehouse_code == warehouse_code,
            )
        )
        trend = self.cost_trend(warehouse_code)
        structure = self.cost_structure(report_month, warehouse_code)

        # 库存健康用本月最后一天快照（取最近可用快照）
        snap = self._latest_snapshot(warehouse_code)
        health = self.inventory_health(snap, warehouse_code) if snap else None
        risk = self.risk_sku_top(snap, warehouse_code) if snap else []

        cost_change = {
            "month": report_month,
            "total": float(cost.total_cost) if cost else 0,
            "mom_pct": float(cost.mom_change_pct) if cost and cost.mom_change_pct is not None else None,
            "trend": trend,
        }
        cost_drivers = self._drivers(structure)
        inventory_risk = {"health": health, "top_risk_sku": risk}
        symbol = CURRENCY_SYMBOLS.get(cost.currency_code, "€") if cost else "€"
        recommendations = self._recommendations(cost_change, structure, health, risk, symbol)

        content_md = self._render_markdown(
            report_month, cost_change, structure, health, risk, recommendations, symbol
        )

        report = MartMonthlyReport(
            report_month=report_month, warehouse_code=warehouse_code,
            title=f"德国海外仓成本健康报告（{report_month}）",
            cost_change=cost_change, cost_drivers=cost_drivers,
            inventory_risk=inventory_risk, recommendations=recommendations,
            content_md=content_md, status="published",
        )
        self.db.execute(delete(MartMonthlyReport).where(
            MartMonthlyReport.report_month == report_month,
            MartMonthlyReport.warehouse_code == warehouse_code,
        ))
        self.db.add(report)
        self.db.commit()
        return report

    def _drivers(self, structure: dict[str, Any]) -> dict[str, Any]:
        items = sorted(structure.get("items", []), key=lambda x: x["amount"], reverse=True)
        total = structure.get("total", 0)
        return {
            "top_category": items[0]["label"] if items else None,
            "top_amount": items[0]["amount"] if items else 0,
            "top_pct": round(items[0]["amount"] / total * 100, 2) if total and items else 0,
            "items": items,
        }

    def _recommendations(self, cost_change, structure, health, risk, symbol: str = "€") -> list[dict[str, str]]:
        recs: list[dict[str, str]] = []
        # 成本
        mom = cost_change.get("mom_pct")
        if mom is not None and mom > 10:
            recs.append({"type": "成本", "level": "高",
                         "text": f"本月总成本环比上涨 {mom}%，建议核查主要费用项增长原因。"})
        # 费用结构
        drivers = structure.get("items", [])
        if drivers:
            top = max(drivers, key=lambda x: x["amount"])
            if top["amount"] > 0:
                recs.append({"type": "费用", "level": "中",
                             "text": f"费用以「{top['label']}」为主（{symbol}{top['amount']:.2f}），可重点优化该项。"})
        # 库存
        if health:
            critical = next((b for b in health["buckets"] if b["bucket"] == "critical"), None)
            if critical and critical["quantity"] > 0:
                recs.append({"type": "库存", "level": "高",
                             "text": f"严重呆滞库存 {critical['quantity']} 件，建议评估促销/退运/销毁方案。"})
        if risk:
            recs.append({"type": "库存", "level": "中",
                         "text": f"TOP 风险 SKU：{risk[0]['sku']}（库龄 {risk[0]['warehouse_age']} 天，{risk[0]['quantity']} 件）。"})
        if not recs:
            recs.append({"type": "综合", "level": "低", "text": "本月成本与库存整体健康，保持当前运营节奏。"})
        return recs

    def _render_markdown(self, month, cost_change, structure, health, risk, recs, symbol: str = "€") -> str:
        lines = [f"# 德国海外仓成本健康报告（{month}）", ""]
        lines.append(f"## 一、成本变化")
        lines.append(f"- 本月总成本：{symbol}{cost_change['total']:.2f}")
        if cost_change["mom_pct"] is not None:
            lines.append(f"- 环比变化：{cost_change['mom_pct']:+.2f}%")
        lines.append("")
        lines.append("## 二、费用结构")
        for it in structure.get("items", []):
            lines.append(f"- {it['label']}：{symbol}{it['amount']:.2f}")
        lines.append("")
        lines.append("## 三、库存风险")
        if health:
            for b in health["buckets"]:
                lines.append(f"- {b['label']}：{b['sku_count']} SKU / {b['quantity']} 件")
        if risk:
            lines.append(f"\nTOP 风险 SKU：")
            for r in risk[:5]:
                lines.append(f"- #{r['rank']} {r['sku']}（库龄 {r['warehouse_age']} 天，{r['quantity']} 件）")
        lines.append("")
        lines.append("## 四、优化建议")
        for r in recs:
            lines.append(f"- [{r['level']}] {r['text']}")
        return "\n".join(lines)

    # ---------- 辅助 ----------
    def _latest_snapshot(self, warehouse_code: str) -> date | None:
        return self.db.scalar(
            select(StgInventoryAge.snapshot_date)
            .where(StgInventoryAge.warehouse_code == warehouse_code)
            .order_by(StgInventoryAge.snapshot_date.desc())
            .limit(1)
        )

    @staticmethod
    def _prev_month(bill_month: str) -> str:
        y, m = int(bill_month[:4]), int(bill_month[5:7])
        if m == 1:
            return f"{y - 1}-12"
        return f"{y}-{m - 1:02d}"

    @staticmethod
    def _cat_label(cat: str) -> str:
        return {
            "storage": "仓储费", "inbound": "入库费",
            "outbound": "出库操作费", "transport": "运输费", "other": "其他费用",
        }.get(cat, cat)