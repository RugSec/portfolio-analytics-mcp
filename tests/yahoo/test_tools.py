"""Yahoo MCP tools (yfinance and downloads faked)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest
import yfinance as yf

from finance_mcp.yahoo import data
from finance_mcp.yahoo import tools as ytools
from finance_mcp.yahoo.data import YahooError


def test_performance_stats_in_base_currency_with_benchmark(
    fake_yahoo: list[list[str]],
) -> None:
    """Performance stats convert currency and compare with a benchmark."""
    out = ytools.get_performance_stats(
        ["AAPL", "VUSA.L"], start_date="2024-01-01", base_currency="EUR",
        benchmark="SPY",
    )  # fmt: skip
    assert out["currency"] == "EUR"
    assert out["stats"]["AAPL"]["vs_benchmark"]["beta"] is not None
    assert "sharpe_ratio" in out["stats"]["VUSA.L"]


def test_tools_return_error_dicts(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yahoo tools return error dicts instead of raising."""
    out = ytools.get_correlation(["AAPL"])
    assert out["error_code"] == "invalid_input"
    out = ytools.get_price_history(["NOPE"])
    assert out["error_code"] == "no_data" and "hint" in out
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    assert ytools.get_price_history(["NOPE"])["error_code"] == "upstream_unavailable"
    corr = ytools.get_correlation(["AAPL", "SPY"], base_currency="EUR")
    assert corr["correlation"]["AAPL"]["AAPL"] == 1.0


def test_fx_rates_tool(fake_yahoo: list[list[str]]) -> None:
    """FX rates handle minor units, the base itself and change since a date."""
    out = ytools.get_fx_rates(["USD", "GBp", "EUR"], "eur", start_date="2025-01-01")
    assert out["rates"]["USD"]["rate"] == 0.9
    assert out["rates"]["GBp"]["rate"] == pytest.approx(0.012)
    assert out["rates"]["EUR"]["rate"] == 1.0
    assert out["rates"]["USD"]["change_since_start_pct"] == 0.0


def test_price_history_thins_long_series(fake_yahoo: list[list[str]]) -> None:
    """Daily data over ~4 years is thinned to at most ~400 points, keeping the last."""
    out = ytools.get_price_history(["AAPL"], start_date="2023-01-01")
    aapl = out["data"]["AAPL"]
    assert aapl["thinned"] is True and aapl["points"] <= ytools.MAX_ROWS_PER_TICKER + 1
    assert aapl["last_date"] == "2026-10-23"
    eur = ytools.get_price_history(["AAPL", "NOPE"], "2026-01-01", base_currency="eur")
    assert eur["data"]["AAPL"]["currency"] == "EUR"
    assert eur["data"]["AAPL"]["quote_currency"] == "USD"
    assert eur["data"]["NOPE"]["error_code"] == "no_data"


def test_search_symbol(monkeypatch: pytest.MonkeyPatch) -> None:
    """Search returns candidates with a note; failures become error dicts."""

    class FakeSearch:
        """Stand-in for ``yf.Search``."""

        def __init__(self, query: str, max_results: int, news_count: int) -> None:
            """Answer 'asml' with two listings, anything else with nothing.

            Args:
                query: Search text.
                max_results: Limit.
                news_count: Ignored.

            Raises:
                RuntimeError: For the query "boom".
            """
            if query == "boom":
                raise RuntimeError("down")
            self.quotes = (
                [{"symbol": "ASML", "longname": "ASML Holding", "exchDisp": "NASDAQ"},
                 {"symbol": "ASML.AS", "shortname": "ASML", "exchange": "AMS"}]
                if query == "asml" else []
            )  # fmt: skip

    monkeypatch.setattr(yf, "Search", FakeSearch)
    hits = ytools.search_symbol("asml")
    assert [c["symbol"] for c in hits["candidates"]] == ["ASML", "ASML.AS"]
    assert "confirm exchange" in hits["note"]
    assert "No matches" in ytools.search_symbol("zzz")["note"]
    assert ytools.search_symbol("boom")["error_code"] == "upstream_unavailable"


def test_symbol_info(fake_yf: None) -> None:
    """Info drops empty fields; unknown or failing symbols return no_data."""
    out = ytools.get_symbol_info(" aapl ")
    assert out == {"symbol": "AAPL", "longName": "Apple Inc.", "currency": "USD"}
    assert ytools.get_symbol_info("NOPE")["error_code"] == "no_data"
    boom = ytools.get_symbol_info("BOOM")
    assert boom["error_code"] == "no_data" and boom["detail"] == "boom"


def test_etf_sector_allocation_and_holdings(fake_yf: None) -> None:
    """Fund composition is converted to %, sorted; non-funds give hints."""
    sectors = ytools.get_etf_sector_allocation("spy")
    assert sectors["sector_allocation_pct"] == {"technology": 30.0, "healthcare": 10.0}
    holdings = ytools.get_etf_holdings("SPY")
    assert holdings["holdings"][0] == {"symbol": "AAPL", "name": "Apple",
                                       "weight_pct": 7.0}  # fmt: skip
    assert holdings["total_pct_covered"] == 13.5
    for fn in (ytools.get_etf_sector_allocation, ytools.get_etf_holdings):
        empty = fn("AAPL")
        assert empty["error_code"] == "no_data" and "get_etf_exposure" in empty["hint"]
        assert fn("NOPE")["error_code"] == "no_data"


def test_etf_tools_unexpected_fund_errors(
    fake_yf: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Errors raised while reading fund fields are reported, not raised."""

    class Broken:
        """Fund data whose fields raise."""

        @property
        def sector_weightings(self) -> dict[str, float]:
            """Raise like a yfinance parsing bug.

            Raises:
                ValueError: Always.
            """
            raise ValueError("parse")

        @property
        def top_holdings(self) -> pd.DataFrame:
            """Raise like a yfinance parsing bug.

            Raises:
                ValueError: Always.
            """
            raise ValueError("parse")

    monkeypatch.setattr(ytools, "_funds_data", lambda sym: Broken())
    assert "parse" in ytools.get_etf_sector_allocation("SPY")["error"]
    assert "parse" in ytools.get_etf_holdings("SPY")["error"]


def test_quote(fake_yf: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Quotes include the day change; all-failed lookups check reachability."""
    out = ytools.get_quote(["AAPL", "VUSA.L", "NOPE"])["quotes"]
    assert out["AAPL"]["change_pct"] == 10.0
    assert out["VUSA.L"]["change_pct"] is None  # no previous close
    assert out["NOPE"]["error_code"] == "no_data"
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    assert ytools.get_quote(["NOPE"])["error_code"] == "upstream_unavailable"


def test_fx_rates_errors(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty input and FX download failures are reported."""
    assert ytools.get_fx_rates([" "])["error_code"] == "invalid_input"

    def no_fx(*args: Any) -> pd.DataFrame:
        """Fail like a missing FX pair.

        Args:
            *args: Ignored.

        Raises:
            YahooError: Always.
        """
        raise YahooError("fx_unavailable", "no FX")

    monkeypatch.setattr(data, "download_fx", no_fx)
    assert ytools.get_fx_rates(["USD"])["error_code"] == "fx_unavailable"


def test_performance_stats_warnings(fake_yahoo: list[list[str]]) -> None:
    """Missing benchmark, missing tickers and short windows are flagged."""
    out = ytools.get_performance_stats(["AAPL", "NOPE"], benchmark="ZZZ")
    assert out["stats"]["NOPE"]["error_code"] == "no_data"
    assert "benchmark ZZZ returned no data" in out["warnings"]
    daily = ytools.get_performance_stats(["EUNL.DE"], benchmark="SPY")
    assert any("time zones" in w for w in daily["warnings"])
    short = ytools.get_performance_stats(["AAPL"], start_date="2026-10-22")
    assert short["stats"]["AAPL"]["error_code"] == "insufficient_data"
    assert ytools.get_performance_stats(["NOPE"])["error_code"] == "no_data"


def test_correlation_short_window_and_missing(fake_yahoo: list[list[str]]) -> None:
    """Too few common dates is an error; missing tickers are listed."""
    short = ytools.get_correlation(["AAPL", "SPY"], start_date="2026-10-15")
    assert short["error_code"] == "insufficient_data"
    out = ytools.get_correlation(["AAPL", "SPY", "NOPE"], interval="1d")
    assert out["missing"] == ["NOPE"]
    assert not any("time zones" in w for w in out.get("warnings", []))  # both US


def test_dividends(fake_yf: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """Dividends are filtered by date with a trailing-12-month total."""
    out = ytools.get_dividends("AAPL", start_date="2025-06-01", end_date="2026-12-31")
    assert out["count"] == 2 and out["total"] == 0.51
    assert out["trailing_12m_total"] == 0.51 and out["payments_last_12m"] == 2
    assert list(out["dividends"]) == ["2025-11-10", "2026-02-10"]
    assert ytools.get_dividends("SPY")["note"] == "No dividends found."
    assert ytools.get_dividends("BOOM")["detail"] == "boom"
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    assert ytools.get_dividends("SPY")["error_code"] == "upstream_unavailable"
