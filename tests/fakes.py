"""Shared offline test data: a synthetic market and synthetic justETF pages."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
import pandas as pd

from finance_mcp import server

DATES = pd.bdate_range("2023-01-02", "2026-10-23")


def walk(seed: int, start: float = 100.0, vol: float = 0.01) -> np.ndarray:
    """Build a reproducible random-walk price path over ``DATES``.

    Args:
        seed: Random generator seed.
        start: First price level.
        vol: Daily return standard deviation.

    Returns:
        One price per business day in ``DATES``.
    """
    rng = np.random.default_rng(seed)
    return start * np.cumprod(1 + rng.normal(0.0003, vol, len(DATES)))


# local-currency prices as Yahoo would return them
PRICES = {
    "AAPL": walk(1, 150),  # USD
    "VUSA.L": walk(2, 8000),  # GBp (pence)
    "EUNL.DE": walk(3, 80),  # EUR
    "IWDA.AS": walk(3, 80),  # EUR, same fund as EUNL.DE
    "SPY": walk(4, 400),  # USD, benchmark
}
CURRENCIES = {"AAPL": "USD", "VUSA.L": "GBp", "EUNL.DE": "EUR", "IWDA.AS": "EUR",
              "SPY": "USD"}  # fmt: skip
FX = {"USD": 0.9, "GBP": 1.2}  # EUR per unit, constant to make values checkable

ISIN = "IE00B4L5Y983"  # iShares Core MSCI World (a real, valid ISIN)

# Minimal profile page mirroring justETF's data-testid markup, made-up numbers.
PAGE = """
<div data-testid="etf-profile-header_etf-name">Test World ETF (Acc)</div>
<span data-testid="etf-profile-header_isin-value">IE00B4L5Y983</span>
<span data-testid="etf-profile-header_identifier-value-ticker">TWLD</span>
<span data-testid="etf-profile-header_ter-value">0.20% p.a.</span>
<div data-testid="etf-profile-header_fund-size-value-wrapper"><span> EUR 1,500 </span> m</div>
<div data-testid="etf-profile-header_holdings-value">1,252</div>
<div data-testid="etf-profile-header_distribution-policy-value">Accumulating</div>
<div data-testid="tl_etf-basics_value_domicile-country">Ireland</div>
<table><tbody>
<tr data-testid="etf-holdings_countries_row">
 <td data-testid="tl_etf-holdings_countries_value_name">United States</td>
 <td><span data-testid="tl_etf-holdings_countries_value_percentage">70.00%</span></td></tr>
<tr data-testid="etf-holdings_countries_row">
 <td data-testid="tl_etf-holdings_countries_value_name">Other</td>
 <td><span data-testid="tl_etf-holdings_countries_value_percentage">30.00%</span></td></tr>
</tbody></table>
<table><tbody><tr data-testid="etf-holdings_top-holdings_row">
 <td><a data-testid="tl_etf-holdings_top-holdings_link_name" href="/en/stock-profiles/US0378331005"><span>Apple</span></a></td>
 <td><span data-testid="tl_etf-holdings_top-holdings_value_percentage">5.00%</span></td></tr></tbody></table>
<div data-testid="tl_etf-holdings_reference-date">As of 31/08/2026</div>
"""

# Every section the parser reads: panels, returns, risk, listings, similar ETFs.
FULL_PAGE = (
    PAGE
    + """
<div data-testid="tl_etf-basics_value_index-name">MSCI World</div>
<div data-testid="tl_etf-basics_value_fund-currency">USD</div>
<div data-testid="tl_etf-basics_value_currency-hedge">Unhedged</div>
<div data-testid="tl_etf-basics_value_volatility">13.50%</div>
<div data-testid="etf-profile-header_replication-value">Physical</div>
<table><tr data-testid="etf-holdings_sectors_row">
 <td data-testid="tl_etf-holdings_sectors_value_name">Technology</td>
 <td><span data-testid="tl_etf-holdings_sectors_value_percentage">25.00%</span></td></tr></table>
<table><tr data-testid="etf-holdings_top-holdings_row">
 <td><a data-testid="tl_etf-holdings_top-holdings_link_name" href="/x"><span>No weight</span></a></td>
 <td><span data-testid="tl_etf-holdings_top-holdings_value_percentage">-</span></td></tr></table>
<div id="collapse-legal"><table>
 <tr><td class="vallabel">Fund Structure</td><td>Company</td></tr>
 <tr><td>no label class</td><td>ignored</td></tr></table></div>
<div id="collapse-tax"><table>
 <tr><td>Germany</td><td>30% partial exemption</td></tr>
 <tr><td>-</td><td></td></tr></table></div>
<span data-testid="etf-returns-section_1year-return">+12.50%</span>
<span data-testid="etf-returns-section_3year-return">+30.00%</span>
<span data-testid="etf-returns-section_year-title-1">2025</span>
<span data-testid="etf-returns-section_year-return-1">-4.00%</span>
<select data-testid="etf-returns-section_currencies-select">
 <option>USD</option><option selected>EUR</option></select>
<table data-testid="etf-risk_table_panel">
 <tr><td class="vallabel">Max. drawdown 1 year</td><td>-8.20%</td></tr></table>
<table>
 <tr data-testid="etf-trade-data-panel_row-xetr">
  <td data-testid="etf-trade-data-panel_row-xetr_listing">XETRA</td>
  <td data-testid="etf-trade-data-panel_row-xetr_trade-currency">EUR</td>
  <td data-testid="etf-trade-data-panel_row-xetr_ticker">EUNL</td></tr>
 <tr data-testid="etf-trade-data-panel_row-xetr_extra"></tr></table>
<table>
 <tr data-testid="etf-further-info-en_related-etf-row-IE00BFMXXD54">
  <td>Other World</td><td>2,000</td><td>0.12%</td><td>Accumulating</td><td>Physical</td></tr>
 <tr data-testid="etf-further-info-en_related-etf-row-IE00B3XXRP09"><td>Too short</td></tr>
</table>
"""
)

AJAX = """<ajax-response><component id="t"><![CDATA[<table>
<tr data-testid="etf-holdings_countries_row"><td data-testid="tl_etf-holdings_countries_value_name">United States</td>
<td><span data-testid="tl_etf-holdings_countries_value_percentage">70.00%</span></td></tr>
<tr data-testid="etf-holdings_countries_row"><td data-testid="tl_etf-holdings_countries_value_name">Japan</td>
<td><span data-testid="tl_etf-holdings_countries_value_percentage">10.00%</span></td></tr>
<tr data-testid="etf-holdings_countries_row"><td data-testid="tl_etf-holdings_countries_value_name">Other</td>
<td><span data-testid="tl_etf-holdings_countries_value_percentage">20.00%</span></td></tr>
</table>]]></component></ajax-response>"""


def make(
    isin: str,
    ter: float | None,
    size: float | None,
    countries: list[tuple[str, float]],
    sectors: list[tuple[str, float]],
    top: list[tuple[str, float]],
    **extra: Any,
) -> dict[str, Any]:
    """Build a parsed-profile dict shaped like ``parser.parse_profile`` output.

    Args:
        isin: ISIN (also used as the name).
        ter: TER in % p.a., or None if unknown.
        size: Fund size in EUR millions, or None if unknown.
        countries: ``(name, weight_pct)`` country rows.
        sectors: ``(name, weight_pct)`` sector rows.
        top: ``(name, weight_pct)`` top-holding rows.
        **extra: Extra top-level keys to add or override.

    Returns:
        A profile dict.
    """
    return {
        "isin": isin,
        "name": isin,
        "ter_pct": ter,
        "fund_size": {"currency": "EUR", "amount_mn": size} if size else None,
        "distribution_policy": "Accumulating",
        "replication": "Physical",
        "inception_date": "25 September 2009",
        "number_of_holdings": 1000,
        "basics": {
            "domicile_country": "Ireland",
            "fund_currency": "USD",
            "currency_risk": "unhedged",
            "fund_provider": "X",
            "index": "I",
            "volatility_1y_pct": 12.0,
        },
        "holdings": {
            "countries": [{"name": n, "weight_pct": w} for n, w in countries],
            "sectors": [{"name": n, "weight_pct": w} for n, w in sectors],
            "top_10": [{"name": n, "isin": n, "weight_pct": w} for n, w in top],
            "top_10_weight_pct": sum(w for _, w in top),
            "as_of": "31/08/2026",
        },
        "performance": {"period_returns_pct": {"1y": 10.0, "3y": 25.0}},
        "risk": {"max_drawdown_1_year": -8.0},
        "listings": [{"ticker": "EUNL", "mic_code": "XETR"}],
        "similar_etfs": [],
        "warnings": [],
        "from_cache": False,
        **extra,
    }


def tool(name: str) -> Callable[..., Any]:
    """Return the Python function behind a registered MCP tool.

    Args:
        name: Tool name.

    Returns:
        The undecorated tool function.
    """
    registered = server.mcp._tool_manager.get_tool(name)
    assert registered is not None, name
    return registered.fn


FAST_INFO = {
    "AAPL": {"lastPrice": 110.0, "previousClose": 100.0, "currency": "USD",
             "exchange": "NMS", "timezone": "America/New_York"},
    "VUSA.L": {"lastPrice": 8000.0, "previousClose": 0.0, "currency": "GBp",
               "exchange": "LSE", "timezone": "Europe/London"},
}  # fmt: skip


INFO = {"AAPL": {"symbol": "AAPL", "longName": "Apple Inc.", "currency": "USD",
                 "sector": None}}  # fmt: skip


DIVIDENDS = pd.Series(
    [0.25, 0.25, 0.26],
    index=pd.DatetimeIndex(
        ["2025-02-10", "2025-11-10", "2026-02-10"], tz="America/New_York"
    ),
)


class FakeFunds:
    """Stand-in for ``Ticker.funds_data``."""

    sector_weightings = {"technology": 0.3, "healthcare": 0.1}
    top_holdings = pd.DataFrame(
        {"Name": ["Apple", "Microsoft"], "Holding Percent": [0.07, 0.065]},
        index=pd.Index(["AAPL", "MSFT"], name="Symbol"),
    )


class EmptyFunds:
    """Fund data of a symbol that is not a fund."""

    sector_weightings: dict[str, float] = {}
    top_holdings = pd.DataFrame()


class FakeTicker:
    """Stand-in for ``yf.Ticker``: known symbols answer, others raise."""

    def __init__(self, symbol: str) -> None:
        """Remember the symbol.

        Args:
            symbol: Yahoo symbol.
        """
        self.symbol = symbol

    @property
    def fast_info(self) -> dict[str, Any]:
        """Quote fields; unknown symbols raise KeyError like yfinance.

        Returns:
            The fast_info mapping.
        """
        return FAST_INFO[self.symbol]

    @property
    def info(self) -> dict[str, Any]:
        """Profile fields; unknown symbols give an empty dict.

        Returns:
            The info mapping.

        Raises:
            RuntimeError: For the symbol "BOOM".
        """
        if self.symbol == "BOOM":
            raise RuntimeError("boom")
        return INFO.get(self.symbol, {})

    @property
    def funds_data(self) -> FakeFunds | EmptyFunds:
        """Fund composition for SPY, empty data for AAPL.

        Returns:
            The fund data object.

        Raises:
            RuntimeError: For other symbols.
        """
        if self.symbol == "SPY":
            return FakeFunds()
        if self.symbol == "AAPL":
            return EmptyFunds()
        raise RuntimeError("not a fund")

    @property
    def dividends(self) -> pd.Series:
        """Dividend history for AAPL only.

        Returns:
            The dividend series (empty for other symbols).

        Raises:
            RuntimeError: For the symbol "BOOM".
        """
        if self.symbol == "BOOM":
            raise RuntimeError("boom")
        return DIVIDENDS if self.symbol == "AAPL" else pd.Series(dtype=float)
