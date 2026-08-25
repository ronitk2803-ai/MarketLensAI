"""Pure holdings-file parsing for Zerodha and Upstox exports
(Build_plan.md's own flagged risk for this feature: "format variance").
No IO, no DB — bytes/text in, structured rows + per-row errors out, same
"engines are pure/no-IO" contract as app/engines/thesis/base.py's
evaluate_trigger.

Neither broker's exact export headers were verified against a real
downloaded file. Zerodha research converged on something like
`Instrument, Qty., Avg. cost, ...` from secondary sources; Upstox's own
API field names (`tradingsymbol`, `quantity`, `average_price`, read
directly from upstox/upstox-python's docs) are the best signal available
for its likely export vocabulary. Column resolution therefore matches by
normalized substring, not a literal header string, deliberately tolerant
of a UI wording change (or a guess that was simply wrong) breaking every
future import — and this same tolerance is why one alias list can cover
both brokers without per-broker special-casing.

Only symbol/quantity/avg_cost are extracted. P&L / current-value columns,
if present, are read by nobody: this app always recomputes those live
from its own stored price data (app/services/portfolio.py), never trusts
a file snapshot for them — the same "facts vs fabrication" discipline
FinancialMetric/CompanyAiSummary already follow elsewhere.
"""

import csv
import io
from dataclasses import dataclass, field

import openpyxl

_SYMBOL_HEADERS = ("tradingsymbol", "instrument", "symbol")
_QUANTITY_HEADERS = ("qty", "quantity")
_AVG_COST_TOKENS_A = ("avg", "average")
_AVG_COST_TOKENS_B = ("cost", "price")

# Broker "report" exports commonly carry a title / "generated on" /
# account-ID row (sometimes a merged cell, which just reads as blank in
# every column but the first) before the real header row — scanning
# instead of assuming row 0 is the header absorbs that without needing to
# know each broker's exact export layout.
_HEADER_SCAN_ROWS = 15


@dataclass(frozen=True, slots=True)
class ParsedHoldingRow:
    row_number: int  # 1-indexed relative to the data rows, header excluded
    symbol: str
    quantity: float
    avg_cost: float


@dataclass(frozen=True, slots=True)
class RowError:
    row_number: int
    reason: str


@dataclass(frozen=True, slots=True)
class ParsedHoldingsCsv:
    rows: list[ParsedHoldingRow] = field(default_factory=list)
    errors: list[RowError] = field(default_factory=list)


def _normalize_header(h: str) -> str:
    return h.strip().lower().replace(".", "").replace(" ", "")


def _resolve_columns(header_row: list[str]) -> tuple[str, str, str] | None:
    """Returns (symbol_col, qty_col, avg_cost_col) header text if this row
    resolves all three; None if it doesn't look like the header row."""
    normalized = {h: _normalize_header(h) for h in header_row if h.strip()}

    def find(candidates: tuple[str, ...]) -> str | None:
        return next((h for h, n in normalized.items() if any(c in n for c in candidates)), None)

    symbol_col = find(_SYMBOL_HEADERS)
    qty_col = find(_QUANTITY_HEADERS)
    avg_cost_col = next(
        (
            h
            for h, n in normalized.items()
            if any(a in n for a in _AVG_COST_TOKENS_A) and any(b in n for b in _AVG_COST_TOKENS_B)
        ),
        None,
    )
    if symbol_col is None or qty_col is None or avg_cost_col is None:
        return None
    return symbol_col, qty_col, avg_cost_col


def parse_holdings_rows(rows: list[list[str]]) -> ParsedHoldingsCsv:
    """Raises ValueError for structural failures (empty file, no header
    row found within the scan window) — those invalidate the whole file,
    not one row, so they're not folded into `errors`. Per-row problems
    (bad number, non-positive quantity/cost, empty symbol, duplicate
    symbol) become `RowError`s instead, so one bad line doesn't fail the
    whole import.
    """
    if not rows:
        raise ValueError("the file is empty")

    header_row_index: int | None = None
    columns: tuple[str, str, str] | None = None
    for i, row in enumerate(rows[:_HEADER_SCAN_ROWS]):
        resolved = _resolve_columns(row)
        if resolved is not None:
            header_row_index, columns = i, resolved
            break

    if header_row_index is None or columns is None:
        raise ValueError(
            "couldn't find a symbol, a quantity, an average cost column in the first "
            f"{min(_HEADER_SCAN_ROWS, len(rows))} rows — found headers: {rows[0]}"
        )

    header_row = rows[header_row_index]
    symbol_col, qty_col, avg_cost_col = columns
    symbol_idx = header_row.index(symbol_col)
    qty_idx = header_row.index(qty_col)
    avg_cost_idx = header_row.index(avg_cost_col)

    result_rows: list[ParsedHoldingRow] = []
    errors: list[RowError] = []
    seen_symbols: dict[str, int] = {}
    for i, record in enumerate(rows[header_row_index + 1 :], start=1):
        if not any(cell.strip() for cell in record):
            continue  # blank trailing line
        symbol = record[symbol_idx].strip().upper() if symbol_idx < len(record) else ""
        if not symbol:
            errors.append(RowError(i, "empty symbol"))
            continue
        if symbol in seen_symbols:
            errors.append(
                RowError(
                    i, f"duplicate symbol {symbol} (first seen at row {seen_symbols[symbol]})"
                )
            )
            continue
        try:
            quantity = float(record[qty_idx].strip().replace(",", ""))
            avg_cost = float(record[avg_cost_idx].strip().replace(",", ""))
        except (IndexError, ValueError):
            errors.append(RowError(i, "unparseable quantity or average cost"))
            continue
        if quantity <= 0 or avg_cost <= 0:
            errors.append(RowError(i, "quantity and average cost must be positive"))
            continue
        seen_symbols[symbol] = i
        result_rows.append(
            ParsedHoldingRow(row_number=i, symbol=symbol, quantity=quantity, avg_cost=avg_cost)
        )

    return ParsedHoldingsCsv(rows=result_rows, errors=errors)


def parse_holdings_csv(raw_csv: str) -> ParsedHoldingsCsv:
    rows = list(csv.reader(io.StringIO(raw_csv)))
    return parse_holdings_rows(rows)


def parse_holdings_xlsx(raw_bytes: bytes) -> ParsedHoldingsCsv:
    """read_only + data_only: this is a downloaded broker report, not a
    formula-heavy user-authored sheet, so resolving formulas to their
    last-calculated value (rather than the formula text or None) is the
    right mode. Tries the active sheet first, then every other sheet in
    the workbook — broker export tools don't always mark the holdings tab
    as "active", and a summary/disclaimer tab could easily be first."""
    try:
        wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
    except Exception as exc:
        raise ValueError("couldn't read this as an Excel file") from exc

    sheets = [wb.active, *[s for s in wb.worksheets if s is not wb.active]]
    last_error: ValueError | None = None
    for sheet in sheets:
        if sheet is None:
            continue
        rows = [
            ["" if cell is None else str(cell) for cell in row]
            for row in sheet.iter_rows(values_only=True)
        ]
        try:
            return parse_holdings_rows(rows)
        except ValueError as exc:
            last_error = exc
            continue

    raise last_error if last_error is not None else ValueError("the file is empty")


def parse_holdings_file(raw_bytes: bytes, filename: str) -> ParsedHoldingsCsv:
    """The one place that decides CSV vs Excel — both `app/services/
    portfolio.py` and the API layer go through this rather than each
    sniffing the filename themselves."""
    if filename.lower().endswith(".xlsx"):
        return parse_holdings_xlsx(raw_bytes)
    try:
        raw_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("couldn't read the file as UTF-8 text") from exc
    return parse_holdings_csv(raw_text)
