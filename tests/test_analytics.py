"""Offline tests for the pure return/risk maths (synthetic prices)."""

import math

import numpy as np
import pandas as pd
import pytest

from finance_mcp.yahoo import analytics as an


def series(values, start="2024-01-01", freq="B"):
    return pd.Series(
        values, index=pd.date_range(start, periods=len(values), freq=freq), dtype=float
    )


def random_prices(n=600, vol=0.01, seed=0, drift=0.0003):
    rng = np.random.default_rng(seed)
    return series(100 * np.cumprod(1 + rng.normal(drift, vol, n)))


# ------------------------------------------------------------------ currency
def test_major_currency_handles_minor_units():
    assert an.major_currency("GBp") == ("GBP", 0.01)
    assert an.major_currency("GBX") == ("GBP", 0.01)
    assert an.major_currency("usd") == ("USD", 1.0)
    assert an.major_currency(None) == (None, 1.0)


def test_to_base_currency_converts_and_fills_fx():
    idx = pd.to_datetime(["2026-01-05", "2026-01-06", "2026-01-07"])
    prices = pd.DataFrame(
        {"AAPL": [100.0, 110.0, 120.0], "VUSA.L": [5000.0, 5000.0, 5000.0],
         "SAP.DE": [200.0, 200.0, 200.0]},
        index=idx,
    )  # fmt: skip
    # FX only on the first two days: the third is forward-filled
    fx = pd.DataFrame({"USD": [0.9, 0.8], "GBP": [1.2, 1.1]}, index=idx[:2])
    out = an.to_base_currency(
        prices, {"AAPL": "USD", "VUSA.L": "GBp", "SAP.DE": "EUR"}, fx, "eur"
    )
    assert out["AAPL"].tolist() == pytest.approx([90.0, 88.0, 96.0])
    assert out["VUSA.L"].tolist() == pytest.approx([60.0, 55.0, 55.0])
    assert out["SAP.DE"].tolist() == [200.0, 200.0, 200.0]


def test_to_base_currency_errors_on_missing_fx():
    prices = pd.DataFrame(
        {"X": [1.0, 2.0]}, index=pd.date_range("2026-01-01", periods=2)
    )
    with pytest.raises(ValueError, match="no FX rate CHF->EUR"):
        an.to_base_currency(prices, {"X": "CHF"}, pd.DataFrame(), "EUR")
    with pytest.raises(ValueError, match="unknown quote currency"):
        an.to_base_currency(prices, {"X": None}, pd.DataFrame(), "EUR")


# ------------------------------------------------------------------ calendar
def test_align_prices_fills_holidays_and_trims_to_common_window():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    prices = pd.DataFrame(
        {"A": [1.0, 2.0, np.nan, 4.0, 5.0], "B": [np.nan, np.nan, 3.0, 3.0, np.nan]},
        index=idx,
    )
    out = an.align_prices(prices)
    assert out.index[0] == idx[2]  # B starts on day 3
    assert out["A"].tolist() == [2.0, 4.0, 5.0]  # A's holiday filled
    assert out["B"].tolist() == [3.0, 3.0, 3.0]  # B's lagging last quote filled


def test_window_report_flags_short_history_and_stale_quotes():
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    prices = pd.DataFrame(
        {"OLD": np.arange(10.0) + 1, "NEW": [np.nan] * 4 + list(range(6)),
         "STALE": list(range(1, 6)) + [np.nan] * 5},
        index=idx,
    )  # fmt: skip
    rep = an.window_report(prices)
    assert rep["window_limited_by"] == ["NEW"]
    assert rep["stale"] == {"STALE": "2026-01-05"}


# ------------------------------------------------------------------ single series
def test_max_drawdown_dates():
    s = series([100, 120, 90, 110, 125, 100])
    dd = an.max_drawdown(s)
    assert dd["max_drawdown_pct"] == -25.0
    assert dd["peak_date"] == "2024-01-02"
    assert dd["trough_date"] == "2024-01-03"
    assert dd["recovery_date"] == "2024-01-05"


def test_series_stats_constant_growth():
    s = series(100 * 1.001 ** np.arange(400))
    st = an.series_stats(s, 252)
    assert st["annualized_volatility_pct"] == pytest.approx(0.0, abs=1e-6)
    assert st["max_drawdown_pct"] == 0.0 and st["trough_date"] is None
    assert st["total_return_pct"] == pytest.approx((1.001**399 - 1) * 100, abs=0.01)
    assert st["annualized_return_pct"] is not None  # > 1 year of data
    assert st["sharpe_ratio"] is None  # zero volatility


def test_series_stats_no_annualising_short_windows():
    st = an.series_stats(random_prices(100), 252)
    assert st["years"] < 1 and st["annualized_return_pct"] is None
    assert st["annualized_volatility_pct"] > 0


def test_series_stats_volatility_scales_with_interval():
    s = random_prices(800, vol=0.01, drift=0.0)
    daily = an.series_stats(s, 252)["annualized_volatility_pct"]
    assert daily == pytest.approx(1.0 * math.sqrt(252), rel=0.1)
    with pytest.raises(ValueError):
        an.series_stats(series([1.0, 2.0]), 252)


def test_sharpe_falls_with_risk_free_rate():
    s = random_prices(600)
    assert (
        an.series_stats(s, 252, 0.05)["sharpe_ratio"]
        < an.series_stats(s, 252, 0.0)["sharpe_ratio"]
    )


def test_relative_stats_levered_asset():
    bench = random_prices(500, seed=1)
    rets = bench.pct_change().fillna(0)
    asset = 100 * (1 + 2 * rets).cumprod()
    rel = an.relative_stats(asset, bench, 252)
    assert rel["beta"] == pytest.approx(2.0, abs=1e-3)
    assert rel["correlation"] == pytest.approx(1.0, abs=1e-3)
    same = an.relative_stats(bench, bench, 252)
    assert same["tracking_error_pct"] == 0.0 and same["information_ratio"] is None


# ------------------------------------------------------------------ portfolio
def test_portfolio_values_methods():
    prices = pd.DataFrame(
        {"A": [100.0, 200.0, 200.0], "B": [100.0, 100.0, 100.0]},
        index=pd.date_range("2026-01-01", periods=3),
    )
    w = pd.Series({"A": 0.5, "B": 0.5})
    held = an.portfolio_values(prices, w, "current_holdings")
    # today 50/50 = 0.0025 units of A + 0.005 of B: 0.75 at the start -> 1.0
    assert held.tolist() == pytest.approx([100.0, 400 / 3, 400 / 3])
    reb = an.portfolio_values(prices, w, "constant_weights")
    assert reb.tolist() == pytest.approx([100.0, 150.0, 150.0])
    with pytest.raises(ValueError):
        an.portfolio_values(prices, pd.Series({"A": 1.0, "B": 0.0}))


def test_risk_contributions_sum_and_diversification():
    a = random_prices(2000, seed=2, drift=0)
    b = random_prices(2000, seed=3, drift=0)
    prices = pd.concat([a, b], axis=1, keys=["A", "B"])
    out = an.risk_contributions(prices, pd.Series({"A": 0.5, "B": 0.5}), 252)
    contrib = [v["risk_contribution_pct"] for v in out["by_position"].values()]
    assert sum(contrib) == pytest.approx(100.0, abs=0.05)
    assert contrib[0] == pytest.approx(50.0, abs=5)
    # two ~uncorrelated equal-vol assets: diversification ratio ~ sqrt(2)
    assert out["diversification_ratio"] == pytest.approx(math.sqrt(2), abs=0.1)
    corr = an.correlation_matrix(prices)
    assert corr["A"]["A"] == 1.0 and abs(corr["A"]["B"]) < 0.1
