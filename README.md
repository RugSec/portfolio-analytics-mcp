# Finance MCP (portfolio analysis)

One MCP server, one Python package (`finance_mcp`), two data sources plus tools that join them:

- `finance_mcp/yahoo/`: prices, quotes, FX, performance, correlation, dividends via
  [yfinance](https://pypi.org/project/yfinance/) (unofficial, personal use only). Data can be delayed (up to ~15-20 min).
  `analytics.py` holds the maths (pure, tested offline), `data.py` the downloads, currencies and FX.
- `finance_mcp/justetf/`: ETF details (costs, size, exposure, search by name) from justETF, see below.
- `finance_mcp/portfolio/`: ISIN -> Yahoo ticker resolution and whole-portfolio risk in one base currency.

`finance_mcp/server.py` builds the server and registers all three. No API key needed. All tools are read-only
(annotated `readOnlyHint`), and failures come back as `{"error", "error_code", "hint"}` with `error_code` one of
`invalid_input`, `no_data`, `upstream_unavailable`, `fx_unavailable`, `insufficient_data`.

## Portfolio tools (start here for portfolio analysis)

| Tool | What it does |
|------|--------------|
| `analyze_portfolio_risk` | Positions as `{symbol or isin, quantity or value}` (stocks and ETFs mixed). Converts everything to `base_currency` with daily FX (pence-quoted London listings handled), aligns calendars, and returns value and weights, return, volatility, Sharpe/Sortino/Calmar, max drawdown with dates, beta/alpha/tracking error vs a `benchmark`, per-position risk contribution, correlation matrix and diversification ratio. Warns about short histories and stale quotes. |
| `resolve_instrument` | ISIN -> ranked Yahoo tickers. ETFs via their justETF exchange listings (XETRA -> `.DE`, Amsterdam -> `.AS`, London -> `.L`, SIX -> `.SW`, ...), other ISINs via Yahoo search. |

Use `analyze_portfolio` (justETF) alongside it for costs and country/sector/stock look-through of the ETFs.

## Yahoo tools

| Tool | What it does |
|------|--------------|
| `get_price_history` | Adjusted close prices for one or more tickers, optionally converted to `base_currency`. Default 2020-01-01 to latest; `interval` 1d/1wk/1mo. Long series are thinned to ~400 points. |
| `search_symbol` | Company/ETF name or ISIN -> several ticker candidates (exchange, type). The LLM should ask you which listing you hold. |
| `get_symbol_info` | Ticker -> name, exchange, currency, type, sector. |
| `get_etf_sector_allocation` | Sector weights (%) of an ETF (patchy for UCITS ETFs; prefer `get_etf_exposure`). |
| `get_etf_holdings` | Top holdings with % weight (Yahoo usually exposes ~10 only). |
| `get_quote` | Latest price, previous close, change %, currency (`GBp` = pence), exchange. |
| `get_fx_rates` | Latest FX rates into a base currency, optional change since a date. |
| `get_performance_stats` | Total/annualised return (annualised only for windows of 1y+), volatility scaled to the interval, Sharpe, Sortino, Calmar, max drawdown with dates; optional `base_currency`, `risk_free_rate_pct`, `benchmark` (beta, alpha, tracking error, information ratio). |
| `get_correlation` | Correlation matrix of returns on a common calendar (default weekly), optional `base_currency`. |
| `get_dividends` | Dividend history plus trailing-12-month total and payment count. |

## justETF tools (ETF look-up by ISIN)

Data comes from [justETF](https://www.justetf.com) profile pages. **Personal, on-demand use only**: requests are
rate-limited (1.5s apart, `JUSTETF_MIN_INTERVAL_S`) and parsed results are cached for 24h
(`JUSTETF_CACHE_TTL_HOURS`, cache dir `JUSTETF_CACHE_DIR`, default `~/.cache/yahoo-finance-mcp/justetf`).
No bulk crawling, no redistribution. Plan and design notes: [docs/JUSTETF_PLAN.md](docs/JUSTETF_PLAN.md).

| Tool | What it does |
|------|--------------|
| `search_etf` | **Start here.** Name, ticker, index or ISIN -> ISIN (+ tickers). Local registry first, Yahoo as fallback for fuzzy names; hits it cannot map to an ISIN are returned with `isin: null` rather than guessed. |
| `get_etf_profile` | TER, fund size, acc/dist, replication, index, currency/hedging, domicile, provider, legal + tax info. |
| `get_etf_exposure` | Country, sector and top-10 holdings breakdown of one ETF (rest is "Other"). |
| `get_etf_performance` | Period and calendar-year returns, volatility, return per risk, max drawdown. |
| `get_etf_listings` | Exchanges, trading currencies, tickers, Bloomberg/Reuters codes. |
| `get_similar_etfs` | Other ETFs on the same index with size and TER. |
| `compare_etfs` | Side-by-side table for up to 15 ISINs, with cheapest/largest. |
| `analyze_portfolio` | For `[{isin, amount}]`: weighted TER and yearly fees, fund sizes, structure mix, combined country/sector exposure with per-ETF contribution (filterable), top-stock overlap. |

Name search: justETF's own search is not used (its AJAX endpoint is disallowed by robots.txt) and Yahoo cannot return
ISINs, so `finance_mcp/justetf/data/etfs.json` ships ~28 popular ETFs (each verified against its justETF page), and every
profile you fetch adds the ETF, all its listing tickers and its "similar ETFs" to a local registry
(`<cache dir>/registry.json`). If a fund is unknown, give the ISIN once and it is remembered.

Limits: justETF itemises only the top ~10 countries / ~13 sectors / top 10 holdings, so portfolio exposure per named
bucket is a lower bound. All tests run offline (no network): `uv run pytest`.

## Setup

Requires Python 3.11+. Dependencies are declared in `pyproject.toml` and locked in `uv.lock`, managed with [uv](https://docs.astral.sh/uv/):

```bash
cd yahoo-finance-mcp
uv sync                          # creates .venv and installs runtime + dev dependencies
source .venv/bin/activate        # Windows: .venv\Scripts\activate
```

## Development

Dev tools (ruff, basedpyright, poethepoet) are in the `dev` dependency group. Tasks run with [poe](https://poethepoet.natn.io/):

| Command | What it does |
|---------|--------------|
| `poe format` | Format code and sort imports (writes files) |
| `poe format-check` | Check formatting without writing files |
| `poe lint` | Lint with ruff |
| `poe typecheck` | Type check with basedpyright |
| `poe check` | Quick local check: lint + type check |
| `poe ci` | Everything CI runs, read-only: format-check + lint + typecheck |
| `poe fix` | Format, then lint with auto-fixes |

Run `poe -h` to list them.

Editor setup (VS Code) is in `.vscode/`, which is git-ignored, so it stays local:

- `.vscode/extensions.json` recommends Ruff, basedpyright and Emeraldwalk.
- Ruff formats on save, and Emeraldwalk runs `ruff format` and import sorting on every saved `.py` file.

Quick check that Yahoo is reachable from your machine:

```bash
uv run python -c "from finance_mcp.yahoo.tools import get_quote; print(get_quote(['AAPL','ASML.AS']))"
```

Inspect the tools interactively:

```bash
mcp dev finance_mcp/server.py
```

## Connect to Claude Desktop

Add this to `claude_desktop_config.json` (use absolute paths):

```json
{
  "mcpServers": {
    "finance": {
      "command": "/absolute/path/to/yahoo-finance-mcp/.venv/bin/python",
      "args": ["-m", "finance_mcp"]
    }
  }
}
```

On Windows use `.venv\\Scripts\\python.exe` with double backslashes. Restart Claude Desktop afterwards.

For Claude Code: `claude mcp add finance -- /absolute/path/to/.venv/bin/python -m finance_mcp`

## Notes and limitations

- Use Yahoo exchange suffixes: `ASML.AS` (Amsterdam), `VWCE.DE` (Xetra), `SAP.DE`, `AAPL` (US).
- Prices are in each listing's local currency unless you pass `base_currency`; `analyze_portfolio_risk` always converts.
- Dividends are per share as Yahoo reports them, which can be the fund's distribution currency rather than the listing's.
- ETF holdings/sector data on Yahoo is often partial for European UCITS ETFs.
- yfinance is unofficial: Yahoo can rate limit bursts or change things and break it. Run `uv lock --upgrade-package yfinance && uv sync` if calls start failing.
- `mcp` is pinned to `<2` because this code uses the v1 `FastMCP` API.
- `pandas` is pinned exactly to `3.0.6` (with a matching `pandas-stubs` in the dev group). Bump both together.
