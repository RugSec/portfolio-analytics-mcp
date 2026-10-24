# Contributing

Thanks for your interest! Bug reports, fixes and new tools are welcome.
Please open an issue first for larger changes, so we can agree on the
approach.

## Setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11+. Formatting
Markdown and YAML also needs [Node.js](https://nodejs.org) (Prettier runs
through `npx`, nothing to install).

```bash
git clone https://github.com/RugSec/portfolio-analytics-mcp.git
cd portfolio-analytics-mcp
uv sync                     # creates .venv with runtime + dev dependencies
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

## Tasks

Tasks run with [poe](https://poethepoet.natn.io/) (`poe -h` lists them):

| Command            | What it does                                                       |
| ------------------ | ------------------------------------------------------------------ |
| `poe ci-checks`    | Everything CI runs, read-only: format-check, lint, typecheck, test |
| `poe test`         | Tests with coverage; fails below 80%                               |
| `poe format`       | Format Python (ruff) and Markdown/YAML (Prettier), sort imports    |
| `poe fix`          | Format, then lint                                                  |
| `poe format-check` | Check formatting without writing files                             |
| `poe lint`         | Lint with ruff (style, docstrings, type hints)                     |
| `poe typecheck`    | Type check with basedpyright                                       |
| `poe check`        | Quick check: lint + typecheck                                      |

**Run `poe ci-checks` before opening a pull request.** GitHub Actions runs
the same command on Python 3.11, 3.12 and 3.13.

To try the tools interactively, use the MCP inspector:
`mcp dev finance_mcp/server.py`. To check that Yahoo is reachable from your
machine:

```bash
uv run python -c "from finance_mcp.yahoo.tools import get_quote; print(get_quote(['AAPL']))"
```

## Project layout

```
finance_mcp/
  server.py          builds the FastMCP server and registers all tools
  auth.py            API-key middleware for the HTTP transport
  yahoo/
    analytics.py     return/risk maths: pure pandas/numpy, no network
    data.py          yfinance downloads, currencies, FX, error classification
    tools.py         Yahoo MCP tools
  justetf/
    client.py        polite HTTP: rate limit, retries, disk cache, ISIN check
    parser.py        profile page HTML -> dict (stable data-testid hooks)
    service.py       fetch + parse + cache, the tools' single entry point
    registry.py      local name/ticker -> ISIN registry (seed + learned)
    search.py        ETF search: ISIN, registry, then Yahoo fallback
    analysis.py      ETF portfolio maths: pure functions, no network
    tools.py         justETF MCP tools
    data/etfs.json   seed registry of popular ETFs
  portfolio/
    resolve.py       ISIN -> Yahoo symbols via justETF listings
    risk.py          whole-portfolio risk in one base currency
    tools.py         portfolio MCP tools
tests/               mirrors finance_mcp/ (tests/yahoo, tests/justetf, ...)
  conftest.py        fixtures that fake Yahoo and justETF
  fakes.py           synthetic prices, pages and profiles
```

The pattern in each package: network code (`data.py`, `client.py`) is
separate from pure logic (`analytics.py`, `parser.py`, `analysis.py`), and
`tools.py` only adapts inputs and outputs for the MCP client.

## Conventions

- **Tests never touch the network.** Fake Yahoo and justETF with the
  fixtures in `tests/conftest.py` (`fake_yahoo`, `fake_yf`, `registry_env`)
  or with `monkeypatch`. Put a module's tests in the matching file under
  `tests/`, e.g. `finance_mcp/justetf/parser.py` in
  `tests/justetf/test_parser.py`.
- **Coverage stays at or above 80%** (branch coverage); CI fails below it.
- **Type hints on every function**, checked by basedpyright.
- **Docstrings on every function** in Google style: a one-line summary, then
  `Args:`, `Returns:` and `Raises:` sections as they apply. Test functions
  only need the one-line summary. Ruff enforces this.
- **Tool docstrings are read by the LLM.** They are the tool's description,
  so say when to use the tool, what it needs and what comes back, and keep
  them short.
- **Tools return errors, they don't raise them.** Return
  `YahooError(...).to_dict()` (with an `error_code` from the
  [user guide](docs/USER_GUIDE.md#errors)) or `{"error": ...}`, so the agent
  can explain the failure or try another tool.
- **Be polite to data sources.** New justETF requests go through
  `client._get` (rate limit + retries) and the cache; never retry a 403/429.

## Dependencies

Dependencies are declared in `pyproject.toml` and locked in `uv.lock`.

- `mcp` is pinned below 2 because the code uses the v1 `FastMCP` API.
- `pandas` is pinned exactly, with a matching `pandas-stubs` in the dev
  group: bump both together.
- Dependabot opens monthly update PRs for Python packages and GitHub
  Actions.
