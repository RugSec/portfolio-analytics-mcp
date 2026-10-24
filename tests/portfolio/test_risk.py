"""Whole-portfolio risk in one base currency (Yahoo faked)."""

from __future__ import annotations

from typing import Any

import pytest

from finance_mcp.justetf.client import JustEtfError
from finance_mcp.portfolio import risk
from finance_mcp.portfolio.risk import Position
from finance_mcp.yahoo import data
from finance_mcp.yahoo.data import YahooError
from tests.fakes import PRICES


def test_portfolio_values_in_base_currency(fake_yahoo: list[list[str]]) -> None:
    """Positions are valued in the base currency with weights and risk summing to 100%."""
    out = risk.analyze_portfolio_risk(
        [
            Position(symbol="aapl", quantity=10),
            Position(symbol="VUSA.L", quantity=100),
            Position(symbol="EUNL.DE", value=5000),
        ],
        base_currency="EUR",
        benchmark="SPY",
        interval="1d",
        end_date="2026-10-24",
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
    assert any("time zones (America, Europe)" in w for w in out["warnings"])


def test_portfolio_isin_falls_back_to_next_listing(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ISIN whose first listing has no data uses the next candidate."""
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


def test_portfolio_input_errors(fake_yahoo: list[list[str]]) -> None:
    """Mixed sizing, bad currencies and ambiguous positions are rejected."""
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


def test_portfolio_unknown_ticker_vs_yahoo_down(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown ticker is ``no_data``; Yahoo down is ``upstream_unavailable``."""
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="AAPL"), Position(symbol="NOPE")])
    assert exc.value.code == "no_data" and "NOPE" in exc.value.message
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="NOPE")])
    assert exc.value.code == "upstream_unavailable"


def test_portfolio_too_short_window(fake_yahoo: list[list[str]]) -> None:
    """A window with too few prices is ``insufficient_data``."""
    with pytest.raises(YahooError) as exc:
        risk.analyze_portfolio_risk([Position(symbol="AAPL")], start_date="2026-10-20")
    assert exc.value.code == "insufficient_data"


def test_isin_errors_are_classified(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Failures from justETF map to the right error codes."""

    def down(isin: str, base: str | None) -> dict[str, Any]:
        """Fail like justETF being unreachable."""
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


def test_portfolio_drops_bad_prints(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bad Yahoo prints are dropped and reported as warnings."""
    bad = PRICES["EUNL.DE"].copy()
    bad[300] *= 1.34  # e.g. a London quote once recorded in US cents
    monkeypatch.setitem(PRICES, "EUNL.DE", bad)
    out = risk.analyze_portfolio_risk(
        [Position(symbol="EUNL.DE"), Position(symbol="IWDA.AS")], interval="1d"
    )
    assert any("EUNL.DE: dropped 1 bad price" in w for w in out["warnings"])
    # same fund on two exchanges again correlates perfectly
    assert out["correlation"]["EUNL.DE"]["IWDA.AS"] == pytest.approx(1.0, abs=1e-3)
    assert not any("time zones" in w for w in out["warnings"])  # both European
