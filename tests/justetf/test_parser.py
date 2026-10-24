"""justETF profile page parser on synthetic HTML."""

from __future__ import annotations

from typing import Any

import pytest

from finance_mcp.justetf import parser
from tests.fakes import AJAX, FULL_PAGE, PAGE


def test_parse_profile_basic() -> None:
    """Header facts, holdings and the as-of date are parsed from a profile page."""
    p = parser.parse_profile(PAGE)
    assert p["isin"] == "IE00B4L5Y983" and p["ticker"] == "TWLD"
    assert p["ter_pct"] == 0.2
    assert p["fund_size"] == {"currency": "EUR", "amount_mn": 1500.0}
    assert p["number_of_holdings"] == 1252
    assert p["holdings"]["top_10"][0]["isin"] == "US0378331005"
    assert p["holdings"]["as_of"] == "31/08/2026"
    assert any("full countries" in w for w in p["warnings"])


def test_parse_profile_uses_full_lists_from_ajax() -> None:
    """The full country list from the AJAX fragment replaces the short one."""
    p = parser.parse_profile(PAGE, {"countries": AJAX})
    assert [c["name"] for c in p["holdings"]["countries"]] == [
        "United States",
        "Japan",
        "Other",
    ]
    assert not any("countries" in w for w in p["warnings"])


def test_parse_rejects_other_pages() -> None:
    """A page that is not an ETF profile raises ValueError."""
    with pytest.raises(ValueError):
        parser.parse_profile("<html>nope</html>")


def test_to_number() -> None:
    """Signed percentages and thousands separators parse; '-' is None."""
    assert parser.to_number("+16.97%") == 16.97
    assert parser.to_number("-6.47%") == -6.47
    assert parser.to_number("1,252") == 1252
    assert parser.to_number("-") is None


def test_parse_full_page_sections() -> None:
    """Panels, returns, risk, listings and similar ETFs are all parsed."""
    p = parser.parse_profile(FULL_PAGE)
    assert p["basics"]["index"] == "MSCI World"
    assert p["basics"]["volatility_1y_pct"] == 13.5
    assert p["legal_structure"] == {"fund_structure": "Company"}
    assert p["tax_status"] == {"Germany": "30% partial exemption"}
    perf = p["performance"]
    assert perf["currency"] == "EUR"
    assert perf["period_returns_pct"]["1y"] == 12.5
    assert perf["calendar_year_returns_pct"] == {"2025": -4.0}
    assert p["risk"] == {"max_drawdown_1_year": -8.2}
    assert p["listings"] == [
        {"mic_code": "XETR", "exchange": "XETRA", "trading_currency": "EUR",
         "ticker": "EUNL", "bloomberg": None, "reuters": None},
    ]  # fmt: skip
    assert [s["isin"] for s in p["similar_etfs"]] == ["IE00BFMXXD54"]
    assert p["similar_etfs"][0]["fund_size_mn"] == 2000
    assert [h["name"] for h in p["holdings"]["top_10"]] == ["Apple"]


def test_parse_shorter_fragment_keeps_page_list_and_warns() -> None:
    """A fragment with fewer rows than the page does not replace it."""
    empty = "<ajax-response><![CDATA[<table></table>]]></ajax-response>"
    p = parser.parse_profile(FULL_PAGE, {"sectors": empty})
    assert [s["name"] for s in p["holdings"]["sectors"]] == ["Technology"]
    assert any("full sectors" in w for w in p["warnings"])


def test_parse_missing_ter_and_size_warn() -> None:
    """Missing TER and fund size are reported as warnings."""
    html = (
        '<div data-testid="etf-profile-header_etf-name">X</div>'
        '<span data-testid="etf-profile-header_isin-value">IE00B4L5Y983</span>'
    )
    p = parser.parse_profile(html)
    assert p["ter_pct"] is None and p["fund_size"] is None
    assert "TER not found on the page" in p["warnings"]
    assert "fund size not found on the page" in p["warnings"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("EUR 132,896 m", {"currency": "EUR", "amount_mn": 132896.0}),
        ("USD 1.5 bn", {"currency": "USD", "amount_mn": 1500.0}),
        ("GBP 500 k", {"currency": "GBP", "amount_mn": 0.5}),
        ("no size", None),
        (None, None),
    ],
)
def test_parse_fund_size(text: str | None, expected: dict[str, Any] | None) -> None:
    """Fund sizes in m/bn/k are normalised to millions."""
    assert parser.parse_fund_size(text) == expected


def test_to_number_edge_cases() -> None:
    """Unicode minus is handled; text without digits gives None."""
    assert parser.to_number("−3.5%") == -3.5
    assert parser.to_number("n/a") is None
    assert parser.to_number(None) is None
