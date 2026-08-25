"""Pure Zerodha holdings-CSV parsing (Build_plan.md's own flagged risk for
this feature: "format variance"). No IO, no DB — text in, structured rows
+ per-row errors out, same "engines are pure/no-IO" contract as
app/engines/thesis/base.py's evaluate_trigger.

Zerodha's exact export headers were never verified against a real
downloaded file — research converged on something like `Instrument, Qty.,
Avg. cost, LTP, Cur. val, P&L, Net chg., Day chg.` from secondary sources
only. Column resolution therefore matches by normalized substring, not a
literal header string, deliberately tolerant of a UI wording change (or a
guess that was simply wrong) breaking every future import.

Only symbol/quantity/avg_cost are extracted. P&L / current-value columns,
if present, are read by nobody: this app always recomputes those live
from its own stored price data (app/services/portfolio.py), never trusts
a CSV snapshot for them — the same "facts vs fabrication" discipline
FinancialMetric/CompanyAiSummary already follow elsewhere.
"""

import csv
import io
from dataclasses import dataclass, field

_SYMBOL_HEADERS = ("tradingsymbol", "instrument", "symbol")
_QUANTITY_HEADERS = ("qty", "quantity")
_AVG_COST_TOKENS_A = ("avg", "average")
_AVG_COST_TOKENS_B = ("cost", "price")


@dataclass(frozen=True, slots=True)
class ParsedHoldingRow:
    row_number: int  # 1-indexed, header excluded — maps back to the user's spreadsheet
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


def parse_holdings_csv(raw_csv: str) -> ParsedHoldingsCsv:
    """Raises ValueError for structural failures (empty file, a required
    column that can't be resolved at all) — those invalidate the whole
    file, not one row, so they're not folded into `errors`. Per-row
    problems (bad number, empty symbol, duplicate symbol) become
    `RowError`s instead, so one bad line doesn't fail the whole import.
    """
    reader = csv.reader(io.StringIO(raw_csv))
    try:
        header_row = next(reader)
    except StopIteration as exc:
        raise ValueError("the file is empty") from exc

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

    missing = [
        name
        for name, col in (
            ("a symbol", symbol_col),
            ("a quantity", qty_col),
            ("an average cost", avg_cost_col),
        )
        if col is None
    ]
    if missing:
        raise ValueError(
            f"couldn't find {', '.join(missing)} column — found headers: {header_row}"
        )

    assert symbol_col is not None and qty_col is not None and avg_cost_col is not None
    symbol_idx = header_row.index(symbol_col)
    qty_idx = header_row.index(qty_col)
    avg_cost_idx = header_row.index(avg_cost_col)

    rows: list[ParsedHoldingRow] = []
    errors: list[RowError] = []
    seen_symbols: dict[str, int] = {}
    for i, record in enumerate(reader, start=1):
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
        seen_symbols[symbol] = i
        rows.append(
            ParsedHoldingRow(row_number=i, symbol=symbol, quantity=quantity, avg_cost=avg_cost)
        )

    return ParsedHoldingsCsv(rows=rows, errors=errors)
