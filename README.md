# Portfolio Analytics MCP

[![PyPI](https://img.shields.io/pypi/v/portfolio-analytics-mcp.svg)](https://pypi.org/project/portfolio-analytics-mcp/)
[![CI](https://github.com/RugSec/portfolio-analytics-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/RugSec/portfolio-analytics-mcp/actions/workflows/ci.yml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/LICENSE)

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
[user guide](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/docs/USER_GUIDE.md) for the full list.

## Quickstart

You need [uv](https://docs.astral.sh/uv/getting-started/installation/). It
downloads Python 3.12, the server and its dependencies on first run, and
checks for a new release each time the server starts.

**1. Connect it to Claude**

Claude Code and Claude Desktop keep separate settings: set up each app you
use.

**Claude Code** (terminal and IDE extensions):

```bash
claude mcp add -s user portfolio-analytics -- uvx portfolio-analytics-mcp@latest
```

`-s user` makes the tools available in every folder; without it they only
appear in the folder where you ran the command. Check with `claude mcp list`.

**Claude Desktop** (the chat app):

1. Find the full path of `uvx`: run `which uvx` (macOS/Linux) or
   `where uvx` (Windows). Desktop apps don't see your terminal's `PATH`, so a
   bare `uvx` usually fails.
2. Open the config file: in Claude Desktop, **Settings → Developer → Edit
   Config**. It is `~/Library/Application Support/Claude/claude_desktop_config.json`
   on macOS and `%APPDATA%\Claude\claude_desktop_config.json` on Windows.
3. Add a `portfolio-analytics` entry inside `"mcpServers"`, using your path from step 1.
   If the file already has other servers or settings, keep them and add
   `portfolio-analytics` next to them (mind the commas).

   ```json
   {
     "mcpServers": {
       "portfolio-analytics": {
         "command": "/opt/homebrew/bin/uvx",
         "args": ["portfolio-analytics-mcp@latest"]
       }
     }
   }
   ```

   On Windows, write the path with double backslashes, e.g.
   `"C:\\Users\\you\\.local\\bin\\uvx.exe"`.

4. Quit Claude Desktop completely (Cmd+Q on macOS, or Quit from the tray icon
   on Windows; closing the window is not enough) and open it again. The
   `portfolio-analytics` tools appear in new chats.

If the tools don't appear, **Settings → Developer** shows the server's
status, and its log is `~/Library/Logs/Claude/mcp-server-portfolio-analytics.log`
(macOS) or `%APPDATA%\Claude\logs\mcp-server-portfolio-analytics.log` (Windows). The
first start downloads Python and the dependencies and can take a minute; if
it times out, restart the app once.

To stay on one version instead of updating automatically, use
`portfolio-analytics-mcp==0.2.0` in place of `portfolio-analytics-mcp@latest`.

The server runs on your machine. Only symbols and ISINs go out, to Yahoo
Finance and justETF; your quantities and amounts never leave it.

**2. Ask a question**, for example _"What is the TER of IE00B4L5Y983?"_

To work on the code instead, see [Contributing](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/CONTRIBUTING.md#setup).

Want to run it as a shared remote server instead? See
[Remote deployment](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/docs/USER_GUIDE.md#remote-deployment-http).

## Important to know

- **Not financial advice.** The tools report data and statistics; past
  performance does not predict future results. Data can be delayed,
  incomplete or wrong, and is provided as is, without warranty.
- **Not affiliated** with Yahoo, justETF or any fund provider. Names and
  trademarks belong to their owners.
- **Personal use only.** Yahoo Finance (through the unofficial
  [yfinance](https://pypi.org/project/yfinance/) library) and justETF are
  third-party sites. This server makes polite, on-demand requests
  (rate-limited and cached) and is not meant for bulk downloads or
  redistributing their data. Check their terms before using it.
- Quotes can be delayed by up to ~20 minutes, and Yahoo's coverage of
  European ETF holdings is patchy (the justETF tools fill that gap).

## Learn more

- [User guide](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/docs/USER_GUIDE.md): every tool, example workflows,
  configuration, remote deployment and limitations.
- [Agent skill](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/skill/portfolio-analytics/SKILL.md): tells an agent when
  and how to use the tools, and how to present results.
- [Contributing](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/CONTRIBUTING.md): development setup, tests and project
  layout.

## License

[MIT](https://github.com/RugSec/portfolio-analytics-mcp/blob/main/LICENSE)
