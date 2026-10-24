"""Cross-source portfolio tools (Yahoo prices + justETF listings)."""

from __future__ import annotations

from typing import Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from ..justetf.client import JustEtfError
from ..yahoo.data import YahooError
from . import risk
from .resolve import resolve_isin
from .risk import Position

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)


def register(mcp: FastMCP) -> None:
    """Register the portfolio tools on the given server."""

    @mcp.tool(annotations=READ_ONLY)
    def resolve_instrument(isin: str, base_currency: str | None = None) -> dict:
        """ISIN -> Yahoo Finance tickers, best listing first.

        Use this to go from an ISIN (broker statement, KID, justETF) to a
        symbol for the Yahoo tools. ETFs are mapped from their exchange
        listings on justETF (XETRA -> .DE, Euronext Amsterdam -> .AS, London
        -> .L, SIX -> .SW, ...); other ISINs (e.g. single stocks) fall back to
        Yahoo search. Listings in `base_currency` rank first, then the most
        liquid exchanges. Venues Yahoo lacks (gettex, Tradegate) are listed
        under `unmapped_listings`. If the user holds a specific listing,
        use that one.

        Args:
            isin: 12-character ISIN, e.g. IE00B4L5Y983.
            base_currency: Optional ISO code to prefer listings trading in it.
        """
        try:
            return resolve_isin(isin, base_currency)
        except JustEtfError as exc:
            return {
                "error": str(exc),
                "error_code": risk._justetf_code(exc),
                "hint": "Find the ticker with search_symbol instead.",
            }

    @mcp.tool(annotations=READ_ONLY)
    def analyze_portfolio_risk(
        positions: list[Position],
        base_currency: str = "EUR",
        benchmark: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        interval: Literal["1d", "1wk", "1mo"] = "1wk",
        method: Literal["current_holdings", "constant_weights"] = "current_holdings",
        risk_free_rate_pct: float = 0.0,
    ) -> dict:
        """Risk and return of a whole portfolio, measured in one base currency.

        Positions can be stocks or ETFs, given by Yahoo symbol or ISIN, sized
        by quantity (shares) or current value (in base currency); with
        neither, positions are equally weighted. Prices are converted to the
        base currency with daily FX (pence-quoted London listings handled),
        put on a common calendar, and analysed.

        Returns: total value and weights; portfolio return, volatility,
        Sharpe/Sortino/Calmar, max drawdown (dates); vs `benchmark` beta,
        alpha, tracking error, information ratio; per position return,
        volatility, beta and share of portfolio risk; correlation matrix;
        diversification ratio; how ISINs were resolved; FX rates used;
        warnings (short histories, stale quotes, bad Yahoo prices removed).
        Use analyze_portfolio (justETF) for cost and country/sector/stock
        look-through of ETFs.

        Example positions: [{"isin": "IE00B4L5Y983", "value": 30000},
        {"symbol": "ASML.AS", "quantity": 10}, {"symbol": "AAPL", "quantity": 25}]

        Args:
            positions: Up to 30 holdings: {symbol | isin, quantity | value}.
            base_currency: ISO code of the investor's currency. Default EUR.
            benchmark: Optional Yahoo symbol, e.g. "IWDA.AS" or "^GSPC".
            start_date: YYYY-MM-DD. Defaults to 3 years before end_date.
            end_date: YYYY-MM-DD (exclusive). Defaults to the latest data.
            interval: Return frequency. Default "1wk": daily returns across
                regions (US vs Europe) understate correlation and beta because
                the markets close hours apart.
            method: "current_holdings" (today's units held throughout) or
                "constant_weights" (rebalanced to today's weights each period).
            risk_free_rate_pct: Annual risk-free rate in %, e.g. 2.0.
        """
        try:
            return risk.analyze_portfolio_risk(
                positions,
                base_currency=base_currency,
                benchmark=benchmark,
                start_date=start_date,
                end_date=end_date,
                interval=interval,
                method=method,
                risk_free_rate_pct=risk_free_rate_pct,
            )
        except YahooError as exc:
            return exc.to_dict()
