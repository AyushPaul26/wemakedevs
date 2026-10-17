"""Deterministic invoice comparison; monetary result fields are decimal strings."""

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext

from relay.parsers import CURRENCIES, MAX_CSV_ROWS, ParsedTable


@dataclass(frozen=True)
class ComparisonFinding:
    item_id: str
    kind: str
    invoice_row: int | None = None
    order_row: int | None = None
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class ComparisonResult:
    currency: str
    invoice_total: str
    order_total: str
    difference: str
    findings: list[ComparisonFinding]


def _validate(table: ParsedTable) -> None:
    if table.currency not in CURRENCIES or not 1 <= len(table.rows) <= MAX_CSV_ROWS:
        raise ValueError("Comparison requires nonempty validated tables and supported currency.")
    seen: set[str] = set()
    for row in table.rows:
        if (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", row.item_id)
                or row.item_id.startswith("-") or row.item_id in seen):
            raise ValueError("Comparison requires unique valid item IDs.")
        seen.add(row.item_id)
        if type(row.quantity) is not int or not 1 <= row.quantity <= 1_000_000:
            raise ValueError("Comparison quantity is invalid.")
        price = row.unit_price
        if (not isinstance(price, Decimal) or not price.is_finite() or price < 0
                or price > Decimal("1000000000") or price.as_tuple().exponent < -2):
            raise ValueError("Comparison unit price is invalid.")
        if type(row.row_number) is not int or row.row_number < 2:
            raise ValueError("Comparison requires original CSV row numbers.")


def compare_invoice(invoice: ParsedTable, order: ParsedTable) -> ComparisonResult:
    """Compare by item ID without inferring schemas, converting money, or using a model.

    Expected values come from the order; actual values come from the invoice.
    Findings follow invoice order, then order-only items in their original order.
    Each field mismatch is explicit; totals alone cannot hide offsetting changes.
    Invalid tables or conflicting currencies raise ``ValueError``.
    """
    _validate(invoice)
    _validate(order)
    if invoice.currency != order.currency:
        raise ValueError("Invoice and purchase order currencies must agree.")
    order_by_id = {row.item_id: row for row in order.rows}
    invoice_ids = {row.item_id for row in invoice.rows}
    findings: list[ComparisonFinding] = []
    # Maximum valid total is 2e18; 40 digits safely covers cents and subtraction,
    # independent of a caller's ambient decimal precision.
    with localcontext() as context:
        context.prec = 40
        for row in invoice.rows:
            expected = order_by_id.get(row.item_id)
            if expected is None:
                findings.append(ComparisonFinding(row.item_id, "missing_in_order", row.row_number))
                continue
            if row.quantity != expected.quantity:
                findings.append(ComparisonFinding(
                    row.item_id, "quantity_mismatch", row.row_number, expected.row_number,
                    str(expected.quantity), str(row.quantity)))
            if row.unit_price != expected.unit_price:
                findings.append(ComparisonFinding(
                    row.item_id, "unit_price_mismatch", row.row_number, expected.row_number,
                    f"{expected.unit_price:.2f}", f"{row.unit_price:.2f}"))
        for row in order.rows:
            if row.item_id not in invoice_ids:
                findings.append(ComparisonFinding(
                    row.item_id, "missing_in_invoice", order_row=row.row_number))
        invoice_total = sum((row.unit_price * row.quantity for row in invoice.rows), Decimal(0))
        order_total = sum((row.unit_price * row.quantity for row in order.rows), Decimal(0))
        return ComparisonResult(invoice.currency, f"{invoice_total:.2f}", f"{order_total:.2f}",
                                f"{invoice_total - order_total:.2f}", findings)
