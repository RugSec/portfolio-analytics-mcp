"""ISIN -> Yahoo ticker resolution."""

from __future__ import annotations

from typing import Any

import pytest

from finance_mcp.justetf.client import JustEtfError
from finance_mcp.portfolio import resolve


def test_yahoo_search_isin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yahoo ISIN search maps quotes; a crashing search counts as no hits."""
    import yfinance as yf

    class FakeSearch:
        """Stand-in for ``yf.Search`` with fixed quotes."""

        def __init__(self, query: str, **kwargs: Any) -> None:
            """Store canned quotes.

            Args:
                query: Search text.
                **kwargs: Ignored options.
            """
            self.quotes = [
                {"symbol": "AAPL", "shortname": "Apple", "exchange": "NMS",
                 "quoteType": "EQUITY"},
                {"longname": "no symbol"},
            ]  # fmt: skip

    monkeypatch.setattr(yf, "Search", FakeSearch)
    assert resolve._yahoo_search_isin("US0378331005") == [
        {"symbol": "AAPL", "name": "Apple", "exchange": "NMS", "type": "EQUITY"}
    ]

    def not_found(isin: str) -> dict[str, Any]:
        """Fail like justETF not knowing the ISIN.

        Args:
            isin: Requested ISIN.

        Raises:
            JustEtfError: Always.
        """
        raise JustEtfError("not on justETF")

    def crash(isin: str) -> list[dict[str, Any]]:
        """Fail like a broken network.

        Args:
            isin: Requested ISIN.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError("network down")

    monkeypatch.setattr(resolve.service, "get_profile", not_found)
    monkeypatch.setattr(resolve, "_yahoo_search_isin", crash)
    with pytest.raises(JustEtfError, match="found nothing either"):
        resolve.resolve_isin("US0378331005")


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


def test_yahoo_candidates_ranking_and_unmapped() -> None:
    """Listings rank by currency then exchange; unknown venues are unmapped."""
    cands, unmapped = resolve.yahoo_candidates(LISTINGS, "EUR")
    assert [c["symbol"] for c in cands] == ["EUNL.DE", "IWDA.AS", "SWDA.L", "IWDA.SW"]
    assert unmapped == [{"exchange": "gettex", "mic_code": "GETT", "ticker": "EUNL"}]
    usd_first, _ = resolve.yahoo_candidates(LISTINGS, "USD")
    assert usd_first[0]["symbol"] == "SWDA.L"


def test_resolve_isin_uses_justetf_then_yahoo_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ISINs resolve via justETF listings, else via Yahoo search."""
    monkeypatch.setattr(
        resolve.service,
        "get_profile",
        lambda isin: {"isin": isin, "name": "World", "listings": LISTINGS},
    )
    out = resolve.resolve_isin("ie00b4l5y983", "EUR")
    assert out["source"] == "justetf_listings"
    assert out["yahoo_candidates"][0]["symbol"] == "EUNL.DE"

    def not_found(isin: str) -> dict[str, Any]:
        """Fail like justETF not knowing the ISIN."""
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
