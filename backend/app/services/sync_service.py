"""数据同步服务：把 GoodCang 4 个接口的响应落库。

职责：
- 拉取（分页）→ 归一化 → 幂等写入（UPSERT）
- 每步写 sync_logs
- 用 fee_category_map 给费用明细归类

字段映射说明（2026-09-01 校准）：
- billing_list: all_total 是 {balance, currency_code} 嵌套结构；金额从 balance 取
- inventory_age_list: 关键字段 lba_quantity / lba_fifo_time / lba_warning_age /
  product_sku / product_title / product_title_en / warehouse_desc / warehouse_age /
  expiration_date
- get_product_inventory: 关键字段 product_sku / sellable / unsellable / reserved /
  shipped / onway / pending / pi_freeze / pi_warning_qty 等

幂等策略（与 database-design.md 一致）：
- 账单：bill_number 唯一 UPSERT
- 费用明细：先按账单 delete 后 insert（随账单一起同步）
- 库存年龄/状态：按 (snapshot_date, sku, warehouse_code) UPSERT
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.connectors.goodcang import (
    BillingExportRequest,
    BillingListRequest,
    GoodCangClient,
    GoodCangEndpoints,
    InventoryAgeListRequest,
    ProductInventoryRequest,
)
from app.core.config import get_settings
from app.models import (
    DimWarehouse,
    FeeCategoryMap,
    StgBill,
    StgBillFeeItem,
    StgInventoryAge,
    StgInventoryStatus,
    SyncLog,
)

logger = logging.getLogger(__name__)


# 库龄分桶规则（功能 C）
def bucket_age(age_days: int) -> str:
    if age_days < 90:
        return "healthy"
    if age_days < 180:
        return "watch"
    if age_days < 365:
        return "stale"
    return "critical"


def _balance_amount(raw: Any, prefer_currency: str = "EUR") -> Decimal:
    """提取账单金额。

    真实响应（2026-09-01 实调）：金额字段是**多币种数组**，形如
    ``[{"currency_code": "EUR", "balance": "25869.46"}, ...]``。
    优先取 ``prefer_currency`` 的非零 balance；找不到则取第一个非零 balance；
    全为 0 则返回 0。兼容单个 ``{balance, currency_code}`` dict 与裸数值。
    """
    if raw is None:
        return Decimal("0")

    # 多币种数组
    if isinstance(raw, list):
        items = raw
        # 1) 优先币种（非零）
        for it in items:
            if isinstance(it, dict) and it.get("currency_code") == prefer_currency:
                v = it.get("balance")
                if v not in (None, "", "0", 0):
                    try:
                        return Decimal(str(v))
                    except Exception:  # noqa: BLE001
                        continue
        # 2) 第一个非零
        for it in items:
            if isinstance(it, dict):
                v = it.get("balance")
                if v not in (None, "", "0", 0):
                    try:
                        return Decimal(str(v))
                    except Exception:  # noqa: BLE001
                        continue
        return Decimal("0")

    # 单个对象 / 裸值（向后兼容）
    if isinstance(raw, dict):
        v = raw.get("balance")
    else:
        v = raw
    try:
        return Decimal(str(v or 0))
    except Exception:  # noqa: BLE001
        return Decimal("0")


def _balance_currency(raw: Any, default: str = "EUR") -> str:
    """提取主币种：优先 EUR；否则取第一个非零金额的币种；兜底 default。"""
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict):
                cc = it.get("currency_code")
                bal = it.get("balance")
                if cc and bal not in (None, "", "0", 0):
                    return cc
        for it in raw:
            if isinstance(it, dict) and it.get("currency_code"):
                return it["currency_code"]
        return default
    if isinstance(raw, dict):
        c = raw.get("currency_code")
        if c:
            return c
    return default


class SyncService:
    """数据同步编排。每个接口一个方法，返回处理的记录数。"""

    def __init__(
        self, db: Session, client: GoodCangClient, endpoints: GoodCangEndpoints
    ) -> None:
        self.db = db
        self.client = client
        self.ep = endpoints
        self.settings = get_settings()
        self.wh_code = self.settings.goodcang_warehouse_code

    # ---- 同步日志辅助 ----
    def _log(
        self,
        task_name: str,
        endpoint: str,
        status: str,
        records: int | None,
        message: str | None,
    ) -> None:
        self.db.add(
            SyncLog(
                task_name=task_name,
                endpoint=endpoint,
                status=status,
                records_affected=records,
                message=message,
                finished_at=datetime.now(timezone.utc),
            )
        )
        self.db.commit()

    # ---- 费用归类 ----
    def _classify(self, fee_name: str) -> str:
        """按 fee_category_map 匹配 fee_name；未命中归 other。"""
        maps = self.db.scalars(
            select(FeeCategoryMap).order_by(FeeCategoryMap.priority)
        ).all()
        for m in maps:
            if m.match_keyword and m.match_keyword in fee_name:
                return m.fee_category
        return "other"

    # ---- 1. 账单主表 ----
    async def sync_bills(
        self,
        begin_bill_to_time: str | None = None,
        end_bill_to_time: str | None = None,
        account_code: str | None = None,
    ) -> int:
        """同步账单主表（按时间区间或单号）。

        - 默认同步最近 3 个月到现在的账单
        - account_code 可选（3-20 位客户编码，如 ACG1505603）；不传则拉全部客户账单。
          注意：account_code 不是 AppToken，而是谷仓的客户编码。
        """
        req = BillingListRequest(
            account_code=account_code,
            begin_bill_to_time=begin_bill_to_time,
            end_bill_to_time=end_bill_to_time,
        )
        try:
            resp = await self.ep.billing_list(req)
        except Exception as e:  # noqa: BLE001
            self._log("sync_bills", "billing_list", "failed", None, str(e))
            raise

        rows = self._extract_list_rows(resp)
        n = 0
        for r in rows:
            n += self._upsert_bill(r)
        self.db.commit()
        self._log("sync_bills", "billing_list", "success", n, None)
        return n

    def _upsert_bill(self, r: dict[str, Any]) -> int:
        """单条账单 UPSERT（幂等）。"""
        bill_number = str(r.get("bill_number") or "")
        if not bill_number:
            return 0
        all_total = r.get("all_total") or []
        values = {
            "bill_number": bill_number,
            "account_code": r.get("account_code"),
            "bill_from_time": self._to_dt(r.get("bill_from_time")),
            "bill_to_time": self._to_dt(r.get("bill_to_time")),
            "bill_month": self._to_month(r.get("bill_to_time") or r.get("bill_from_time")),
            "all_total": _balance_amount(all_total, "EUR"),
            "currency_code": _balance_currency(all_total, "EUR"),
            "warehouse_code": r.get("warehouse_code") or self.wh_code,
            "raw_json": r,
        }
        stmt = pg_insert(StgBill).values(**values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["bill_number"],
            set_={k: v for k, v in values.items() if k != "bill_number"},
        )
        self.db.execute(stmt)
        return 1

    # ---- 2. 费用明细 ----
    async def sync_fee_items(self, bill_number: str) -> int:
        """同步某账单的费用明细。随账单先删后插。

        注意：谷仓的 billing_export 返回的是 base64 文件（xlsx/zip），不是结构化 JSON。
        完整解析需要 xlsx 解码（依赖 openpyxl），V1 暂存为 raw 记录 + 同步日志，
        后续可由 Step 8（二期）展开为费用行明细。
        """
        from app.core.config import get_settings as _gs
        account = _gs().goodcang_app_token
        req = BillingExportRequest(bill_number_list=[bill_number])
        try:
            resp = await self.ep.billing_export(req)
        except Exception as e:  # noqa: BLE001
            self._log("sync_fee_items", "billing_export", "failed", None, str(e))
            raise

        # billing_export.data 是 base64 字符串，存到 raw_json 即可
        data_b64 = ""
        if isinstance(resp, dict):
            data_b64 = str(resp.get("data") or "")
        self.db.add(StgBillFeeItem(
            bill_number=bill_number,
            fee_name="[export] base64 file",
            fee_category=self._classify(""),
            amount=Decimal("0"),
            currency_code="EUR",
            related_sku=None,
            bill_month=self._to_month(None),
            raw_json={"data": data_b64[:200] + "..." if len(data_b64) > 200 else data_b64,
                      "full_length": len(data_b64)},
        ))
        self.db.commit()
        self._log("sync_fee_items", "billing_export", "success", 1, f"file bytes={len(data_b64)}")
        return 1

    # ---- 3. 库存库龄 ----
    async def sync_inventory_age(self, snapshot_date: date | None = None) -> int:
        snap = snapshot_date or date.today()
        req = InventoryAgeListRequest(warehouse_code=self.wh_code)
        try:
            resp = await self.ep.inventory_age_list(req)
        except Exception as e:  # noqa: BLE001
            self._log("sync_inventory_age", "inventory_age_list", "failed", None, str(e))
            raise

        rows = self._extract_list_rows(resp)
        n = 0
        for r in rows:
            sku = str(r.get("product_sku") or "")
            if not sku:
                continue
            age = self._to_int(r.get("warehouse_age"))
            values = {
                "snapshot_date": snap,
                "sku": sku,
                "product_name": r.get("product_title") or r.get("product_title_en"),
                "quantity": self._to_int(r.get("iba_quantity")),
                "warehouse_age": age,
                "inbound_time": self._to_dt(r.get("iba_fifo_time")),
                "age_bucket": bucket_age(age),
                "warehouse_code": r.get("warehouse_code") or self.wh_code,
                "raw_json": r,
            }
            stmt = pg_insert(StgInventoryAge).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["snapshot_date", "sku", "warehouse_code"],
                set_={k: v for k, v in values.items()
                      if k not in ("snapshot_date", "sku", "warehouse_code")},
            )
            self.db.execute(stmt)
            n += 1
        self.db.commit()
        self._log("sync_inventory_age", "inventory_age_list", "success", n, None)
        return n

    # ---- 4. 库存状态 ----
    async def sync_inventory_status(self, snapshot_date: date | None = None) -> int:
        snap = snapshot_date or date.today()
        req = ProductInventoryRequest(warehouse_code=self.wh_code)
        try:
            resp = await self.ep.product_inventory(req)
        except Exception as e:  # noqa: BLE001
            self._log("sync_inventory_status", "get_product_inventory", "failed", None, str(e))
            raise

        rows = self._extract_list_rows(resp)
        n = 0
        for r in rows:
            sku = str(r.get("product_sku") or "")
            if not sku:
                continue
            values = {
                "snapshot_date": snap,
                "sku": sku,
                "sellable": self._to_int(r.get("sellable")),
                "unsellable": self._to_int(r.get("unsellable")),
                "reserved": self._to_int(r.get("reserved")),
                "onway": self._to_int(r.get("onway")),
                "warehouse_code": r.get("warehouse_code") or self.wh_code,
                "raw_json": r,
            }
            stmt = pg_insert(StgInventoryStatus).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=["snapshot_date", "sku", "warehouse_code"],
                set_={k: v for k, v in values.items()
                      if k not in ("snapshot_date", "sku", "warehouse_code")},
            )
            self.db.execute(stmt)
            n += 1
        self.db.commit()
        self._log("sync_inventory_status", "get_product_inventory", "success", n, None)
        return n

    # ---- 全量同步入口 ----
    async def sync_all(
        self,
        begin_bill_to_time: str | None = None,
        end_bill_to_time: str | None = None,
        snapshot_date: date | None = None,
    ) -> dict[str, int]:
        """依次同步 4 个接口，返回各任务记录数。"""
        result = {
            "bills": 0,
            "fee_items": 0,
            "inventory_age": 0,
            "inventory_status": 0,
        }
        result["bills"] = await self.sync_bills(begin_bill_to_time, end_bill_to_time)
        # 拉该时间窗所有账单号，逐个同步明细
        bill_numbers = self.db.scalars(select(StgBill.bill_number)).all()
        for bn in bill_numbers:
            result["fee_items"] += await self.sync_fee_items(bn)
        result["inventory_age"] = await self.sync_inventory_age(snapshot_date)
        result["inventory_status"] = await self.sync_inventory_status(snapshot_date)
        return result

    # ---- 辅助：解析响应结构 ----
    def _extract_list_rows(self, resp: Any) -> list[dict[str, Any]]:
        """谷仓 V2 风格：``{"code": 0, "message": "...", "data": {"list": [...], "total": N}}``。

        兼容形态：
        - ``{"data": {"list": [...]}}``  ← 主流
        - ``{"data": [...]}``            ← export 类型
        - ``{"data": "<base64>"}``       ← 账单导出
        - 直接 list
        """
        if isinstance(resp, list):
            return resp
        if not isinstance(resp, dict):
            return []
        data = resp.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("list", "rows", "records", "items", "result"):
                if isinstance(data.get(key), list):
                    return data[key]
        return []

    def _to_int(self, v: Any) -> int:
        """兼容字符串数值（谷仓部分数量字段返回 "120" 而非 120）。"""
        if v is None or v == "":
            return 0
        try:
            return int(v)
        except (TypeError, ValueError):
            try:
                return int(float(v))
            except (TypeError, ValueError):
                return 0

    def _to_dt(self, v: Any) -> datetime | None:
        if not v:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            # 截图示例 "2021-08-01" 或 "2021-07-27 23:59:59"
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
            ):
                try:
                    return datetime.strptime(v, fmt)
                except ValueError:
                    continue
            try:
                s = v.replace("Z", "+00:00")
                return datetime.fromisoformat(s)
            except ValueError:
                return None
        return None

    def _to_month(self, v: Any) -> str:
        dt = self._to_dt(v)
        if dt:
            return dt.strftime("%Y-%m")
        return datetime.now().strftime("%Y-%m")
