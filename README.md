# Portfolio Analytics MCP

[![CI](https://github.com/RugSec/portfolio-analytics-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/RugSec/portfolio-analytics-mcp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**Ask Claude about your investments in plain language.** This is an
[MCP](https://modelcontextprotocol.io) server that gives Claude (or any MCP
client) read-only tools for market data and portfolio analysis: prices, FX,
ETF costs and exposure, and risk for a whole portfolio of stocks and ETFs,
measured in your own currency.

It is built for European investors as much as US ones: it understands ISINs,
UCITS ETFs listed on several exchanges, and prices quoted in pence.

## What you can ask

> "I hold 30k EUR of IE00B4L5Y983, 10 ASML.AS and 25 AAPL. How volatile is
> this portfolio, and which position contributes most to the risk?"

> "Compare the costs of the iShares Core MSCI World and the Vanguard FTSE
> All-World. Which is cheaper and bigger?"

> "How much of my ETF portfolio is in US tech stocks? Do my ETFs overlap?"

> "What has VWCE returned since 2021 in euros, compared with the S&P 500?"

Claude picks the right tools, fetches the data and explains the result.

## What's inside

| Area          | What it gives you                                                                                      | Data source                                |
| ------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------ |
| **Portfolio** | Risk and return of a mixed portfolio in one currency: volatility, drawdown, beta, risk per position    | Yahoo Finance + justETF                    |
| **ETFs**      | Costs (TER), fund size, country/sector/stock exposure, listings, similar funds, portfolio look-through | [justETF](https://www.justetf.com)         |
| **Markets**   | Price history, quotes, FX rates, performance statistics, correlations, dividends                       | [Yahoo Finance](https://finance.yahoo.com) |

20 tools in total, all read-only. No API key or account needed. See the
[user guide](docs/USER_GUIDE.md) for the full list.

## Quickstart

You need [uv](https://docs.astral.sh/uv/getting-started/installation/) and
Python 3.12.

**1. Install**

```bash
git clone https://github.com/RugSec/portfolio-analytics-mcp.git
cd portfolio-analytics-mcp
uv sync
```

**2. Connect it to Claude**

Claude Code:

```bash
claude mcp add finance -- /absolute/path/to/portfolio-analytics-mcp/.venv/bin/python -m finance_mcp
```

Claude Desktop: add this to `claude_desktop_config.json`, then restart the
app. On Windows use `.venv\\Scripts\\python.exe`.

```json
{
  "mcpServers": {
    "finance": {
      "command": "/absolute/path/to/portfolio-analytics-mcp/.venv/bin/python",
      "args": ["-m", "finance_mcp"]
    }
  }
}
```

**3. Ask a question**, for example _"What is the TER of IE00B4L5Y983?"_

Want to run it as a shared remote server instead? See
[Remote deployment](docs/USER_GUIDE.md#remote-deployment-http).

## Important to know

- **Not financial advice.** The tools report data and statistics; past
  performance does not predict future results.
- **Personal use only.** Yahoo Finance (through the unofficial
  [yfinance](https://pypi.org/project/yfinance/) library) and justETF are
  third-party sites. This server makes polite, on-demand requests
  (rate-limited and cached) and is not meant for bulk downloads or
  redistributing their data. Check their terms before using it.
- Quotes can be delayed by up to ~20 minutes, and Yahoo's coverage of
  European ETF holdings is patchy (the justETF tools fill that gap).

## Learn more

- [User guide](docs/USER_GUIDE.md): every tool, example workflows,
  configuration, remote deployment and limitations.
- [Contributing](CONTRIBUTING.md): development setup, tests and project
  layout.

## License

[MIT](LICENSE)
