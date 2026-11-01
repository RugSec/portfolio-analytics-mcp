---
name: portfolio-analytics
description: >-
  Analyse a personal investment portfolio of stocks and ETFs with the
  Portfolio Analytics MCP server: risk and return in your own currency,
  ETF costs (TER), country/sector exposure, overlap between ETFs, FX and
  price history. Use when the user asks about their holdings, an ETF's costs
  or exposure, comparing ETFs, or how investments performed. Built for
  European (UCITS, ISIN) and US investors. Read-only; not financial advice.
summary: >-
  Ask your agent about your investments in plain language. Volatility,
  drawdown, beta and risk per position for a mixed portfolio, ETF costs and
  look-through exposure from justETF, all in your base currency.
version: 0.1.0
tags: [investing, portfolio, etf, risk, mcp]
keywords:
  [
    portfolio analysis,
    ETF,
    ISIN,
    UCITS,
    TER,
    volatility,
    drawdown,
    Sharpe ratio,
    diversification,
    justETF,
    Yahoo Finance,
  ]
use_cases:
  - How risky is my portfolio and which position contributes most to the risk?
  - Compare the costs and size of two ETFs that track the same index
  - How much of my ETF portfolio is in US tech, and do my ETFs overlap?
  - What has this fund returned since 2021 in euros, against a benchmark?
docs_url: https://github.com/RugSec/portfolio-analytics-mcp/blob/main/docs/USER_GUIDE.md
---

# Portfolio analytics

This skill uses the open-source
[Portfolio Analytics MCP server](https://github.com/RugSec/portfolio-analytics-mcp)
(MIT licence). It provides 20 read-only tools for market data and portfolio
statistics. Nothing here trades, places orders or moves money.

## Setup (once)

The tools come from a local MCP server. If tools such as
`analyze_portfolio_risk` or `get_etf_profile` are not available, help the
user install it. It needs [uv](https://docs.astral.sh/uv/), which downloads
Python 3.12 and the server from PyPI
([`portfolio-analytics-mcp`](https://pypi.org/project/portfolio-analytics-mcp/)).

Each client has its own MCP settings; configure the one the user is in.
`claude mcp add` only configures Claude Code, not the Claude Desktop chat.

Claude Code (`-s user` makes the tools available in every folder):

```bash
claude mcp add -s user portfolio-analytics -- uvx portfolio-analytics-mcp@latest
```

Claude Desktop, Cursor and other clients: add a stdio server named
`portfolio-analytics` with argument `portfolio-analytics-mcp@latest` and, as command,
the **full path** to `uvx` (from `which uvx` on macOS/Linux or `where uvx`
on Windows). Desktop apps don't see the terminal's `PATH`, so a bare `uvx`
usually fails. For Claude Desktop the file is opened from **Settings →
Developer → Edit Config**; tell the user to keep existing entries in
`"mcpServers"`, then quit the app completely and reopen it:

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

The tools appear only after the client restarts or in a new session. The
first start downloads Python and the dependencies and can take a minute.

No account or API key is needed. The server runs on the user's machine and
updates itself to the latest release when it starts.

## Network access and privacy

The server contacts only:

- PyPI (`pypi.org`, `files.pythonhosted.org`), through uv, to install and
  update the server.
- Yahoo Finance (`*.finance.yahoo.com`), through the unofficial `yfinance`
  library, for prices, quotes, FX rates and fund data.
- justETF (`www.justetf.com`), ETF profile pages, rate-limited and cached for
  24 hours.

Only symbols and ISINs are sent. Quantities, amounts and any other portfolio
details stay on the user's machine. Nothing is sent to the skill's author.
Both sources are third-party websites used for personal, on-demand lookups;
do not use these tools for bulk downloads or scheduled scraping.

## How to answer: rules

1. **Information, not advice.** Report data and statistics and explain what
   they mean. Do not tell the user to buy, sell or hold a specific security,
   and do not predict prices. If asked "what should I do?", lay out the
   trade-offs the data shows and suggest a licensed financial adviser for a
   personal recommendation.
2. **State the limits** that matter for the answer: quotes may be delayed by
   about 20 minutes, past performance does not predict future results, and
   justETF exposure is a lower bound (top ~10 countries/sectors, top 10
   holdings only).
3. **Confirm the listing.** One ETF trades on many exchanges in different
   currencies. When an ISIN maps to several Yahoo symbols, ask which one the
   user holds rather than guessing.
4. **Use the user's currency.** Pass `base_currency` (for example `EUR`,
   `GBP`, `CHF`, `USD`) so FX moves are included the way the user
   experiences them.
5. **Errors come back as data** with an `error_code` and a `hint`. Follow the
   hint (for example, add an exchange suffix) before giving up, and do not
   retry `upstream_unavailable` in a loop.

## Identifiers

- **ISIN** (`IE00B4L5Y983`): the fund or share, on any exchange. justETF
  tools need ISINs.
- **Yahoo symbol** (`EUNL.DE`, `IWDA.AS`, `AAPL`): one listing on one
  exchange. Suffixes: `.DE` Xetra, `.AS` Amsterdam, `.L` London, `.SW` SIX,
  `.PA` Paris, `.MI` Milan. London prices may be in pence (GBp).

Name to ISIN: `search_etf`. ISIN to Yahoo symbol: `resolve_instrument`.
Name to Yahoo symbol: `search_symbol`.

## Which tool for which question

| Question                                    | Tools                                                           |
| ------------------------------------------- | --------------------------------------------------------------- |
| Risk and return of my whole portfolio       | `analyze_portfolio_risk` (up to 30 positions, ISINs or symbols) |
| Costs, fees and exposure of my ETFs         | `analyze_portfolio` (justETF, `{isin, amount}`)                 |
| One ETF: TER, size, structure, domicile     | `get_etf_profile`                                               |
| One ETF: countries, sectors, top holdings   | `get_etf_exposure`                                              |
| Cheaper fund on the same index              | `get_similar_etfs`, then `compare_etfs` (up to 15)              |
| Where an ETF trades, tickers                | `get_etf_listings`                                              |
| How an investment performed, vs a benchmark | `get_performance_stats` with `base_currency` and `benchmark`    |
| Price chart data                            | `get_price_history`                                             |
| Latest prices, FX rates, dividends          | `get_quote`, `get_fx_rates`, `get_dividends`                    |
| Do these move together?                     | `get_correlation`                                               |

For European ETFs prefer the justETF tools (`get_etf_exposure`) over Yahoo's
`get_etf_holdings` and `get_etf_sector_allocation`, which are often partial.

## Workflows

**"Is my portfolio diversified?"**

1. Collect the positions: ISIN or symbol, and quantity or value. Ask for the
   base currency if it is unclear.
2. `analyze_portfolio_risk` with a broad benchmark (for example `IWDA.AS` for
   world equities). Report volatility, max drawdown, each position's share of
   the risk, the most correlated pairs and the diversification ratio.
3. `analyze_portfolio` with the ETF ISINs and amounts: combined country and
   sector exposure, and stocks held by several ETFs.
4. Summarise concentrations and overlaps factually.

**"Is there a cheaper ETF for the same index?"**

1. `search_etf` with the fund name to get its ISIN.
2. `get_similar_etfs`, then `compare_etfs` on the shortlist.
3. Present TER, fund size and structure (accumulating or distributing,
   replication, domicile) side by side. Note that the user decides; costs are
   one factor among tax treatment, tracking and liquidity.

## Reading the results

- `analyze_portfolio_risk` defaults to weekly returns over 3 years. Daily
  returns understate correlation between US and European markets, which close
  hours apart.
- `method: "current_holdings"` (default) assumes today's units were held over
  the whole window; `"constant_weights"` assumes rebalancing to today's
  weights every period.
- Prices are adjusted for splits and dividends, so returns are total returns.

## Disclaimer

This skill and the server provide information for educational and personal
use only. They are not investment, tax or legal advice, and not a
recommendation to buy or sell any security. Data comes from third parties,
can be delayed, incomplete or wrong, and is provided as is, without warranty.
The author is not affiliated with Yahoo, justETF or any fund provider.
