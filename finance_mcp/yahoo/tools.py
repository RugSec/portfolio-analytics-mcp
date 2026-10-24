"""Yahoo Finance tools for portfolio analysis.

Built on yfinance (unofficial, personal use only). Data can be delayed
depending on the exchange.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, cast

import pandas as pd
import yfinance as yf
from mcp.server.fastmcp import FastMCP

DEFAULT_START = "2020-01-01"
MAX_ROWS_PER_TICKER = 400  # keeps tool output a sensible size for the LLM
VALID_INTERVALS = {"1d", "1wk", "1mo"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _clean_tickers(tickers: list[str] | str) -> list[str]:
    """Normalize tickers to unique, uppercase symbols in their original order.

    Args:
        tickers: A list of symbols, or a comma/semicolon-separated string.

    Returns:
        The cleaned symbols, without blanks or duplicates.
    """
    if isinstance(tickers, str):
        tickers = [t for t in tickers.replace(";", ",").split(",")]
    out = []
    for t in tickers:
        t = t.strip().upper()
        if t and t not in out:
            out.append(t)
    return out


def _num(x: Any, digits: int = 4) -> float | None:
    """Convert a value to a rounded float, or None if it is missing or invalid.

    Args:
        x: Value to convert (number, numeric string, NaN, None, ...).
        digits: Number of decimal places to round to.

    Returns:
        The rounded float, or None for NaN, infinity or non-numeric input.
    """
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def _download_close(
    tickers: list[str], start: str, end: str | None, interval: str
) -> pd.DataFrame:
    """Download adjusted close prices with one column per ticker.

    Args:
        tickers: Yahoo Finance symbols to download.
        start: Start date, YYYY-MM-DD.
        end: End date (exclusive), YYYY-MM-DD, or None for the latest data.
        interval: One of VALID_INTERVALS ("1d", "1wk", "1mo").

    Returns:
        A DataFrame indexed by date with one column per ticker, or an empty
        DataFrame if Yahoo returned no data.

    Raises:
        ValueError: If the interval is not supported.
    """
    if interval not in VALID_INTERVALS:
        raise ValueError(f"interval must be one of {sorted(VALID_INTERVALS)}")
    df = yf.download(
        tickers,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    if df is None or df.empty:
        return pd.DataFrame()
    close = df["Close"]
    if isinstance(close, pd.Series):  # single ticker
        close = close.to_frame(name=tickers[0])
    return close.dropna(how="all")


# --------------------------------------------------------------------------
# 1. price history
# --------------------------------------------------------------------------
def get_price_history(
    tickers: list[str],
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    interval: str = "1d",
) -> dict:
    """Get historical adjusted closing prices for one or more tickers.

    Args:
        tickers: Yahoo Finance symbols, e.g. ["AAPL", "ASML.AS", "VWCE.DE"].
        start_date: YYYY-MM-DD. Defaults to 2020-01-01.
        end_date: YYYY-MM-DD (exclusive). Defaults to the latest available value.
        interval: "1d", "1wk" or "1mo". Use weekly/monthly for long ranges.

    Prices are adjusted for splits and dividends. If a series is longer than
    400 points, it is thinned evenly (first and last point are always kept)
    and `thinned` is set to true; request a coarser interval for full data.
    """
    symbols = _clean_tickers(tickers)
    if not symbols:
        return {"error": "No tickers provided."}
    try:
        close = _download_close(symbols, start_date, end_date, interval)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Download failed: {e}"}
    if close.empty:
        return {"error": "No data returned. Check the symbols and date range."}

    result: dict[str, Any] = {}
    for sym in symbols:
        if sym not in close.columns:
            result[sym] = {"error": "No data for this symbol."}
            continue
        s = close[sym].dropna()
        if s.empty:
            result[sym] = {"error": "No data for this symbol in the range."}
            continue
        thinned = False
        if len(s) > MAX_ROWS_PER_TICKER:
            step = math.ceil(len(s) / MAX_ROWS_PER_TICKER)
            idx = list(range(0, len(s), step))
            if idx[-1] != len(s) - 1:
                idx.append(len(s) - 1)
            s = s.take(idx)
            thinned = True
        result[sym] = {
            "first_date": s.index[0].strftime("%Y-%m-%d"),
            "last_date": s.index[-1].strftime("%Y-%m-%d"),
            "last_price": _num(s.iloc[-1]),
            "points": len(s),
            "thinned": thinned,
            "prices": {
                cast(pd.Timestamp, d).strftime("%Y-%m-%d"): _num(v)
                for d, v in s.items()
            },
        }
    return {"interval": interval, "start": start_date, "end": end_date, "data": result}


# --------------------------------------------------------------------------
# 2. name <-> symbol
# --------------------------------------------------------------------------
def search_symbol(query: str, max_results: int = 10) -> dict:
    """Find ticker candidates for a company/ETF name (or a partial ticker).

    Returns several candidates with exchange and currency. The same company
    often trades on multiple exchanges (e.g. ASML on NASDAQ and Euronext
    Amsterdam), so when more than one candidate is plausible, ASK THE USER
    which listing/exchange/currency they hold before using a ticker.
    """
    try:
        res = yf.Search(query, max_results=max_results, news_count=0)
        quotes = res.quotes or []
    except Exception as e:  # noqa: BLE001
        return {"error": f"Search failed: {e}"}
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
    return {
        "query": query,
        "candidates": candidates,
        "note": (
            "Multiple listings are possible: confirm exchange and currency "
            "with the user."
        ),
    }


def get_symbol_info(ticker: str) -> dict:
    """Get the company/fund name, exchange, currency and type for a ticker."""
    sym = ticker.strip().upper()
    try:
        info = yf.Ticker(sym).info
    except Exception as e:  # noqa: BLE001
        return {"error": f"Lookup failed: {e}"}
    if not info or not (info.get("longName") or info.get("shortName")):
        return {"error": f"No information found for {sym}."}
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
def get_etf_sector_allocation(ticker: str) -> dict:
    """Get the sector allocation (% by sector) of an ETF or fund."""
    sym = ticker.strip().upper()
    try:
        fd = yf.Ticker(sym).funds_data
        weights = fd.sector_weightings
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not load fund data for {sym}: {e}. Is it an ETF/fund?"}
    if not weights:
        return {"error": f"No sector data available for {sym} on Yahoo Finance."}
    sectors = {
        k: _num(v * 100, 2)
        for k, v in sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
    }
    return {"ticker": sym, "sector_allocation_pct": sectors}


def get_etf_holdings(ticker: str) -> dict:
    """Get the top holdings of an ETF with each company's % weight.

    Yahoo usually exposes only the top ~10 holdings, so the percentages
    will not sum to 100. `total_pct_covered` shows how much is covered.
    """
    sym = ticker.strip().upper()
    try:
        fd = yf.Ticker(sym).funds_data
        top = fd.top_holdings
    except Exception as e:  # noqa: BLE001
        return {"error": f"Could not load fund data for {sym}: {e}. Is it an ETF/fund?"}
    if top is None or top.empty:
        return {"error": f"No holdings data available for {sym} on Yahoo Finance."}
    holdings = []
    for symbol, row in top.iterrows():
        holdings.append(
            {
                "symbol": symbol,
                "name": row.get("Name"),
                "weight_pct": _num((row.get("Holding Percent") or 0) * 100, 2),
            }
        )
    return {
        "ticker": sym,
        "holdings": holdings,
        "total_pct_covered": _num(sum(h["weight_pct"] or 0 for h in holdings), 2),
    }


# --------------------------------------------------------------------------
# extras for portfolio analysis
# --------------------------------------------------------------------------
def get_quote(tickers: list[str]) -> dict:
    """Get the latest price, currency, exchange and market state for tickers.

    Data may be delayed (up to ~15-20 min) depending on the exchange.
    """
    out: dict[str, Any] = {}
    for sym in _clean_tickers(tickers):
        try:
            t = yf.Ticker(sym)
            fi = t.fast_info
            price = _num(fi.get("lastPrice"))
            prev = _num(fi.get("previousClose"))
            change_pct = _num((price / prev - 1) * 100, 2) if price and prev else None
            out[sym] = {
                "price": price,
                "previous_close": prev,
                "change_pct": change_pct,
                "currency": fi.get("currency"),
                "exchange": fi.get("exchange"),
            }
        except Exception as e:  # noqa: BLE001
            out[sym] = {"error": str(e)}
    return {"as_of": date.today().isoformat(), "quotes": out}


def get_performance_stats(
    tickers: list[str],
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
) -> dict:
    """Compute total return, annualized return, volatility and max drawdown.

    Uses adjusted daily closes (dividends reinvested). Volatility is the
    annualized standard deviation of daily returns.
    """
    symbols = _clean_tickers(tickers)
    try:
        close = _download_close(symbols, start_date, end_date, "1d")
    except Exception as e:  # noqa: BLE001
        return {"error": f"Download failed: {e}"}
    if close.empty:
        return {"error": "No data returned."}
    stats: dict[str, Any] = {}
    for sym in symbols:
        if sym not in close.columns:
            stats[sym] = {"error": "No data."}
            continue
        s = close[sym].dropna()
        if len(s) < 2:
            stats[sym] = {"error": "Not enough data."}
            continue
        first = cast(pd.Timestamp, s.index[0])
        last = cast(pd.Timestamp, s.index[-1])
        years = (last - first).days / 365.25
        total = s.iloc[-1] / s.iloc[0] - 1
        cagr = (1 + total) ** (1 / years) - 1 if years > 0 else None
        rets = s.pct_change().dropna()
        vol = rets.std() * math.sqrt(252)
        drawdown = (s / s.cummax() - 1).min()
        stats[sym] = {
            "from": s.index[0].strftime("%Y-%m-%d"),
            "to": s.index[-1].strftime("%Y-%m-%d"),
            "total_return_pct": _num(total * 100, 2),
            "annualized_return_pct": _num(cagr * 100, 2) if cagr is not None else None,
            "annualized_volatility_pct": _num(vol * 100, 2),
            "max_drawdown_pct": _num(drawdown * 100, 2),
        }
    return {"stats": stats}


def get_correlation(
    tickers: list[str],
    start_date: str = DEFAULT_START,
    end_date: str | None = None,
    interval: str = "1wk",
) -> dict:
    """Correlation matrix of returns between 2+ tickers (default weekly returns).

    Note: tickers on different exchanges/currencies are compared in their
    own local currency, which affects correlation.
    """
    symbols = _clean_tickers(tickers)
    if len(symbols) < 2:
        return {"error": "Provide at least two tickers."}
    try:
        close = _download_close(symbols, start_date, end_date, interval)
    except Exception as e:  # noqa: BLE001
        return {"error": f"Download failed: {e}"}
    rets = close.pct_change().dropna(how="any")
    if len(rets) < 3:
        return {"error": "Not enough overlapping data."}
    corr = rets.corr()
    return {
        "interval": interval,
        "observations": len(rets),
        "correlation": {
            a: {b: _num(corr.loc[a, b], 3) for b in corr.columns} for a in corr.index
        },
    }


def get_dividends(
    ticker: str, start_date: str = DEFAULT_START, end_date: str | None = None
) -> dict:
    """Get dividend payments for a ticker in a date range."""
    sym = ticker.strip().upper()
    try:
        div = yf.Ticker(sym).dividends
    except Exception as e:  # noqa: BLE001
        return {"error": f"Lookup failed: {e}"}
    if div is None or div.empty:
        return {"ticker": sym, "dividends": {}, "note": "No dividends found."}
    dt_index = cast(pd.DatetimeIndex, div.index)
    idx = dt_index.tz_localize(None) if dt_index.tz is not None else dt_index
    div = div.copy()
    div.index = idx
    div = div[div.index >= pd.Timestamp(start_date)]
    if end_date:
        div = div[div.index < pd.Timestamp(end_date)]
    return {
        "ticker": sym,
        "total": _num(div.sum(), 4),
        "dividends": {
            cast(pd.Timestamp, d).strftime("%Y-%m-%d"): _num(v, 4)
            for d, v in div.items()
        },
    }


TOOLS = [
    get_price_history,
    search_symbol,
    get_symbol_info,
    get_etf_sector_allocation,
    get_etf_holdings,
    get_quote,
    get_performance_stats,
    get_correlation,
    get_dividends,
]


def register(mcp: FastMCP) -> None:
    """Register all Yahoo Finance tools on the given server."""
    for tool in TOOLS:
        mcp.tool()(tool)
