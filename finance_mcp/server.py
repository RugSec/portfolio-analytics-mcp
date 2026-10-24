"""Finance MCP server: Yahoo Finance (prices, quotes) + justETF (ETF details)
and cross-source portfolio tools (ISIN resolution, portfolio risk).

Run with ``uv run finance-mcp`` or ``python -m finance_mcp`` (stdio). Set
``MCP_TRANSPORT=http`` to serve streamable HTTP with API-key auth instead.
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from finance_mcp.auth import ApiKeyMiddleware, load_keys
from finance_mcp.justetf.tools import register as register_justetf
from finance_mcp.portfolio.tools import register as register_portfolio
from finance_mcp.yahoo.tools import register as register_yahoo

mcp = FastMCP("finance", stateless_http=True)
register_yahoo(mcp)
register_justetf(mcp)
register_portfolio(mcp)


@mcp.custom_route("/health", methods=["GET"])
async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


def serve_http() -> None:
    """Serve streamable HTTP at ``/mcp``; every request needs an API key."""
    import uvicorn

    keys = load_keys()
    if not keys:
        raise SystemExit("MCP_API_KEYS must be set when MCP_TRANSPORT=http")
    app = ApiKeyMiddleware(mcp.streamable_http_app(), keys)
    uvicorn.run(
        app,
        host=os.environ.get("HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


def main() -> None:
    """Start the server on stdio, or on HTTP when ``MCP_TRANSPORT=http``."""
    if os.environ.get("MCP_TRANSPORT", "stdio").lower() in {"http", "streamable-http"}:
        serve_http()
    else:
        mcp.run()


if __name__ == "__main__":
    main()
