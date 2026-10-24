"""Finance MCP server: Yahoo Finance (prices, quotes) + justETF (ETF details).

Run with ``uv run finance-mcp`` or ``python -m finance_mcp``.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .justetf.tools import register as register_justetf
from .yahoo.tools import register as register_yahoo

mcp = FastMCP("finance")
register_yahoo(mcp)
register_justetf(mcp)


def main() -> None:
    """Start the server on the stdio transport."""
    mcp.run()


if __name__ == "__main__":
    main()
