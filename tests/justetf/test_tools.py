"""justETF MCP tools (service layer faked)."""

from __future__ import annotations

from typing import Any

import pytest

from finance_mcp.justetf import service
from finance_mcp.justetf.client import JustEtfError
from tests.fakes import ISIN, make, tool

OTHER = "IE00BFMXXD54"  # Vanguard S&P 500 (a real, valid ISIN)


@pytest.fixture
def profiles(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    """Serve two synthetic ETF profiles from ``service.get_profile``.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The fake profiles by ISIN; tools see unknown ISINs as not found.
    """
    known = {
        ISIN: make(ISIN, 0.2, 1000, [("United States", 70), ("Other", 30)],
                   [("Technology", 25), ("Other", 75)], [("Apple", 5)]),
        OTHER: make(OTHER, 0.07, 40000, [("United States", 100)],
                    [("Technology", 30), ("Other", 70)], [("Apple", 7)]),
    }  # fmt: skip

    def get_profile(isin: str, refresh: bool = False) -> dict[str, Any]:
        """Look up a fake profile.

        Args:
            isin: Requested ISIN.
            refresh: Ignored.

        Returns:
            The profile.

        Raises:
            JustEtfError: For invalid or unknown ISINs.
        """
        isin = service.normalize_isin(isin)
        if isin not in known:
            raise JustEtfError(f"ISIN {isin} was not found on justETF")
        return known[isin]

    monkeypatch.setattr(service, "get_profile", get_profile)
    return known


def test_profile_listings_performance_similar(
    profiles: dict[str, dict[str, Any]],
) -> None:
    """Single-ETF tools return their slice of the profile plus the source."""
    p = tool("get_etf_profile")(ISIN)
    assert p["ter_pct"] == 0.2 and p["source"].startswith("justETF")
    assert "holdings" not in p
    assert tool("get_etf_listings")(ISIN)["listings"][0]["ticker"] == "EUNL"
    perf = tool("get_etf_performance")(ISIN)
    assert perf["performance"]["period_returns_pct"]["1y"] == 10.0
    similar = tool("get_similar_etfs")(ISIN)
    assert similar["index"] == "I" and similar["this_etf"]["ter_pct"] == 0.2


@pytest.mark.parametrize(
    "name",
    ["get_etf_profile", "get_etf_exposure", "get_etf_performance",
     "get_etf_listings", "get_similar_etfs"],
)  # fmt: skip
def test_single_etf_tools_return_errors(
    profiles: dict[str, dict[str, Any]], name: str
) -> None:
    """Unknown or invalid ISINs come back as an error dict, not an exception."""
    assert "not a valid ISIN" in tool(name)("nope")["error"]
    assert "not found" in tool(name)("US0378331005")["error"]


def test_exposure_sections(profiles: dict[str, dict[str, Any]]) -> None:
    """``section`` limits the breakdown; bad values are rejected."""
    exposure = tool("get_etf_exposure")
    full = exposure(ISIN)
    assert {"countries", "sectors", "top_10_holdings"} <= set(full)
    only = exposure(ISIN, section=" Countries ")
    assert "countries" in only and "sectors" not in only
    assert "top_10_holdings" not in only
    assert "error" in exposure(ISIN, section="bonds")


def test_compare_etfs(profiles: dict[str, dict[str, Any]]) -> None:
    """Comparison picks the cheapest and largest and keeps per-ISIN errors."""
    out = tool("compare_etfs")([ISIN, OTHER, "nope"])
    assert [r["isin"] for r in out["etfs"]] == [ISIN, OTHER]
    assert out["cheapest"] == OTHER and out["largest"] == OTHER
    assert "nope" in out["errors"]
    assert out["etfs"][0]["return_1y_pct"] == 10.0
    empty = tool("compare_etfs")([])
    assert empty["cheapest"] is None and empty["largest"] is None


def test_analyze_portfolio_tool(profiles: dict[str, dict[str, Any]]) -> None:
    """Amounts are summed per ISIN; failed ETFs are excluded with a note."""
    analyze = tool("analyze_portfolio")
    out = analyze(
        [{"isin": ISIN, "amount": 1000}, {"isin": ISIN.lower(), "amount": "1000"},
         {"isin": OTHER, "amount": 2000}, {"isin": "US0378331005", "amount": 5}],
    )  # fmt: skip
    assert out["cost_and_size"]["weighted_ter_pct"] == pytest.approx(0.135)
    assert "US0378331005" in out["errors"]
    assert any("excluded" in n for n in out["notes"])
    equal = analyze([{"isin": ISIN}, {"isin": OTHER}], top_n=500)
    assert equal["cost_and_size"]["weighted_ter_pct"] == pytest.approx(0.135)


def test_analyze_portfolio_tool_errors(profiles: dict[str, dict[str, Any]]) -> None:
    """Empty, malformed, unloadable and mixed-weight inputs return errors."""
    analyze = tool("analyze_portfolio")
    assert analyze([])["error"] == "positions is empty"
    assert "invalid positions" in analyze([{"isin": ISIN, "amount": "lots"}])["error"]
    nothing = analyze([{"isin": "US0378331005"}, {"isin": "bad"}])
    assert nothing["error"] == "no ETF could be loaded"
    mixed = analyze([{"isin": ISIN, "amount": 100}, {"isin": OTHER}])
    assert "error" in mixed


def test_search_etf_tool_clamps_results(monkeypatch: pytest.MonkeyPatch) -> None:
    """``max_results`` is clamped to 1-20 before searching."""
    seen: list[int] = []

    def search_etf(query: str, max_results: int, use_yahoo: bool) -> dict[str, Any]:
        """Record the requested limit.

        Args:
            query: Search text.
            max_results: Limit after clamping.
            use_yahoo: Whether Yahoo may be used.

        Returns:
            An empty result.
        """
        seen.append(max_results)
        return {"matches": []}

    from finance_mcp.justetf import search

    monkeypatch.setattr(search, "search_etf", search_etf)
    tool("search_etf")("world", max_results=99)
    tool("search_etf")("world", max_results=0)
    assert seen == [20, 1]
