# justETF extension: plan

Goal: let an agent answer specific questions about ETFs from justETF, and analyse a
list of ETFs (cost, size, exposure to countries/sectors/stocks).

## What users are likely to ask

| # | Question type | Example | Tool |
|---|---------------|---------|------|
| 0 | Find the ETF | "ISIN of the iShares MSCI World Acc?", "IWDA", "Vanguard all world" | `search_etf` |
| 1 | Basic facts | "TER, fund size, replication, accumulating or distributing, domicile, index of IE00B4L5Y983?" | `get_etf_profile` |
| 2 | Costs and size | "How expensive / big is this ETF?" | `get_etf_profile`, `compare_etfs` |
| 3 | Geographic exposure | "How much US / emerging markets is in it?" | `get_etf_exposure` |
| 4 | Sector exposure | "How much technology / finance?" | `get_etf_exposure` |
| 5 | Top holdings | "Is Nvidia in there? Weight of the top 10?" | `get_etf_exposure` |
| 6 | Performance and risk | "YTD, 1y, 3y, 5y return, volatility, max drawdown, per calendar year" | `get_etf_performance` |
| 7 | Where to buy | "Which exchanges / tickers / currencies?" (Xetra, LSE, ...) | `get_etf_listings` |
| 8 | Alternatives | "Cheaper ETFs on the same index?" | `get_similar_etfs` |
| 9 | Side-by-side | "Compare these 3 ETFs" | `compare_etfs` |
| 10 | Portfolio: cost | "Weighted TER and yearly fees on my 3 ETFs with these amounts" | `analyze_portfolio` |
| 11 | Portfolio: size | "Fund size of each ETF; any tiny/closing-risk fund?" | `analyze_portfolio` |
| 12 | Portfolio: exposure | "How exposed am I to US / tech overall? Which ETF contributes most?" | `analyze_portfolio` |
| 13 | Portfolio: overlap | "Do my ETFs hold the same stocks?" | `analyze_portfolio` (top-10 look-through) |
| 14 | Portfolio: structure | "Mix of acc/dist, physical/synthetic, currency, domicile" | `analyze_portfolio` |

Later (not built yet): ETF screener (by index, TER, size),
tax/legal details, savings-plan/dividend details, Yahoo price history joined by ticker.

## Architecture

```
finance_mcp/
  server.py            builds the FastMCP server, registers both tool sets
  yahoo/tools.py       Yahoo Finance tools
  justetf/
    client.py            polite HTTP: honest UA, rate limit, retries, cache (memory + disk TTL)
    parser.py            HTML -> structured dict (uses stable data-testid hooks)
    service.py           get_profile(isin): fetch page + "Show more" AJAX, cached
    analysis.py          pure functions: portfolio aggregation (no network, unit-testable)
    registry.py          local ISIN/name/ticker registry (seed + learned)
    search.py            name -> ISIN: ISIN passthrough, registry, Yahoo fallback
    tools.py             MCP tool definitions (thin wrappers)
    data/etfs.json       seed registry (each entry verified on justETF)
tests/                 offline tests: parser (synthetic HTML), analysis, registry/search
```

## Politeness / compliance (see the terms discussion)

- Personal, on-demand use only; no crawling, no scheduled bulk jobs, no redistribution.
- Honest User-Agent, min delay between requests (default 1.5s), max ISINs per call,
  on-disk cache (default 24h) so repeated questions never re-hit the site.
- Only `/en/etf-profile.html` (allowed by robots.txt). No `/servlet/`, no `/link/`.
- ISIN validated (format + checksum) before any request, so no arbitrary URLs.

## Known limits (reported to the agent in tool output)

- justETF exposes only the top 10 holdings, top ~10 countries and top ~10 sectors;
  the rest is "Other". Portfolio exposure is therefore a lower bound per named bucket.
- Sector / country names are justETF's own classification.
- Fund size is shown in the currency of the selected universe (EUR for the default).
- Page structure can change; the parser returns `null` for missing fields rather than failing.

## Name -> ISIN (decision record)

- justETF search is AJAX (`search.html?..._wicket=1`), which robots.txt disallows: not used.
- Yahoo search finds names/tickers/listings but yfinance's `.isin` no longer works (returns "-").
- So: seed registry + registry learned from fetched profiles; Yahoo hits are mapped to ISINs
  by ticker, then exact name. Unmapped hits are reported, never guessed.
- Possible later improvements: more seed entries, exchange instrument lists (Xetra/Euronext) if their terms allow.
