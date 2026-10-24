"""Name/ticker -> ISIN search for ETFs."""

from __future__ import annotations

from types import ModuleType

import pytest


def test_search_isin_passthrough_and_empty() -> None:
    """An ISIN is returned as is; an empty query is an error."""
    from finance_mcp.justetf import search

    assert search.search_etf("ie00b4l5y983")["matches"][0]["match"] == "isin"
    assert "error" in search.search_etf("  ")


def test_search_maps_yahoo_listings_to_isin(
    registry_env: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yahoo listings are mapped to known ISINs; unknown ones stay unresolved."""
    from finance_mcp.justetf import search

    quotes = [
        {
            "symbol": "IWDA.AS",
            "quoteType": "ETF",
            "longname": "x",
            "exchDisp": "Amsterdam",
        },
        {"symbol": "EUNL.DE", "quoteType": "ETF", "longname": "x", "exchDisp": "XETRA"},
        {
            "symbol": "ZZZ.L",
            "quoteType": "ETF",
            "longname": "Unknown Fund",
            "exchDisp": "London",
        },
    ]
    monkeypatch.setattr(search, "_yahoo_candidates", lambda q, n: quotes)
    out = search.search_etf("something obscure")
    resolved = [m for m in out["matches"] if m["match"] == "yahoo"]
    assert (
        resolved[0]["isin"] == "IE00B4L5Y983"
        and len(resolved[0]["yahoo_listings"]) == 2
    )
    assert out["unresolved_candidates"][0]["isin"] is None
