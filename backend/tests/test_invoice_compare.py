"""Money is calculated from validated rows with decimal arithmetic, without a model."""

from decimal import Decimal, localcontext
from pathlib import Path

import pytest

from relay.invoice_compare import compare_invoice
from relay.parsers import ParsedRow, ParsedTable, parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "invoices"


def table(*rows, currency="USD"):
    return ParsedTable(currency=currency, rows=[
        ParsedRow(item_id=item, quantity=quantity, unit_price=Decimal(price), row_number=i + 2)
        for i, (item, quantity, price) in enumerate(rows)])


def test_approved_fixture_has_exact_totals_and_one_row_cited_mismatch():
    invoice = parse_file(FIXTURES / "invoice.csv", "text/csv").table
    order = parse_file(FIXTURES / "purchase-order.csv", "text/csv").table
    result = compare_invoice(invoice, order)
    assert (result.currency, result.invoice_total, result.order_total, result.difference) == (
        "USD", "220.00", "200.00", "20.00")
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert (finding.item_id, finding.kind, finding.invoice_row, finding.order_row) == (
        "gateway-seat", "unit_price_mismatch", 2, 2)
    assert (finding.expected, finding.actual) == ("100.00", "110.00")


def test_matching_items_are_joined_by_id_and_create_no_findings():
    invoice = table(("b", 1, "0.20"), ("a", 3, "0.10"))
    order = table(("a", 3, "0.10"), ("b", 1, "0.20"))
    result = compare_invoice(invoice, order)
    assert result.findings == []
    assert (result.invoice_total, result.difference) == ("0.50", "0.00")


def test_quantity_missing_and_extra_items_keep_each_original_row():
    result = compare_invoice(
        table(("common", 3, "10"), ("extra", 1, "2")),
        table(("missing", 1, "3"), ("common", 2, "10")))
    assert [(f.kind, f.item_id, f.invoice_row, f.order_row) for f in result.findings] == [
        ("quantity_mismatch", "common", 2, 3),
        ("missing_in_order", "extra", 3, None),
        ("missing_in_invoice", "missing", None, 2)]
    assert (result.invoice_total, result.order_total, result.difference) == ("32.00", "23.00", "9.00")
    assert (result.findings[0].expected, result.findings[0].actual) == ("2", "3")


def test_totals_remain_exact_under_low_ambient_decimal_precision():
    invoice = table(*[(f"item-{i}", 1000000, "999999999.99") for i in range(2000)])
    with localcontext() as context:
        context.prec = 6
        result = compare_invoice(invoice, invoice)
    assert result.invoice_total == "1999999999980000000.00"
    assert result.difference == "0.00"


def test_negative_difference_is_exact():
    result = compare_invoice(table(("a", 1, "0.10")), table(("a", 1, "0.30")))
    assert result.difference == "-0.20"


@pytest.mark.parametrize("invoice,order", [
    (table(("a", 1, "1")), table(("a", 1, "1"), currency="EUR")),
    (table(("a", 1, "1"), ("a", 1, "1")), table(("a", 1, "1"))),
    (table(("a", 1, "NaN")), table(("a", 1, "1"))),
    (table(("a", 0, "1")), table(("a", 1, "1"))),
    (table(("a", 1, "1.001")), table(("a", 1, "1"))),
])
def test_compare_rejects_invalid_tables_instead_of_guessing(invoice, order):
    with pytest.raises(ValueError):
        compare_invoice(invoice, order)
