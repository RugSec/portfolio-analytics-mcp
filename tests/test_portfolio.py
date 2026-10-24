"""Offline tests for ISIN resolution and portfolio risk (network faked)."""

import numpy as np
import pandas as pd
import pytest

from finance_mcp.justetf.client import JustEtfError
from finance_mcp.portfolio import resolve, risk
from finance_mcp.portfolio.risk import Position
from finance_mcp.yahoo import data
from finance_mcp.yahoo import tools as ytools
from finance_mcp.yahoo.data import YahooError

DATES = pd.bdate_range("2023-01-02", "2026-10-23")


def walk(seed, start=100.0, vol=0.01):
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


@pytest.fixture
def fake_yahoo(monkeypatch):
    calls: list[list[str]] = []

    def download_close(symbols, start, end, interval):
        calls.append(list(symbols))
        cols = {s: PRICES[s] for s in symbols if s in PRICES}
        if not cols:
            return pd.DataFrame()
        df = pd.DataFrame(cols, index=DATES)
        if interval == "1wk":
            df = df.resample("W-MON").last()
        return df.loc[pd.Timestamp(start) :]

    def download_fx(currencies, base, start, end):
        need = sorted(c for c in currencies if c != base)
        return pd.DataFrame({c: FX[c] for c in need}, index=DATES)

    monkeypatch.setattr(data, "download_close", download_close)
    monkeypatch.setattr(data, "download_fx", download_fx)
    monkeypatch.setattr(
        data, "get_currencies", lambda syms: {s: CURRENCIES.get(s) for s in syms}
    )
    monkeypatch.setattr(data, "yahoo_reachable", lambda: True)
    return calls


# ------------------------------------------------------------------ resolve
LISTINGS = [
    {"mic_code": "XLON", "exchange": "London Stock Exchange",
     "trading_currency": "USD", "ticker": "SWDA"},
    {"mic_code": "XAMS", "exchange": "Euronext Amsterdam",
     "trading_currency": "EUR", "ticker": "IWDA"},
    {"mic_code": "XETR", "exchange": "XETRA", "trading_currency": "EUR",
     "ticker": "EUNL"},
    {"mic_code": "GETT", "exchange": "gettex", "trading_currency": "EUR",
     "ticker": "EUNL"},
    {"mic_code": "XYZZ", "exchange": "SIX Swiss Exchange",
     "trading_currency": "CHF", "ticker": "IWDA"},
]  # fmt: skip


def test_yahoo_candidates_ranking_and_unmapped():
    cands, unmapped = resolve.yahoo_candidates(LISTINGS, "EUR")
    assert [c["symbol"] for c in cands] == ["EUNL.DE", "IWDA.AS", "SWDA.L", "IWDA.SW"]
    assert unmapped == [{"exchange": "gettex", "mic_code": "GETT", "ticker": "EUNL"}]
    usd_first, _ = resolve.yahoo_candidates(LISTINGS, "USD")
    assert usd_first[0]["symbol"] == "SWDA.L"


def test_resolve_isin_uses_justetf_then_yahoo_search(monkeypatch):
    monkeypatch.setattr(
        resolve.service,
        "get_profile",
        lambda isin: {"isin": isin, "name": "World", "listings": LISTINGS},
    )
    out = resolve.resolve_isin("ie00b4l5y983", "EUR")
    assert out["source"] == "justetf_listings"
    assert out["yahoo_candidates"][0]["symbol"] == "EUNL.DE"

    def not_found(isin):
        raise JustEtfError("not on justETF")

    monkeypatch.setattr(resolve.service, "get_profile", not_found)
    monkeypatch.setattr(
        resolve,
        "_yahoo_search_isin",
        lambda isin: [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "exchange": "NASDAQ",
                "type": "EQUITY",
            }
        ],  # fmt: skip
    )
    out = resolve.resolve_isin("US0378331005")
    assert (
        out["source"] == "yahoo_search"
        and out["yahoo_candidates"][0]["symbol"] == "AAPL"
    )
    monkeypatch.setattr(resolve, "_yahoo_search_isin", lambda isin: [])
    with pytest.raises(JustEtfError):
        resolve.resolve_isin("US0378331005")


# ------------------------------------------------------------------ portfolio
def test_portfolio_values_in_base_currency(fake_yahoo):
    out = risk.analyze_portfolio_risk(
        [
            Position(symbol="aapl", quantity=10),
            Position(symbol="VUSA.L", quantity=100),
            Position(symbol="EUNL.DE", value=5000),
        ],
        base_currency="EUR",
        benchmark="SPY",
    )
    rows = {r["symbol"]: r for r in out["positions"]}
    aapl_eur = 10 * PRICES["AAPL"][-1] * 0.9
    vusa_eur = 100 * PRICES["VUSA.L"][-1] * 0.01 * 1.2  # pence -> GBP -> EUR
    assert rows["AAPL"]["value_base"] == pytest.approx(aapl_eur, abs=0.01)
    assert rows["VUSA.L"]["value_base"] == pytest.approx(vusa_eur, abs=0.01)
    assert out["total_value"] == pytest.approx(aapl_eur + vusa_eur + 5000, abs=0.05)
    assert sum(r["weight_pct"] for r in rows.values()) == pytest.approx(100, abs=0.05)
    assert sum(r["risk_contribution_pct"] for r in rows.values()) == pytest.approx(
        100, abs=0.05
    )
    assert out["window"]["from"] == "2023-10-24"  # default: 3 years back
    assert "beta" in out["portfolio"]["vs_benchmark"]
    assert out["benchmark"]["symbol"] == "SPY"
    assert set(out["correlation"]) == {"AAPL", "VUSA.L", "EUNL.DE"}
    assert out["fx_rates_used"] == {"GBPEUR": 1.2, "USDEUR": 0.9}
    assert any("minor units" in w for w in out["warnings"])


def test_portfolio_isin_falls_back_to_next_listing(fake_yahoo, monkeypatch):
    monkeypatch.setattr(
        risk,
        "resolve_isin",
        lambda isin, base: {
            "isin": isin,
            "name": "World",
            "yahoo_candidates": [{"symbol": "EUNL.F"}, {"symbol": "IWDA.AS"}],
        },
    )
    out = risk.analyze_portfolio_risk(
        [Position(isin="IE00B4L5Y983"), Position(symbol="AAPL")], interval="1wk"
    )
    assert [r["symbol"] for r in out["positions"]] == ["IWDA.AS", "AAPL"]
    assert out["isin_resolution"][0]["symbol"] == "IWDA.AS"
    assert out["isin_resolution"][0]["alternatives"] == ["EUNL.F"]
    assert out["total_value"] is None  # equal weights
    assert [r["weight_pct"] for r in out["positions"]] == [50.0, 50.0]


def test_portfolio_input_errors(fake_yahoo):
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk(
            [Position(symbol="AAPL", quantity=1), Position(symbol="SPY")]
        )
    assert exc.value.code == "invalid_input"
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="AAPL")], base_currency="euro")
    assert exc.value.code == "invalid_input"
    with pytest.raises(ValueError):
        Position(symbol="AAPL", quantity=1, value=2)
    with pytest.raises(ValueError):
        Position(quantity=1)


def test_portfolio_unknown_ticker_vs_yahoo_down(fake_yahoo, monkeypatch):
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="AAPL"), Position(symbol="NOPE")])
    assert exc.value.code == "no_data" and "NOPE" in exc.value.message
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="NOPE")])
    assert exc.value.code == "upstream_unavailable"


def test_portfolio_too_short_window(fake_yahoo):
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="AAPL")], start_date="2026-10-20")
    assert exc.value.code == "insufficient_data"


# ------------------------------------------------------------------ yahoo tools
def test_performance_stats_in_base_currency_with_benchmark(fake_yahoo):
    out = ytools.get_performance_stats(
        ["AAPL", "VUSA.L"], start_date="2024-01-01", base_currency="EUR",
        benchmark="SPY",
    )  # fmt: skip
    assert out["currency"] == "EUR"
    assert out["stats"]["AAPL"]["vs_benchmark"]["beta"] is not None
    assert "sharpe_ratio" in out["stats"]["VUSA.L"]


def test_tools_return_error_dicts(fake_yahoo, monkeypatch):
    out = ytools.get_correlation(["AAPL"])
    assert out["error_code"] == "invalid_input"
    out = ytools.get_price_history(["NOPE"])
    assert out["error_code"] == "no_data" and "hint" in out
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    assert ytools.get_price_history(["NOPE"])["error_code"] == "upstream_unavailable"
    corr = ytools.get_correlation(["AAPL", "SPY"], base_currency="EUR")
    assert corr["correlation"]["AAPL"]["AAPL"] == 1.0


def test_fx_rates_tool(fake_yahoo):
    out = ytools.get_fx_rates(["USD", "GBp", "EUR"], "eur", start_date="2025-01-01")
    assert out["rates"]["USD"]["rate"] == 0.9
    assert out["rates"]["GBp"]["rate"] == pytest.approx(0.012)
    assert out["rates"]["EUR"]["rate"] == 1.0
    assert out["rates"]["USD"]["change_since_start_pct"] == 0.0


def test_download_close_parses_yfinance_frames(monkeypatch):
    """The real wrapper, with yf.download faked in its multi-index shape."""
    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06"], tz="Europe/Amsterdam")
    cols = pd.MultiIndex.from_product([["Close", "Volume"], ["AAPL", "DEAD"]])
    frame = pd.DataFrame(
        [[1.0, np.nan, 10, np.nan], [2.0, np.nan, 20, np.nan]], index=idx, columns=cols
    )
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: frame)
    out = data.download_close(["AAPL", "DEAD"], "2026-01-01", None, "1d")
    assert list(out.columns) == ["AAPL"]  # all-NaN column dropped
    assert out.index.tz is None and out["AAPL"].tolist() == [1.0, 2.0]
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: pd.DataFrame())
    assert data.download_close(["X"], None, None, "1d").empty
    with pytest.raises(YahooError):
        data.download_close(["X"], None, None, "5m")


def test_isin_errors_are_classified(fake_yahoo, monkeypatch):
    def down(isin, base):
        raise JustEtfError(
            "Could not reach justETF: timeout; Yahoo search found nothing either"
        )

    monkeypatch.setattr(risk, "resolve_isin", down)
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(isin="IE00B4L5Y983")])
    assert exc.value.code == "upstream_unavailable"
    assert (
        risk._justetf_code(JustEtfError("'X' is not a valid ISIN")) == "invalid_input"
    )
