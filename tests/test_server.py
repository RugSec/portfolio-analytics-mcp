"""Server wiring: registered tools, health route, transport selection."""

from __future__ import annotations

import asyncio
import runpy
from typing import Any

import pytest

from finance_mcp import server

TOKEN = "alice-secret-token-123"
EXPECTED_TOOLS = {
    # Yahoo
    "get_price_history", "search_symbol", "get_symbol_info",
    "get_etf_sector_allocation", "get_etf_holdings", "get_quote", "get_fx_rates",
    "get_performance_stats", "get_correlation", "get_dividends",
    # justETF
    "search_etf", "get_etf_profile", "get_etf_exposure", "get_etf_performance",
    "get_etf_listings", "get_similar_etfs", "compare_etfs", "analyze_portfolio",
    # portfolio
    "resolve_instrument", "analyze_portfolio_risk",
}  # fmt: skip


def test_all_tools_registered_read_only() -> None:
    """Every tool is registered once and annotated as read-only."""
    tools = asyncio.run(server.mcp.list_tools())
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.annotations is not None and tool.annotations.readOnlyHint
        assert tool.description, f"{tool.name} has no description"


def test_health_route() -> None:
    """The health endpoint answers 'ok'."""
    resp = asyncio.run(server.health(None))  # type: ignore[arg-type]
    assert resp.status_code == 200 and resp.body == b"ok"


@pytest.mark.parametrize(
    ("transport", "expected"),
    [
        (None, "stdio"),
        ("stdio", "stdio"),
        ("http", "http"),
        ("Streamable-HTTP", "http"),
    ],
)
def test_main_picks_transport(
    monkeypatch: pytest.MonkeyPatch, transport: str | None, expected: str
) -> None:
    """MCP_TRANSPORT selects stdio (default) or HTTP."""
    used: list[str] = []
    monkeypatch.setattr(server.mcp, "run", lambda: used.append("stdio"))
    monkeypatch.setattr(server, "serve_http", lambda: used.append("http"))
    if transport is None:
        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
    else:
        monkeypatch.setenv("MCP_TRANSPORT", transport)
    server.main()
    assert used == [expected]


def test_serve_http_requires_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP mode refuses to start without API keys."""
    monkeypatch.delenv("MCP_API_KEYS", raising=False)
    with pytest.raises(SystemExit):
        server.serve_http()


def test_serve_http_runs_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP mode wraps the app in auth and honours HOST/PORT."""
    import uvicorn

    from finance_mcp.auth import ApiKeyMiddleware

    seen: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        """Record what uvicorn would have been started with.

        Args:
            app: The ASGI app.
            **kwargs: uvicorn options.
        """
        seen.update(app=app, **kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    # serve_http mutates the shared server settings; restore them afterwards
    monkeypatch.setattr(
        server.mcp.settings,
        "transport_security",
        server.mcp.settings.transport_security,
    )
    monkeypatch.setenv("MCP_API_KEYS", f"alice:{TOKEN}")
    monkeypatch.setenv("PORT", "9999")
    monkeypatch.delenv("HOST", raising=False)
    server.serve_http()
    assert isinstance(seen["app"], ApiKeyMiddleware)
    assert seen["host"] == "0.0.0.0" and seen["port"] == 9999
    assert seen["access_log"] is False  # ?key=<token> must not reach the logs
    assert not server.mcp.settings.transport_security.enable_dns_rebinding_protection  # type: ignore[union-attr]


def test_module_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """``python -m finance_mcp`` calls ``server.main``."""
    called: list[bool] = []
    monkeypatch.setattr(server, "main", lambda: called.append(True))
    runpy.run_module("finance_mcp", run_name="__main__")
    assert called == [True]
