"""Yahoo Finance tools for portfolio analysis.

Built on yfinance (unofficial, personal use only). Data can be delayed
depending on the exchange. Maths lives in ``analytics`` (pure, tested
offline); downloads, currencies and FX in ``data``.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Literal

import pandas as pd
import yfinance as yf
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import analytics as an
from . import data
from .data import YahooError

DEFAULT_START = "2020-01-01"
MAX_ROWS_PER_TICKER = 400  # keeps tool output a sensible size for the LLM
Interval = Literal["1d", "1wk", "1mo"]
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=True)

# kept for backwards compatibility with earlier imports
_clean_tickers = data.clean_symbols
_num = an.num


# --------------------------------------------------------------------------
# 1. price history
# --------------------------------------------------------------------------
def get_price_history(
    tickers: list[str],
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    interval: Interval = "1d",
    base_currency: str | None = None,
) -> dict:
    """Get historical adjusted closing prices for one or more tickers.

    Prices are adjusted for splits and dividends. Series longer than 400
    points are thinned evenly (first and last kept, `thinned: true`); use a
    coarser interval for full data. For statistics, prefer
    get_performance_stats / analyze_portfolio_risk over computing from this.

    Args:
        tickers: Yahoo symbols, e.g. ["AAPL", "ASML.AS", "VWCE.DE"].
        start_date: YYYY-MM-DD. Defaults to 2020-01-01.
        end_date: YYYY-MM-DD (exclusive). Defaults to the latest value.
        interval: "1d", "1wk" or "1mo".
        base_currency: Optional ISO code (e.g. "EUR") to convert all prices
            into with daily FX; default is each listing's own currency.
    """
    symbols = data.clean_symbols(tickers)
    try:
        close, info = data.prices_in_currency(
            symbols, start_date, end_date, interval, base_currency
        )
    except YahooError as exc:
        return exc.to_dict()
    result: dict[str, Any] = {}
    for sym in symbols:
        if sym not in close.columns:
            result[sym] = {
                "error": "No data for this symbol in the range.",
                "error_code": "no_data",
            }
            continue
        s = close[sym].dropna()
        thinned = False
        if len(s) > MAX_ROWS_PER_TICKER:
            step = math.ceil(len(s) / MAX_ROWS_PER_TICKER)
            idx = list(range(0, len(s), step))
            if idx[-1] != len(s) - 1:
                idx.append(len(s) - 1)
            s = s.take(idx)
            thinned = True
        result[sym] = {
            "first_date": an.day(s.index[0]),
            "last_date": an.day(s.index[-1]),
            "last_price": an.num(s.iloc[-1]),
            "points": len(s),
            "thinned": thinned,
            "prices": {an.day(d): an.num(v) for d, v in s.items()},
        }
        if base_currency:
            result[sym]["currency"] = base_currency.upper()
            result[sym]["quote_currency"] = info["currencies"].get(sym)
    return {"interval": interval, "start": start_date, "end": end_date, "data": result}


# --------------------------------------------------------------------------
# 2. name <-> symbol
# --------------------------------------------------------------------------
def search_symbol(query: str, max_results: int = 10) -> dict:
    """Find ticker candidates for a company/ETF name, partial ticker or ISIN.

    The same security often trades on several exchanges (e.g. ASML on NASDAQ
    and Euronext Amsterdam), so when more than one candidate is plausible,
    ASK THE USER which listing/exchange/currency they hold. For European ETFs
    by ISIN, resolve_instrument gives exchange-accurate tickers.

    Args:
        query: Name, ticker fragment or ISIN.
        max_results: Maximum candidates (1-25).
    """
    try:
        res = yf.Search(query, max_results=max(1, min(max_results, 25)), news_count=0)
        quotes = res.quotes or []
    except Exception as exc:  # noqa: BLE001
        return YahooError(
            "upstream_unavailable", f"Search failed: {exc}", "Retry later."
        ).to_dict()
    candidates = [
        {
            "symbol": q.get("symbol"),
            "name": q.get("longname") or q.get("shortname"),
            "type": q.get("quoteType"),
            "exchange": q.get("exchDisp") or q.get("exchange"),
            "sector": q.get("sector"),
            "industry": q.get("industry"),
        }
        for q in quotes
        if q.get("symbol")
    ]
    out: dict[str, Any] = {"query": query, "candidates": candidates}
    if not candidates:
        out["note"] = "No matches. Try a shorter name or the ISIN."
    else:
        out["note"] = (
            "Multiple listings are possible: confirm exchange and currency "
            "with the user."
        )
    return out


def get_symbol_info(ticker: str) -> dict:
    """Name, exchange, currency, type, sector/industry and country of a ticker.

    Args:
        ticker: Yahoo symbol, e.g. "ASML.AS".
    """
    sym = ticker.strip().upper()
    try:
        info = yf.Ticker(sym).info
    except Exception as exc:  # noqa: BLE001
        return data.missing_data_error([sym]).to_dict() | {"detail": str(exc)}
    if not info or not (info.get("longName") or info.get("shortName")):
        return data.missing_data_error([sym]).to_dict()
    keys = [
        "symbol",
        "longName",
        "shortName",
        "quoteType",
        "exchange",
        "fullExchangeName",
        "currency",
        "country",
        "sector",
        "industry",
        "category",
        "fundFamily",
        "website",
    ]
    return {k: info.get(k) for k in keys if info.get(k) is not None}


# --------------------------------------------------------------------------
# 3 + 4. ETF composition
# --------------------------------------------------------------------------
def _funds_data(sym: str) -> Any:
    try:
        return yf.Ticker(sym).funds_data
    except Exception as exc:  # noqa: BLE001
        raise data.missing_data_error([sym]) from exc


def get_etf_sector_allocation(ticker: str) -> dict:
    """Sector allocation (% by sector) of an ETF or fund, from Yahoo.

    Yahoo coverage of European UCITS ETFs is patchy: for those, prefer
    get_etf_exposure (justETF, by ISIN).

    Args:
        ticker: Yahoo symbol of the fund, e.g. "SPY", "IWDA.AS".
    """
    sym = ticker.strip().upper()
    try:
        weights = _funds_data(sym).sector_weightings
    except YahooError as exc:
        return exc.to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"No fund data for {sym}: {exc}", "error_code": "no_data"}
    if not weights:
        return {
            "error": f"No sector data for {sym} on Yahoo (is it an ETF/fund?).",
            "error_code": "no_data",
            "hint": "For UCITS ETFs use get_etf_exposure with the ISIN.",
        }
    sectors = {
        k: an.num(v * 100, 2)
        for k, v in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    }
    return {"ticker": sym, "sector_allocation_pct": sectors}


def get_etf_holdings(ticker: str) -> dict:
    """Top holdings of an ETF with each company's % weight, from Yahoo.

    Yahoo usually exposes only the top ~10 holdings; `total_pct_covered`
    shows how much of the fund that is. For UCITS ETFs and portfolio-level
    overlap, prefer get_etf_exposure / analyze_portfolio (justETF, by ISIN).

    Args:
        ticker: Yahoo symbol of the fund, e.g. "QQQ", "IWDA.AS".
    """
    sym = ticker.strip().upper()
    try:
        top = _funds_data(sym).top_holdings
    except YahooError as exc:
        return exc.to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"No fund data for {sym}: {exc}", "error_code": "no_data"}
    if top is None or top.empty:
        return {
            "error": f"No holdings data for {sym} on Yahoo (is it an ETF/fund?).",
            "error_code": "no_data",
            "hint": "For UCITS ETFs use get_etf_exposure with the ISIN.",
        }
    holdings = [
        {
            "symbol": symbol,
            "name": row.get("Name"),
            "weight_pct": an.num((row.get("Holding Percent") or 0) * 100, 2),
        }
        for symbol, row in top.iterrows()
    ]
    return {
        "ticker": sym,
        "holdings": holdings,
        "total_pct_covered": an.num(sum(h["weight_pct"] or 0 for h in holdings), 2),
    }


# --------------------------------------------------------------------------
# quotes, FX, statistics
# --------------------------------------------------------------------------
def get_quote(tickers: list[str]) -> dict:
    """Latest price, previous close, day change, currency and exchange.

    Data may be delayed (up to ~15-20 min). `currency` is as Yahoo reports
    it: "GBp" means pence (divide by 100 for GBP).

    Args:
        tickers: Yahoo symbols, e.g. ["IWDA.AS", "VWRL.L", "AAPL"].
    """
    out: dict[str, Any] = {}
    for sym in data.clean_symbols(tickers):
        try:
            fi = yf.Ticker(sym).fast_info
            price = an.num(fi["lastPrice"])
            prev = an.num(fi["previousClose"])
            currency = fi["currency"]
            exchange = fi["exchange"]
        except Exception:  # noqa: BLE001 - unknown tickers raise KeyError etc.
            out[sym] = {
                "error": "No quote for this symbol.",
                "error_code": "no_data",
                "hint": "Check it with search_symbol (non-US listings need a "
                "suffix, e.g. VWCE.DE).",
            }
            continue
        out[sym] = {
            "price": price,
            "previous_close": prev,
            "change_pct": an.num((price / prev - 1) * 100, 2)
            if price and prev
            else None,
            "currency": currency,
            "exchange": exchange,
        }
    if out and all("error" in v for v in out.values()) and not data.yahoo_reachable():
        return data.missing_data_error(list(out)).to_dict()
    return {"as_of": date.today().isoformat(), "quotes": out}


def get_fx_rates(
    currencies: list[str], base_currency: str = "EUR", start_date: str | None = None
) -> dict:
    """Latest FX rates into a base currency (and the change since start_date).

    Rate = units of base_currency per 1 unit of the currency, e.g. with base
    EUR, USD -> 0.92 means 1 USD = 0.92 EUR. Minor units are accepted
    ("GBp" is converted as GBP / 100).

    Args:
        currencies: ISO codes, e.g. ["USD", "GBP", "CHF"].
        base_currency: ISO code to express rates in. Default EUR.
        start_date: Optional YYYY-MM-DD to also return the % change since then.
    """
    base = base_currency.strip().upper()
    wanted = {c.strip(): an.major_currency(c.strip()) for c in currencies if c.strip()}
    if not wanted:
        return {"error": "No currencies given.", "error_code": "invalid_input"}
    start = start_date or an.day(pd.Timestamp.today() - pd.Timedelta(days=10))
    try:
        fx = data.download_fx({m or "" for m, _ in wanted.values()}, base, start, None)
    except YahooError as exc:
        return exc.to_dict()
    rates: dict[str, Any] = {}
    for code, (major, factor) in wanted.items():
        if major == base:
            rates[code] = {"rate": an.num(factor, 6), "date": date.today().isoformat()}
            continue
        s = fx[major].dropna()
        row: dict[str, Any] = {
            "rate": an.num(s.iloc[-1] * factor, 6),
            "date": an.day(s.index[-1]),
        }
        if start_date:
            row["change_since_start_pct"] = an.pct(s.iloc[-1] / s.iloc[0] - 1)
            row["start_rate"] = an.num(s.iloc[0] * factor, 6)
        rates[code] = row
    return {"base_currency": base, "rates": rates}


def get_performance_stats(
    tickers: list[str],
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    interval: Interval = "1d",
    base_currency: str | None = None,
    risk_free_rate_pct: float = 0.0,
    benchmark: str | None = None,
) -> dict:
    """Return and risk statistics per ticker, optionally vs a benchmark.

    Total and annualised return (annualised only for windows >= 1 year),
    annualised volatility, Sharpe, Sortino, Calmar, max drawdown with peak /
    trough / recovery dates, best and worst period. With `benchmark`: beta,
    alpha, correlation, tracking error and information ratio. Uses adjusted
    closes (dividends reinvested). Each ticker uses its own available window,
    so check `from`/`to` before comparing; for a portfolio use
    analyze_portfolio_risk.

    Args:
        tickers: Yahoo symbols.
        start_date: YYYY-MM-DD. Defaults to 2020-01-01.
        end_date: YYYY-MM-DD (exclusive). Defaults to the latest value.
        interval: Return frequency: "1d", "1wk" or "1mo".
        base_currency: Optional ISO code to measure everything in (e.g. "EUR"
            for a euro investor holding USD assets); default local currency.
        risk_free_rate_pct: Annual risk-free rate in %, for Sharpe/Sortino.
        benchmark: Optional Yahoo symbol to compare against, e.g. "IWDA.AS".
    """
    symbols = data.clean_symbols(tickers)
    bench = data.clean_symbols([benchmark])[0] if benchmark else None
    wanted = symbols + ([bench] if bench and bench not in symbols else [])
    try:
        close, _ = data.prices_in_currency(
            wanted, start_date, end_date, interval, base_currency
        )
    except YahooError as exc:
        return exc.to_dict()
    ppy = an.PERIODS_PER_YEAR[interval]
    rf = risk_free_rate_pct / 100
    has_bench = bench is not None and bench in close.columns
    stats: dict[str, Any] = {}
    for sym in symbols:
        if sym not in close.columns:
            stats[sym] = {"error": "No data.", "error_code": "no_data"}
            continue
        try:
            row = an.series_stats(close[sym], ppy, rf)
            if has_bench and sym != bench:
                pair = an.align_prices(close[[sym, bench]])
                row["vs_benchmark"] = an.relative_stats(pair[sym], pair[bench], ppy, rf)
        except ValueError as exc:
            row = {"error": str(exc), "error_code": "insufficient_data"}
        stats[sym] = row
    out: dict[str, Any] = {
        "interval": interval,
        "currency": base_currency.upper() if base_currency else "local",
        "risk_free_rate_pct": risk_free_rate_pct,
        "stats": stats,
    }
    if bench and not has_bench:
        out["warnings"] = [f"benchmark {bench} returned no data"]
    return out


def get_correlation(
    tickers: list[str],
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    interval: Interval = "1wk",
    base_currency: str | None = None,
) -> dict:
    """Correlation matrix of returns between 2+ tickers (default weekly).

    Exchange holidays are forward-filled and only the common window is used.
    Without `base_currency`, each series is in its own currency, so FX moves
    affect the result; set e.g. base_currency="EUR" to measure as a euro
    investor experiences it.

    Args:
        tickers: 2 or more Yahoo symbols.
        start_date: YYYY-MM-DD. Defaults to 2020-01-01.
        end_date: YYYY-MM-DD (exclusive).
        interval: "1d", "1wk" or "1mo".
        base_currency: Optional ISO code to convert all prices into first.
    """
    symbols = data.clean_symbols(tickers)
    if len(symbols) < 2:
        return {"error": "Provide at least two tickers.", "error_code": "invalid_input"}
    try:
        close, info = data.prices_in_currency(
            symbols, start_date, end_date, interval, base_currency
        )
    except YahooError as exc:
        return exc.to_dict()
    aligned = an.align_prices(close)
    if len(aligned) < 4:
        return YahooError(
            "insufficient_data",
            f"Only {len(aligned)} common dates across the tickers.",
            "Use an earlier start_date or a finer interval.",
        ).to_dict()
    out: dict[str, Any] = {
        "interval": interval,
        "currency": base_currency.upper() if base_currency else "local",
        "from": an.day(aligned.index[0]),
        "to": an.day(aligned.index[-1]),
        "observations": len(aligned) - 1,
        "correlation": an.correlation_matrix(aligned),
    }
    if info["missing"]:
        out["missing"] = info["missing"]
    return out


def get_dividends(
    ticker: str, start_date: str = DEFAULT_START, end_date: str | None = None
) -> dict:
    """Dividend payments per share for a ticker, plus a trailing-12-month total.

    Amounts are per share as Yahoo reports them; this can be the fund's
    distribution currency rather than the listing's trading currency (e.g. a
    USD-distributing ETF listed in GBP), so check before computing a yield.

    Args:
        ticker: Yahoo symbol.
        start_date: YYYY-MM-DD. Defaults to 2020-01-01.
        end_date: YYYY-MM-DD (exclusive).
    """
    sym = ticker.strip().upper()
    try:
        div = yf.Ticker(sym).dividends
    except Exception as exc:  # noqa: BLE001
        return data.missing_data_error([sym]).to_dict() | {"detail": str(exc)}
    if div is None or div.empty:
        if not data.yahoo_reachable():
            return data.missing_data_error([sym]).to_dict()
        return {"ticker": sym, "dividends": {}, "note": "No dividends found."}
    div = div.copy()
    div.index = pd.DatetimeIndex(div.index).tz_localize(None)
    last_year = div[div.index > div.index.max() - pd.DateOffset(years=1)]
    sel = div[div.index >= pd.Timestamp(start_date)]
    if end_date:
        sel = sel[sel.index < pd.Timestamp(end_date)]
    return {
        "ticker": sym,
        "total": an.num(sel.sum(), 4),
        "count": len(sel),
        "trailing_12m_total": an.num(last_year.sum(), 4),
        "payments_last_12m": len(last_year),
        "dividends": {an.day(d): an.num(v, 4) for d, v in sel.items()},
    }


TOOLS = [
    get_price_history,
    search_symbol,
    get_symbol_info,
    get_etf_sector_allocation,
    get_etf_holdings,
    get_quote,
    get_fx_rates,
    get_performance_stats,
    get_correlation,
    get_dividends,
]


def register(mcp: FastMCP) -> None:
    """Register all Yahoo Finance tools on the given server."""
    for tool in TOOLS:
        mcp.tool(annotations=READ_ONLY)(tool)
