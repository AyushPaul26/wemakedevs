"""Pure, bounded parsing; the caller owns authorization and subprocess isolation.

This module never writes files, contacts providers, or accesses a database. Run
``parse_file`` in the source service's one resource-limited worker with a
30-second wall timeout: parser-level limits alone cannot bound PDF decompression.
"""

import csv
import io
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_CHARACTERS = 200_000
MAX_PDF_PAGES = 50
MAX_CSV_ROWS = 2_000
MAX_CELL_CHARACTERS = 4_096
MAX_CHUNK_CHARACTERS = 2_000
CSV_HEADERS = ["item_id", "quantity", "unit_price", "currency"]
CURRENCIES = frozenset({"USD", "INR", "EUR", "GBP"})
_ITEM_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")
_QUANTITY = re.compile(r"[0-9]+\Z")
_PRICE = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?\Z")


class ParseError(ValueError):
    """Attachment content is unsupported, invalid, empty, or exceeds a limit."""


@dataclass(frozen=True)
class ParsedChunk:
    ordinal: int
    text: str
    locator: dict[str, int]


@dataclass(frozen=True)
class ParsedRow:
    item_id: str
    quantity: int
    unit_price: Decimal
    row_number: int


@dataclass(frozen=True)
class ParsedTable:
    currency: str
    rows: list[ParsedRow]


@dataclass(frozen=True)
class ParsedDocument:
    chunks: list[ParsedChunk]
    table: ParsedTable | None = None


def _append_chunks(chunks: list[ParsedChunk], text: str, locator: dict[str, int]) -> None:
    for offset in range(0, len(text), MAX_CHUNK_CHARACTERS):
        chunks.append(ParsedChunk(len(chunks) + 1, text[offset:offset + MAX_CHUNK_CHARACTERS],
                                  dict(locator)))


def _decode(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ParseError("Text attachments must use UTF-8.") from exc
    if len(text) > MAX_CHARACTERS:
        raise ParseError("Attachment exceeds 200,000 characters.")
    if not text.strip():
        raise ParseError("Attachment contains no text.")
    return text


def _parse_text(text: str) -> ParsedDocument:
    chunks: list[ParsedChunk] = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = re.split(r"\n[ \t]*\n+", text.strip())
    for number, paragraph in enumerate(paragraphs, start=1):
        _append_chunks(chunks, paragraph, {"paragraph": number})
    return ParsedDocument(chunks)


def _parse_csv(text: str) -> ParsedDocument:
    chunks: list[ParsedChunk] = []
    rows: list[ParsedRow] = []
    seen: set[str] = set()
    currency: str | None = None
    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        if next(reader, None) != CSV_HEADERS:
            raise ParseError("CSV headers must be item_id,quantity,unit_price,currency.")
        for cells in reader:
            if len(rows) >= MAX_CSV_ROWS:
                raise ParseError("CSV exceeds 2,000 data rows.")
            if len(cells) != 4 or any(len(cell) > MAX_CELL_CHARACTERS for cell in cells):
                raise ParseError("CSV rows require four cells of at most 4,096 characters.")
            item_id, quantity_text, price_text, row_currency = cells
            if (not _ITEM_ID.fullmatch(item_id) or item_id.startswith("-")
                    or item_id in seen):
                raise ParseError("CSV item IDs must be valid and unique.")
            if not _QUANTITY.fullmatch(quantity_text) or not 1 <= int(quantity_text) <= 1_000_000:
                raise ParseError("CSV quantity must be an integer from 1 to 1,000,000.")
            if not _PRICE.fullmatch(price_text) or Decimal(price_text) > Decimal("1000000000"):
                raise ParseError("CSV unit price must be a nonnegative decimal with at most two places.")
            if row_currency not in CURRENCIES or currency not in (None, row_currency):
                raise ParseError("CSV requires one supported currency for all rows.")
            currency = row_currency
            seen.add(item_id)
            row_number = reader.line_num
            rows.append(ParsedRow(item_id, int(quantity_text), Decimal(price_text), row_number))
            # Valid cells contain no commas or newlines, so this preserves the source record.
            _append_chunks(chunks, ",".join(cells),
                           {"row_start": row_number, "row_end": row_number})
    except csv.Error as exc:
        raise ParseError("CSV content is malformed.") from exc
    if not rows or currency is None:
        raise ParseError("CSV contains no data rows.")
    return ParsedDocument(chunks, ParsedTable(currency, rows))


def _parse_pdf(data: bytes) -> ParsedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise ParseError("PDF parsing is unavailable.") from exc
    chunks: list[ParsedChunk] = []
    try:
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            raise ParseError("Encrypted PDFs are unsupported.")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise ParseError("PDF must contain 1 to 50 pages.")
        characters = 0
        for number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""
            characters += len(text)
            if characters > MAX_CHARACTERS:
                raise ParseError("PDF exceeds 200,000 extracted characters.")
            text = text.strip()
            if text:
                _append_chunks(chunks, text, {"page": number})
    except ParseError:
        raise
    except Exception as exc:
        # PDF libraries expose many malformed-input exception types. Do not leak
        # paths, parser internals, or supplied text to the API boundary.
        raise ParseError("PDF content is malformed or cannot be extracted.") from exc
    if not chunks:
        raise ParseError("PDF contains no selectable text; scanned-only PDFs are unsupported.")
    return ParsedDocument(chunks)


def parse_file(path: Path, mime: str) -> ParsedDocument:
    """Parse one private attachment; all chunk ordinals and locators are 1-based.

    Raises ``ParseError`` for invalid/unsupported content, limits, or unavailable
    PDF support. File-system errors propagate for the source service to handle.
    Text passages retain paragraph identity; PDF passages retain page identity;
    CSV records retain physical source row numbers, including the header row.
    """
    if mime not in {"application/pdf", "text/plain", "text/markdown", "text/csv"}:
        raise ParseError("Unsupported attachment type.")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ParseError("Attachment exceeds 10 MiB.")
    if mime == "application/pdf":
        return _parse_pdf(data)
    text = _decode(data)
    return _parse_csv(text) if mime == "text/csv" else _parse_text(text)
