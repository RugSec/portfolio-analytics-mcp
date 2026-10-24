# Finance MCP (portfolio analysis)

One MCP server, one Python package (`finance_mcp`), two data sources:

- `finance_mcp/yahoo/`: prices, quotes, performance, correlation, dividends via
  [yfinance](https://pypi.org/project/yfinance/) (unofficial, personal use only). Data can be delayed (up to ~15-20 min).
- `finance_mcp/justetf/`: ETF details (costs, size, exposure, search by name) from justETF, see below.

`finance_mcp/server.py` builds the server and registers both. No API key needed.

## Tools

| Tool | What it does |
|------|--------------|
| `get_price_history` | Adjusted close prices for one or more tickers. Default 2020-01-01 to latest; optional `start_date`, `end_date`, `interval` (1d/1wk/1mo). Long series are thinned to ~400 points. |
| `search_symbol` | Company/ETF name -> several ticker candidates (exchange, type). The LLM should ask you which listing you hold. |
| `get_symbol_info` | Ticker -> name, exchange, currency, type, sector. |
| `get_etf_sector_allocation` | Sector weights (%) of an ETF. |
| `get_etf_holdings` | Top holdings with % weight (Yahoo usually exposes ~10 only). |
| `get_quote` | Latest price, previous close, change %, currency, exchange. |
| `get_performance_stats` | Total return, annualized return, volatility, max drawdown. |
| `get_correlation` | Correlation matrix of returns (default weekly). |
| `get_dividends` | Dividend history. |

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
bucket is a lower bound. Tests run offline: `uv run pytest`.

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
- Prices are in each listing's local currency; correlations across currencies are affected by FX.
- ETF holdings/sector data on Yahoo is often partial for European UCITS ETFs.
- yfinance is unofficial: Yahoo can rate limit bursts or change things and break it. Run `uv lock --upgrade-package yfinance && uv sync` if calls start failing.
- `mcp` is pinned to `<2` because this code uses the v1 `FastMCP` API.
- `pandas` is pinned exactly to `3.0.6` (with a matching `pandas-stubs` in the dev group). Bump both together.
