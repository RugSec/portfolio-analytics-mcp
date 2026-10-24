"""Network layer for Yahoo Finance (via yfinance): prices, currencies, FX.

Errors are raised as ``YahooError`` with a machine-readable ``code`` and a
hint, so tools can tell an agent *why* data is missing (bad ticker vs Yahoo
unreachable) instead of returning an empty result.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
import pandas as pd
import yfinance as yf

from .analytics import major_currency

VALID_INTERVALS = ("1d", "1wk", "1mo")
_PROBE_URL = "https://query1.finance.yahoo.com/"
_currency_cache: dict[str, str | None] = {}


class YahooError(Exception):
    """An expected failure, with a code an agent can act on.

    Codes: ``invalid_input``, ``no_data``, ``upstream_unavailable``,
    ``fx_unavailable``, ``insufficient_data``.
    """

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"error": self.message, "error_code": self.code}
        if self.hint:
            out["hint"] = self.hint
        return out


def clean_symbols(symbols: list[str] | str) -> list[str]:
    """Unique upper-case symbols in input order (accepts 'A, B; C' too)."""
    if isinstance(symbols, str):
        symbols = symbols.replace(";", ",").split(",")
    out: list[str] = []
    for s in symbols:
        s = s.strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def yahoo_reachable() -> bool:
    """True if Yahoo's API host answers at all (any HTTP status)."""
    try:
        httpx.get(_PROBE_URL, timeout=5)
    except httpx.HTTPError:
        return False
    return True


def missing_data_error(symbols: list[str]) -> YahooError:
    """Explain missing data: network problem, or symbols/range at fault."""
    if not yahoo_reachable():
        return YahooError(
            "upstream_unavailable",
            "Yahoo Finance could not be reached (network error, proxy or block).",
            "Retry later. This says nothing about whether the tickers are valid.",
        )
    return YahooError(
        "no_data",
        f"Yahoo returned no data for: {', '.join(symbols)}.",
        "Check the symbol with search_symbol (non-US listings need an exchange "
        "suffix, e.g. VWCE.DE, IWDA.AS, VWRL.L), or use a wider date range.",
    )


def download_close(
    symbols: list[str], start: str | None, end: str | None, interval: str
) -> pd.DataFrame:
    """Adjusted closes (splits + dividends), one column per symbol that has data.

    Symbols without any data are simply absent from the result; callers decide
    whether that is an error (see ``missing_data_error``).
    """
    if interval not in VALID_INTERVALS:
        raise YahooError(
            "invalid_input", f"interval must be one of {', '.join(VALID_INTERVALS)}"
        )
    if not symbols:
        raise YahooError("invalid_input", "No tickers provided.")
    try:
        df = yf.download(
            symbols,
            start=start,
            end=end,
            interval=interval,
            auto_adjust=True,
            progress=False,
            group_by="column",
            threads=True,
            multi_level_index=True,
        )
    except Exception as exc:  # noqa: BLE001 - yfinance raises anything
        raise YahooError(
            "upstream_unavailable", f"Yahoo download failed: {exc}", "Retry later."
        ) from exc
    if df is None or df.empty or "Close" not in df.columns.get_level_values(0):
        return pd.DataFrame()
    close = df["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(name=symbols[0])
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    close.columns = [str(c) for c in close.columns]
    return close.dropna(how="all").dropna(axis=1, how="all")


def _currency(symbol: str) -> str | None:
    try:
        value = yf.Ticker(symbol).fast_info["currency"]
    except Exception:  # noqa: BLE001 - unknown tickers raise KeyError etc.
        return None
    return str(value) if value else None


def get_currencies(symbols: list[str]) -> dict[str, str | None]:
    """Quote currency per symbol as Yahoo reports it (may be minor, e.g. GBp)."""
    todo = [s for s in symbols if s not in _currency_cache]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for sym, cur in zip(todo, pool.map(_currency, todo), strict=True):
                if cur:
                    _currency_cache[sym] = cur
    return {s: _currency_cache.get(s) for s in symbols}


def download_fx(
    currencies: set[str], base: str, start: str | None, end: str | None
) -> pd.DataFrame:
    """Daily FX: one column per ISO currency = units of ``base`` per 1 unit.

    Raises:
        YahooError: ``fx_unavailable`` if a needed pair has no data.
    """
    base = base.upper()
    need = sorted({c for c in currencies if c and c != base})
    if not need:
        return pd.DataFrame()
    pairs = {f"{c}{base}=X": c for c in need}
    close = download_close(list(pairs), start, end, "1d")
    missing = [c for sym, c in pairs.items() if sym not in close.columns]
    if missing:
        if close.empty and not yahoo_reachable():
            raise missing_data_error(list(pairs))
        raise YahooError(
            "fx_unavailable",
            f"No FX rate to {base} for: {', '.join(missing)}.",
            "Check base_currency is an ISO code (EUR, USD, GBP, CHF...).",
        )
    return close.rename(columns=pairs)


def prices_in_currency(
    symbols: list[str],
    start: str | None,
    end: str | None,
    interval: str,
    base_currency: str | None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Download prices and optionally convert them to ``base_currency``.

    Returns:
        ``(prices, info)``; ``info`` has per-symbol ``currencies`` and a list of
        ``missing`` symbols that returned no data.

    Raises:
        YahooError: if no symbol has data, or currencies/FX cannot be resolved.
    """
    from .analytics import to_base_currency

    close = download_close(symbols, start, end, interval)
    if close.empty:
        raise missing_data_error(symbols)
    missing = [s for s in symbols if s not in close.columns]
    info: dict[str, Any] = {"missing": missing, "currencies": {}}
    if not base_currency:
        return close, info
    have = list(close.columns)
    currencies = get_currencies(have)
    info["currencies"] = currencies
    unknown = [s for s, c in currencies.items() if not c]
    if unknown:
        raise YahooError(
            "no_data",
            f"Could not determine the quote currency of: {', '.join(unknown)}.",
            "Retry, or call without base_currency to get local-currency figures.",
        )
    majors = {major_currency(c)[0] or "" for c in currencies.values()}
    fx = download_fx(majors, base_currency, start, end)
    return to_base_currency(close, currencies, fx, base_currency), info
