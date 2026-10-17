"""Attachment parsing checks exercise real text, CSV, and selectable-text PDFs."""

from pathlib import Path
from decimal import Decimal

import pytest

from relay.parsers import ParseError, parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "invoices"


def write_file(tmp_path, text, name="attachment.txt"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def csv_file(tmp_path, rows, header="item_id,quantity,unit_price,currency"):
    return write_file(tmp_path, header + "\n" + rows, "attachment.csv")


def make_pdf(tmp_path, pages=("Invoice gateway-seat",), *, encrypted=False):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        if text:
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 20 250 Td ({text}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("not-a-real-secret")
    path = tmp_path / "attachment.pdf"
    writer.write(path)
    return path


@pytest.mark.parametrize("mime", ["text/plain", "text/markdown"])
def test_unicode_paragraphs_keep_exact_locations_and_bounded_chunks(tmp_path, mime):
    path = write_file(tmp_path, "日本語 café 🚀\n\n" + "x" * 4001)
    parsed = parse_file(path, mime)
    assert parsed.table is None
    assert [chunk.ordinal for chunk in parsed.chunks] == [1, 2, 3, 4]
    assert parsed.chunks[0].text == "日本語 café 🚀"
    assert [chunk.locator for chunk in parsed.chunks] == [
        {"paragraph": 1}, {"paragraph": 2}, {"paragraph": 2}, {"paragraph": 2}]
    assert "".join(chunk.text for chunk in parsed.chunks[1:]) == "x" * 4001
    assert all(len(chunk.text) <= 2000 for chunk in parsed.chunks)


@pytest.mark.parametrize("text", ["", " \n\t", "x" * 200001])
def test_text_rejects_empty_and_character_overflow(tmp_path, text):
    with pytest.raises(ParseError):
        parse_file(write_file(tmp_path, text), "text/plain")


def test_text_allows_exact_character_limit(tmp_path):
    parsed = parse_file(write_file(tmp_path, "x" * 200000), "text/plain")
    assert sum(len(chunk.text) for chunk in parsed.chunks) == 200000


def test_rejects_invalid_utf8_unsupported_mime_and_byte_overflow(tmp_path):
    path = tmp_path / "bad.bin"
    path.write_bytes(b"\xff")
    with pytest.raises(ParseError):
        parse_file(path, "text/plain")
    with pytest.raises(ParseError):
        parse_file(path, "application/octet-stream")
    path.write_bytes(b"x" * (10 * 1024 * 1024 + 1))
    with pytest.raises(ParseError):
        parse_file(path, "text/plain")


def test_csv_fixture_decimal_rows_and_source_locations():
    parsed = parse_file(FIXTURES / "invoice.csv", "text/csv")
    assert parsed.table.currency == "USD"
    row = parsed.table.rows[0]
    assert (row.item_id, row.quantity, row.unit_price, row.row_number) == (
        "gateway-seat", 2, Decimal("110.00"), 2)
    assert parsed.chunks[0].locator == {"row_start": 2, "row_end": 2}
    assert "110.00" in parsed.chunks[0].text


@pytest.mark.parametrize("rows", [
    "", "a,1,1.00,USD\na,2,2.00,USD", "a,1,1.00,USD\nb,1,1.00,EUR",
    "a,0,1.00,USD", "a,1000001,1.00,USD", "a,1.0,1.00,USD",
    "a,+1,1.00,USD", "a,1,NaN,USD", "a,1,Infinity,USD", "a,1,1e2,USD",
    "a,1,-1,USD", "a,1,1.001,USD", "a,1,1000000000.01,USD",
    "=SUM,1,1.00,USD", "+formula,1,1.00,USD", "@formula,1,1.00,USD",
    "../path,1,1.00,USD", "a,1,1.00,JPY", "a,1,1.00,usd",
    "a,1,1.00,USD,extra", "a,1,1.00", '"unterminated,1,1,USD',
    "x" * 4097 + ",1,1.00,USD",
])
def test_csv_rejects_ambiguous_or_unsafe_data(tmp_path, rows):
    with pytest.raises(ParseError):
        parse_file(csv_file(tmp_path, rows), "text/csv")


@pytest.mark.parametrize("header", [
    "item_id,quantity,unit_price,currency,currency", "item_id,quantity,unit_price",
    "item_id,item_id,unit_price,currency", "quantity,item_id,unit_price,currency",
    "item_id,quantity,unit_price,currency,extra",
])
def test_csv_requires_exact_unique_headers(tmp_path, header):
    with pytest.raises(ParseError):
        parse_file(csv_file(tmp_path, "a,1,1,USD", header), "text/csv")


def test_csv_row_and_numeric_limits(tmp_path):
    rows = "\n".join(f"item-{i},1000000,1000000000.00,INR" for i in range(2000))
    parsed = parse_file(csv_file(tmp_path, rows), "text/csv")
    assert len(parsed.table.rows) == 2000
    assert parsed.table.rows[-1].row_number == 2001
    with pytest.raises(ParseError):
        parse_file(csv_file(tmp_path, rows + "\nextra,1,1,INR"), "text/csv")


def test_pdf_extracts_selectable_text_with_page_locations(tmp_path):
    parsed = parse_file(make_pdf(tmp_path, ("Invoice", "Purchase order")), "application/pdf")
    assert [chunk.text for chunk in parsed.chunks] == ["Invoice", "Purchase order"]
    assert [chunk.locator for chunk in parsed.chunks] == [{"page": 1}, {"page": 2}]


@pytest.mark.parametrize("pages,encrypted", [((), False), (("",), False), (("",), True), (("secret",), True)])
def test_rejects_empty_scanned_or_encrypted_pdf(tmp_path, pages, encrypted):
    with pytest.raises(ParseError):
        parse_file(make_pdf(tmp_path, pages, encrypted=encrypted), "application/pdf")


def test_pdf_rejects_malformed_and_page_overflow(tmp_path):
    with pytest.raises(ParseError):
        parse_file(write_file(tmp_path, "%PDF-1.7 broken"), "application/pdf")
    with pytest.raises(ParseError):
        parse_file(make_pdf(tmp_path, ("invoice",) * 51), "application/pdf")


def test_pdf_character_limit_and_chunk_size(tmp_path):
    parsed = parse_file(make_pdf(tmp_path, ("a" * 4001,)), "application/pdf")
    assert [len(chunk.text) for chunk in parsed.chunks] == [2000, 2000, 1]
    assert all(chunk.locator == {"page": 1} for chunk in parsed.chunks)
    with pytest.raises(ParseError):
        parse_file(make_pdf(tmp_path, ("a" * 200001,)), "application/pdf")


def test_csv_allows_leading_zero_decimal_values_within_bounds(tmp_path):
    parsed = parse_file(csv_file(tmp_path, "a,000000001,000000000001.20,USD"), "text/csv")
    assert parsed.table.rows[0].quantity == 1
    assert parsed.table.rows[0].unit_price == Decimal("1.20")


def test_csv_rejects_formula_like_negative_prefix_identifier(tmp_path):
    with pytest.raises(ParseError):
        parse_file(csv_file(tmp_path, "-formula,1,1.00,USD"), "text/csv")


def test_pdf_allows_fifty_pages_and_retains_original_page_number(tmp_path):
    parsed = parse_file(make_pdf(tmp_path, ("",) * 49 + ("Last page",)), "application/pdf")
    assert parsed.chunks[0].locator == {"page": 50}
    assert parsed.chunks[0].text == "Last page"
