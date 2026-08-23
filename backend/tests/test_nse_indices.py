import pytest

from app.providers.errors import ProviderError
from app.providers.india.nse_indices import (
    IndexConstituent,
    parse_index_constituents,
)

# Header and rows copied verbatim from the live ind_nifty500list.csv
# (fetched 2026-08-24) so the parser is pinned against the real format,
# including the space in "ISIN Code".
REAL_CSV = """Company Name,Industry,Symbol,Series,ISIN Code
360 ONE WAM Ltd.,Financial Services,360ONE,EQ,INE466L01038
3M India Ltd.,Diversified,3MINDIA,EQ,INE470A01017
ABB India Ltd.,Capital Goods,ABB,EQ,INE117A01022
ACC Ltd.,Construction Materials,ACC,EQ,INE012A01025
"""


def test_parse_index_constituents_reads_the_live_format() -> None:
    constituents = parse_index_constituents(REAL_CSV)

    assert len(constituents) == 4
    assert constituents[0] == IndexConstituent(
        symbol="360ONE",
        name="360 ONE WAM Ltd.",
        industry="Financial Services",
        isin="INE466L01038",
        series="EQ",
    )
    assert [c.symbol for c in constituents] == ["360ONE", "3MINDIA", "ABB", "ACC"]


def test_parse_index_constituents_skips_non_equity_series() -> None:
    csv_text = REAL_CSV + "Some Gilt,Financial Services,GILT01,GS,INE000000001\n"

    constituents = parse_index_constituents(csv_text)

    assert "GILT01" not in {c.symbol for c in constituents}


def test_parse_index_constituents_rejects_an_empty_result() -> None:
    # A silently-empty universe would deactivate every asset on reconcile,
    # so an unrecognised or truncated CSV must fail loudly instead.
    with pytest.raises(ProviderError):
        parse_index_constituents("Company Name,Industry,Symbol,Series,ISIN Code\n")


def test_to_asset_ref_carries_isin() -> None:
    ref = parse_index_constituents(REAL_CSV)[0].to_asset_ref()

    assert ref.symbol == "360ONE"
    assert ref.exchange == "NSE"
    assert ref.market == "IN"
    assert ref.isin == "INE466L01038"
