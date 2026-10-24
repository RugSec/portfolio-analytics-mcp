"""Portfolio MCP tools."""

from __future__ import annotations

from typing import Any

import pytest

from finance_mcp.justetf.client import JustEtfError
from tests.fakes import ISIN, tool


def test_resolve_instrument_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolution errors are returned with a code and a hint."""
    from finance_mcp.portfolio import tools as ptools

    monkeypatch.setattr(ptools, "resolve_isin", lambda isin, base: {"isin": isin})
    assert tool("resolve_instrument")(ISIN) == {"isin": ISIN}

    def fail(isin: str, base: str | None) -> dict[str, Any]:
        """Fail like an invalid ISIN.

        Args:
            isin: Requested ISIN.
            base: Preferred currency.

        Raises:
            JustEtfError: Always.
        """
        raise JustEtfError("'x' is not a valid ISIN")

    monkeypatch.setattr(ptools, "resolve_isin", fail)
    out = tool("resolve_instrument")("x")
    assert out["error_code"] == "invalid_input" and "search_symbol" in out["hint"]


def test_analyze_portfolio_risk_tool(fake_yahoo: list[list[str]]) -> None:
    """The risk tool passes options through and returns errors as dicts."""
    from finance_mcp.portfolio.risk import Position

    run = tool("analyze_portfolio_risk")
    out = run([Position(symbol="AAPL"), Position(symbol="SPY")], interval="1wk")
    assert out["base_currency"] == "EUR" and len(out["positions"]) == 2
    err = run([Position(symbol="AAPL")], base_currency="euro")
    assert err["error_code"] == "invalid_input"
