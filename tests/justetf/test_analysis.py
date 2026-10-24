"""Portfolio maths on parsed justETF profiles."""

from __future__ import annotations

import pytest

from finance_mcp.justetf import analysis
from tests.fakes import make


def test_weights() -> None:
    """Amounts become weights; missing for all means equal weights."""
    assert analysis.compute_weights([None, None]) == [0.5, 0.5]
    assert analysis.compute_weights([300, 100]) == [0.75, 0.25]
    with pytest.raises(ValueError):
        analysis.compute_weights([100, None])
    with pytest.raises(ValueError):
        analysis.compute_weights([100, -1])


def test_portfolio_analysis() -> None:
    """Cost, exposure and look-through are weighted by position."""
    a = make(
        "A",
        0.2,
        1000,
        [("United States", 70), ("Japan", 10), ("Other", 20)],
        [("Technology", 30), ("Other", 70)],
        [("Apple", 5), ("Nvidia", 4)],
    )
    b = make(
        "B",
        0.4,
        50,
        [("United States", 50), ("Other", 50)],
        [("Technology", 50), ("Other", 50)],
        [("Apple", 3)],
    )
    r = analysis.analyze_portfolio([a, b], [7500, 2500])
    cost = r["cost_and_size"]
    assert cost["weighted_ter_pct"] == 0.25
    assert cost["total_annual_cost"] == 25.0
    assert cost["positions"][1]["flags"]  # B is a small fund
    us = r["country_exposure"]["buckets"][0]
    assert us["name"] == "United States" and us["pct_of_portfolio"] == 65.0
    assert us["by_etf"][0]["isin"] == "A"
    assert r["country_exposure"]["other_pct"] == 27.5
    tech = r["sector_exposure"]["buckets"][0]
    assert tech["pct_of_portfolio"] == 35.0
    apple = r["stock_look_through"]["top_stocks"][0]
    assert apple["name"] == "Apple" and apple["number_of_etfs"] == 2
    assert apple["pct_of_portfolio"] == 4.5


def test_focus_filter() -> None:
    """``focus_countries`` keeps only matching buckets."""
    a = make(
        "A",
        0.2,
        1000,
        [("United States", 70), ("Japan", 10), ("Other", 20)],
        [("Technology", 30), ("Other", 70)],
        [],
    )
    r = analysis.analyze_portfolio([a], [None], focus_countries=["jap"])
    assert [b["name"] for b in r["country_exposure"]["buckets"]] == ["Japan"]
