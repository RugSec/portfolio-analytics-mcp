# User guide

This guide covers what each tool does, how the pieces fit together, and how
to configure and deploy the server. For installation, see the
[README](../README.md#quickstart).

- [How it works](#how-it-works)
- [Identifying what you hold](#identifying-what-you-hold)
- [Tools](#tools)
- [Example workflows](#example-workflows)
- [Errors](#errors)
- [Configuration](#configuration)
- [Remote deployment (HTTP)](#remote-deployment-http)
- [Limitations](#limitations)
- [Data sources and fair use](#data-sources-and-fair-use)

## How it works

You ask Claude a question. Claude chooses tools from this server, calls them
with the right inputs, and turns the results into an answer. All tools are
read-only: they fetch and compute, never trade or change anything.

The tools fall into three groups:

- **Portfolio tools** combine both data sources: they turn ISINs into Yahoo
  tickers and analyse a whole portfolio in one base currency.
- **justETF tools** describe ETFs: costs, size, structure and what they hold.
- **Yahoo tools** cover market data for any stock, ETF, index or currency.

Results that took a lot of work to fetch are cached: justETF profiles for 24
hours, Yahoo metadata (currency, time zone) for the lifetime of the server.

## Identifying what you hold

Most questions start with "which security is this?". There are two kinds of
identifier:

- **ISIN** (e.g. `IE00B4L5Y983`): identifies a fund or share, whatever the
  exchange. It's on your broker statement and the fund's KID. justETF tools
  need ISINs.
- **Yahoo symbol** (e.g. `EUNL.DE`, `IWDA.AS`, `AAPL`): one listing on one
  exchange. Non-US listings carry an exchange suffix: `.DE` Xetra, `.AS`
  Amsterdam, `.L` London, `.SW` SIX, `.PA` Paris, `.MI` Milan.

The same ETF can trade on many exchanges in different currencies, so the
tools ask Claude to **confirm with you which listing you hold** when it is
ambiguous. `resolve_instrument` turns an ISIN into ranked Yahoo symbols, and
`analyze_portfolio_risk` accepts ISINs directly.

## Tools

### Portfolio (start here for portfolio questions)

| Tool                     | What it does                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `analyze_portfolio_risk` | Up to 30 positions, each `{symbol or isin, quantity or value}`, stocks and ETFs mixed. Everything is converted to `base_currency` (default EUR) with daily FX and put on a common calendar. Returns value and weights, return, volatility, Sharpe/Sortino/Calmar, max drawdown with dates, beta/alpha/tracking error vs an optional `benchmark`, each position's share of the risk, a correlation matrix and the diversification ratio. |
| `resolve_instrument`     | ISIN to ranked Yahoo symbols. ETFs are mapped from their justETF exchange listings; other ISINs (e.g. single stocks) fall back to Yahoo search. Listings in your currency rank first.                                                                                                                                                                                                                                                   |

Use `analyze_portfolio` (justETF, below) alongside it for costs and
look-through exposure of the ETFs.

### ETFs (justETF, by ISIN)

| Tool                  | What it does                                                                                                                                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_etf`          | Name, ticker or index to ISIN, e.g. "vanguard all world acc". Use this first when you don't know the ISIN.                                                                                                        |
| `get_etf_profile`     | TER, fund size, accumulating/distributing, replication, index, currency and hedging, domicile, provider, legal and tax details.                                                                                   |
| `get_etf_exposure`    | Country, sector and top-10 holdings breakdown.                                                                                                                                                                    |
| `get_etf_performance` | Period and calendar-year returns, volatility, return per risk, max drawdown.                                                                                                                                      |
| `get_etf_listings`    | Exchanges, trading currencies, tickers, Bloomberg/Reuters codes.                                                                                                                                                  |
| `get_similar_etfs`    | Other ETFs on the same index with their size and TER.                                                                                                                                                             |
| `compare_etfs`        | Side-by-side table for up to 15 ETFs, with the cheapest and largest.                                                                                                                                              |
| `analyze_portfolio`   | For a list of `{isin, amount}`: weighted TER and yearly fees, fund sizes (small funds flagged), structure mix, combined country/sector exposure with each ETF's contribution, and top-stock overlap between ETFs. |

### Markets (Yahoo Finance, by symbol)

| Tool                        | What it does                                                                                                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `search_symbol`             | Company or fund name (or ISIN) to candidate symbols on different exchanges.                                                                                         |
| `get_symbol_info`           | Name, exchange, currency, type, sector of a symbol.                                                                                                                 |
| `get_quote`                 | Latest price, previous close, day change, currency, exchange.                                                                                                       |
| `get_price_history`         | Adjusted closing prices, optionally converted to a `base_currency`. Long series are thinned to about 400 points.                                                    |
| `get_performance_stats`     | Total and annualised return, volatility, Sharpe, Sortino, Calmar, max drawdown with dates; optional `benchmark` for beta, alpha, tracking error, information ratio. |
| `get_correlation`           | Correlation matrix of returns on a common calendar (weekly by default).                                                                                             |
| `get_fx_rates`              | Latest FX rates into a base currency, with optional change since a date.                                                                                            |
| `get_dividends`             | Dividend history plus the trailing-12-month total.                                                                                                                  |
| `get_etf_holdings`          | Top holdings of a fund (Yahoo usually has about 10). For European ETFs prefer `get_etf_exposure`.                                                                   |
| `get_etf_sector_allocation` | Sector weights of a fund. For European ETFs prefer `get_etf_exposure`.                                                                                              |

## Example workflows

**"Is my portfolio diversified?"**

1. `analyze_portfolio_risk` with your positions and `benchmark: "IWDA.AS"`:
   volatility, risk contribution per position, correlations, diversification
   ratio.
2. `analyze_portfolio` with the ETF ISINs and amounts: country and sector
   exposure, and which stocks appear in several ETFs.

**"Is there a cheaper ETF for the same index?"**

1. `search_etf` with the fund name, to get the ISIN.
2. `get_similar_etfs` with that ISIN: same-index funds with TER and size.
3. `compare_etfs` on the shortlist.

**"How did my stocks do in euros?"**

`get_performance_stats` with the symbols and `base_currency: "EUR"`, so
currency moves are included, the way a euro investor experiences them.

### Good to know when reading results

- `analyze_portfolio_risk` defaults to **weekly** returns over **3 years**.
  Daily returns understate correlation and beta between US and European
  markets, because they close hours apart; the tools warn when this applies.
- `method: "current_holdings"` (default) assumes you held today's units over
  the whole window. `"constant_weights"` assumes you rebalanced to today's
  weights every period.
- Exposure from justETF is a **lower bound** per country or sector: justETF
  itemises only the largest ~10 countries and sectors and the top 10
  holdings, and groups the rest as "Other".
- Prices are adjusted for splits and dividends, so returns are total returns.

## Errors

Failures come back as data, not exceptions, so Claude can explain them or try
something else:

```json
{
  "error": "Yahoo returned no data for: VWCE.",
  "error_code": "no_data",
  "hint": "Check the symbol with search_symbol (non-US listings need an exchange suffix, e.g. VWCE.DE, ...)"
}
```

| `error_code`           | Meaning                                                                       |
| ---------------------- | ----------------------------------------------------------------------------- |
| `invalid_input`        | Bad argument, e.g. an invalid ISIN or currency code.                          |
| `no_data`              | The source answered but had nothing for this symbol, ISIN or date range.      |
| `upstream_unavailable` | Yahoo or justETF could not be reached, or refused the request. Retry later.   |
| `fx_unavailable`       | No exchange rate for a needed currency pair.                                  |
| `insufficient_data`    | Too few prices for statistics; use an earlier start date or a finer interval. |

The justETF tools return `{"error": ...}` with a plain message.

## Configuration

Everything works without configuration. These environment variables change
the defaults:

| Variable                  | Default                                    | What it does                                              |
| ------------------------- | ------------------------------------------ | --------------------------------------------------------- |
| `JUSTETF_MIN_INTERVAL_S`  | `1.5`                                      | Minimum seconds between requests to justETF.              |
| `JUSTETF_CACHE_TTL_HOURS` | `24`                                       | How long a fetched ETF profile is reused.                 |
| `JUSTETF_CACHE_DIR`       | `~/.cache/portfolio-analytics-mcp/justetf` | Where profiles and the learned ETF registry are stored.   |
| `MCP_TRANSPORT`           | `stdio`                                    | `http` to serve over HTTP instead (see below).            |
| `MCP_API_KEYS`            | (none)                                     | Required with `http`: comma-separated `name:token` pairs. |
| `HOST` / `PORT`           | `0.0.0.0` / `8000`                         | Address of the HTTP server.                               |

**Finding ETFs by name.** justETF has no search the server may use (its
search endpoint is disallowed by robots.txt), and Yahoo cannot return ISINs.
So the server ships a small list of popular ETFs and learns every ETF you
look up (with its tickers and the "similar ETFs" on its page) in a local
registry inside the cache directory. If `search_etf` doesn't know a fund,
give Claude the ISIN once and it is remembered.

## Remote deployment (HTTP)

By default the server talks to one local client over stdio. To share it (for
example with Claude on your phone, or a few friends), serve it over HTTP:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # make a token
MCP_TRANSPORT=http MCP_API_KEYS="me:<token>,alice:<token>" uv run python -m finance_mcp
```

- The MCP endpoint is `/mcp`. Every request needs a key, as
  `Authorization: Bearer <token>` or, for clients that only accept a URL,
  `https://<host>/mcp?key=<token>` (the token then appears in URL logs, so
  treat that URL as a secret).
- Give each person their own `name:token` pair (tokens of 16+ characters) so
  you can revoke one without affecting the others.
- `/health` is the only path without authentication.
- The server refuses to start in HTTP mode without `MCP_API_KEYS`.

**Render.** [render.yaml](../render.yaml) has the settings: create a Web
Service from your fork and set `MCP_API_KEYS` in the dashboard. Then connect:

```bash
claude mcp add --transport http finance https://<app>.onrender.com/mcp \
  --header "Authorization: Bearer <token>"
```

The server is stateless, so restarts don't break clients. On hosts without a
persistent disk the justETF cache starts empty after each restart.

## Limitations

- **yfinance is unofficial.** Yahoo can rate-limit bursts or change its API.
  If calls start failing, update it: `uv lock --upgrade-package yfinance && uv sync`.
- Quotes can be delayed by up to ~15-20 minutes depending on the exchange.
- Dividends are per share as Yahoo reports them, which can be the fund's
  distribution currency rather than the listing's trading currency.
- Yahoo's holdings and sector data for European UCITS ETFs is often partial;
  use the justETF tools for those.
- justETF itemises only the top ~10 countries, ~13 sectors and top 10
  holdings, so look-through exposure is a lower bound.
- If justETF changes its page layout, affected fields come back empty
  (`null`) with a warning instead of breaking the whole profile.

## Data sources and fair use

This project does not own or license any market data. It fetches public
pages on demand, for personal use:

- **Yahoo Finance**, through [yfinance](https://pypi.org/project/yfinance/),
  an unofficial library intended for personal and research use.
- **justETF** profile pages (`/en/etf-profile.html`, allowed by robots.txt).
  Requests use an honest User-Agent, are at least 1.5 seconds apart, are
  cached for 24 hours, are limited to 15 ETFs per call, and are only made for
  valid ISINs. A refusal (HTTP 403 or 429) is respected, not retried.

Don't use this server for bulk crawling, scheduled downloads or
redistributing the data, and check each site's terms of use.
