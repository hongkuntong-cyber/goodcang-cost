"""谷仓账单 xlsx 费用明细解析器。

把 billing_export 返回的 base64 xlsx 解析为费用行明细，并归类到五大类：
storage(仓储) / inbound(入库) / outbound(出库操作) / transport(运输) / other(其他)

xlsx 结构（8 个 sheet）：
- 账单说明：说明文字
- 账户汇总账单：账单头信息（账户/期间/余额）
- 账户充值明细：充值/转汇记录
- 入库费用明细：列有「费用类型」「费用明细」「本期费用小计」「币种」
- 仓租费用明细：同上（仓储费、超库龄附加费）
- 订单费用明细：同上（运费、操作费、道路通行费…）
- 退货费用明细：同上（退件运费、退件处理费…）
- 增值及附加服务费用明细：同上

归类规则（基于「费用明细」列的文本关键字，优先匹配更具体的关键字）：
- 仓租费/仓储费/超库龄 → storage
- 卸货费/入库操作费/入库处理费 → inbound
- 操作费/出库操作费/打包费/退件处理费/质检/理货 → outbound
- 运费/退件运费/道路通行费/燃油附加费/运输费 → transport
- 其余 → other
"""
from __future__ import annotations

import base64
import io
from decimal import Decimal

import openpyxl

# 费用明细页签（这些 sheet 有「费用明细」「本期费用小计」「币种」列）
FEE_SHEETS = (
    "入库费用明细",
    "仓租费用明细",
    "订单费用明细",
    "退货费用明细",
    "增值及附加服务费用明细",
)

# 归类关键字 → 五大类（按顺序匹配，先命中先生效）
CATEGORY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("仓租", "仓储", "超库龄"), "storage"),
    (("卸货", "入库操作", "入库处理", "入库费"), "inbound"),
    (("出库操作", "打包费", "退件处理", "质检", "理货", "操作费"), "outbound"),
    (("退件运费", "道路通行", "燃油附加", "运输费", "运费"), "transport"),
]


def classify_fee(name: str) -> str:
    """按费用明细文本归类到五大类。"""
    for kws, cat in CATEGORY_RULES:
        for kw in kws:
            if kw in name:
                return cat
    return "other"


def parse_billing_xlsx(b64: str) -> list[dict]:
    """解析 base64 xlsx，返回费用明细行列表。

    每行：{"fee_name": 费用明细, "fee_type": 费用类型, "amount": Decimal,
           "currency": 币种, "sheet": 来源页签}
    """
    raw = base64.b64decode(b64)
    # 注意：不能用 read_only=True，否则谷仓 xlsx 的表头行会被截断（列维度不完整）
    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    rows: list[dict] = []
    for sheet_name in FEE_SHEETS:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        header = None
        for r in ws.iter_rows(values_only=True):
            if header is None:
                header = r  # 第一行是表头
                # 定位关键列
                idx = {
                    "fee_type": _col(header, "费用类型"),
                    "fee_name": _col(header, "费用明细"),
                    "amount": _col(header, "本期费用小计"),
                    "currency": _col(header, "币种"),
                }
                continue
            if r is None or all(v is None for v in r):
                continue
            name = _cell(r, idx["fee_name"])
            if not name:
                continue
            amt = _cell(r, idx["amount"])
            if amt is None:
                continue
            try:
                amount = Decimal(str(amt))
            except Exception:  # noqa: BLE001
                continue
            if amount == 0:
                continue  # 跳过零金额行
            rows.append({
                "fee_name": str(name),
                "fee_type": _cell(r, idx["fee_type"]) or "",
                "amount": amount,
                "currency": _cell(r, idx["currency"]) or "EUR",
                "sheet": sheet_name,
            })
    wb.close()
    return rows


def _col(header, name: str) -> int:
    for i, h in enumerate(header):
        if h == name:
            return i
    return -1


def _cell(row, i: int):
    if i < 0 or i >= len(row):
        return None
    return row[i]
