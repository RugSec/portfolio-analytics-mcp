"""Finance MCP server: Yahoo Finance (prices, quotes) + justETF (ETF details)
and cross-source portfolio tools (ISIN resolution, portfolio risk).

Run with ``uv run finance-mcp`` or ``python -m finance_mcp``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from finance_mcp.justetf.tools import register as register_justetf
from finance_mcp.portfolio.tools import register as register_portfolio
from finance_mcp.yahoo.tools import register as register_yahoo

mcp = FastMCP("finance")
register_yahoo(mcp)
register_justetf(mcp)
register_portfolio(mcp)


def main() -> None:
    """Start the server on the stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
