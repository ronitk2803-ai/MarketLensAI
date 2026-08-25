import pytest

from app.engines.csv_import import parse_holdings_csv

_STANDARD_HEADER = "Instrument,Qty.,Avg. cost,LTP,Cur. val,P&L,Net chg.,Day chg."


def test_standard_zerodha_headers_parse() -> None:
    csv_text = _STANDARD_HEADER + "\nTCS,10,3500.50,3600,36000,995,2.8,0.5\n"
    result = parse_holdings_csv(csv_text)
    assert result.errors == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert row.symbol == "TCS"
    assert row.quantity == 10
    assert row.avg_cost == 3500.50


def test_alternate_header_names_resolve() -> None:
    csv_text = "Tradingsymbol,Quantity,Average Price\nINFY,5,1500\n"
    result = parse_holdings_csv(csv_text)
    assert result.errors == []
    assert result.rows[0].symbol == "INFY"
    assert result.rows[0].quantity == 5
    assert result.rows[0].avg_cost == 1500


def test_header_matching_is_case_and_whitespace_tolerant() -> None:
    csv_text = "  INSTRUMENT  , QTY , AVG COST \nHDFC,1,100\n"
    result = parse_holdings_csv(csv_text)
    assert result.errors == []
    assert result.rows[0].symbol == "HDFC"


def test_empty_file_raises_value_error() -> None:
    with pytest.raises(ValueError, match="empty"):
        parse_holdings_csv("")


def test_missing_quantity_column_raises_and_names_it() -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_holdings_csv("Instrument,Avg. cost\nTCS,100\n")
    assert "a quantity" in str(exc_info.value)


def test_missing_all_required_columns_names_all_of_them() -> None:
    with pytest.raises(ValueError) as exc_info:
        parse_holdings_csv("Foo,Bar\n1,2\n")
    message = str(exc_info.value)
    assert "a symbol" in message
    assert "a quantity" in message
    assert "an average cost" in message
    assert "Foo" in message and "Bar" in message  # found headers echoed back


def test_unparseable_number_becomes_row_error_not_a_crash() -> None:
    csv_text = (
        _STANDARD_HEADER
        + "\nTCS,not-a-number,3500,3600,36000,0,0,0\nINFY,5,1500,1600,8000,500,0,0\n"
    )
    result = parse_holdings_csv(csv_text)
    assert len(result.rows) == 1
    assert result.rows[0].symbol == "INFY"
    assert len(result.errors) == 1
    assert result.errors[0].row_number == 1
    assert "unparseable" in result.errors[0].reason


def test_blank_trailing_row_is_silently_skipped() -> None:
    csv_text = _STANDARD_HEADER + "\nTCS,10,3500,3600,36000,995,0,0\n,,,,,,,\n"
    result = parse_holdings_csv(csv_text)
    assert len(result.rows) == 1
    assert result.errors == []


def test_empty_symbol_cell_becomes_row_error() -> None:
    csv_text = _STANDARD_HEADER + "\n,10,3500,3600,36000,995,0,0\n"
    result = parse_holdings_csv(csv_text)
    assert result.rows == []
    assert len(result.errors) == 1
    assert "empty symbol" in result.errors[0].reason


def test_duplicate_symbol_keeps_first_errors_second() -> None:
    csv_text = (
        _STANDARD_HEADER
        + "\nTCS,10,3500,3600,36000,995,0,0\nTCS,20,3600,3600,72000,0,0,0\n"
    )
    result = parse_holdings_csv(csv_text)
    assert len(result.rows) == 1
    assert result.rows[0].quantity == 10
    assert len(result.errors) == 1
    assert "duplicate symbol TCS" in result.errors[0].reason
    assert "row 1" in result.errors[0].reason


def test_comma_thousands_separators_parse() -> None:
    csv_text = _STANDARD_HEADER + '\nTCS,"1,234.5","3,500.75",0,0,0,0,0\n'
    result = parse_holdings_csv(csv_text)
    assert result.errors == []
    assert result.rows[0].quantity == 1234.5
    assert result.rows[0].avg_cost == 3500.75


def test_pnl_and_current_value_columns_are_never_consulted() -> None:
    # Even if P&L/Cur.val are wildly wrong or non-numeric garbage, parsing
    # must still succeed — those columns are read by nobody.
    csv_text = "Instrument,Qty.,Avg. cost,P&L,Cur. val\nTCS,10,3500,garbage,also garbage\n"
    result = parse_holdings_csv(csv_text)
    assert result.errors == []
    assert result.rows[0].symbol == "TCS"
