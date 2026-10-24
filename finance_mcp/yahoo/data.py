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

from .analytics import major_currency, remove_spikes, to_base_currency

VALID_INTERVALS = ("1d", "1wk", "1mo")
_PROBE_URL = "https://query1.finance.yahoo.com/"
_meta_cache: dict[str, dict[str, str | None]] = {}


class YahooError(Exception):
    """An expected failure, with a code an agent can act on.

    Codes: ``invalid_input``, ``no_data``, ``upstream_unavailable``,
    ``fx_unavailable``, ``insufficient_data``.
    """

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        """Create the error.

        Args:
            code: Machine-readable error code (see the class docstring).
            message: Human-readable explanation.
            hint: Optional next step for the agent, e.g. which tool to try.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def to_dict(self) -> dict[str, Any]:
        """Serialise the error as a tool result.

        Returns:
            ``{"error", "error_code"}`` plus ``"hint"`` when there is one.
        """
        out: dict[str, Any] = {"error": self.message, "error_code": self.code}
        if self.hint:
            out["hint"] = self.hint
        return out


def clean_symbols(symbols: list[str] | str) -> list[str]:
    """Normalise symbols to unique upper-case values in input order.

    Args:
        symbols: A list of symbols, or one string like "A, B; C".

    Returns:
        The cleaned symbols, empty entries removed.
    """
    if isinstance(symbols, str):
        symbols = symbols.replace(";", ",").split(",")
    out: list[str] = []
    for s in symbols:
        s = s.strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def yahoo_reachable() -> bool:
    """Check whether Yahoo's API host answers at all (any HTTP status).

    Returns:
        True if an HTTP response came back, False on a network error.
    """
    try:
        httpx.get(_PROBE_URL, timeout=5)
    except httpx.HTTPError:
        return False
    return True


def missing_data_error(symbols: list[str]) -> YahooError:
    """Build the error for missing data: network problem, or symbols/range at fault.

    Args:
        symbols: The symbols that returned no data.

    Returns:
        An ``upstream_unavailable`` error if Yahoo is unreachable, else ``no_data``.
    """
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
    """Download adjusted closes (splits + dividends), one column per symbol.

    Symbols without any data are simply absent from the result; callers decide
    whether that is an error (see ``missing_data_error``).

    Args:
        symbols: Yahoo symbols.
        start: First date YYYY-MM-DD, or None for Yahoo's default.
        end: End date YYYY-MM-DD (exclusive), or None for the latest.
        interval: "1d", "1wk" or "1mo".

    Returns:
        Closes on a time-zone-naive index; empty if nothing came back.

    Raises:
        YahooError: ``invalid_input`` for a bad interval or no symbols,
            ``upstream_unavailable`` if the download itself fails.
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
    if isinstance(close, pd.Series):  # flat columns: a single ticker
        close = close.to_frame(name=symbols[0])
    # Drop the exchange time zone so listings from different markets share
    # one calendar (dates, not instants, are what we compare).
    close.index = pd.DatetimeIndex(close.index).tz_localize(None)
    close.columns = [str(c) for c in close.columns]
    return close.dropna(how="all").dropna(axis=1, how="all")


def _meta(symbol: str) -> dict[str, str | None]:
    """Look up a symbol's quote currency and exchange time zone (one fast_info call).

    Args:
        symbol: Yahoo symbol.

    Returns:
        ``{"currency", "timezone"}``, each None when unknown.
    """
    out: dict[str, str | None] = {"currency": None, "timezone": None}
    try:
        fi = yf.Ticker(symbol).fast_info
        out["currency"] = str(fi["currency"]) if fi["currency"] else None
        out["timezone"] = str(fi["timezone"]) if fi["timezone"] else None
    except Exception:  # noqa: BLE001 - unknown tickers raise KeyError etc.
        pass
    return out


def _load_meta(symbols: list[str]) -> None:
    """Fill the metadata cache for symbols not looked up yet, in parallel.

    Only symbols with a known currency are cached, so a transient failure is
    retried on the next call.

    Args:
        symbols: Yahoo symbols.
    """
    todo = [s for s in symbols if s not in _meta_cache]
    if todo:
        with ThreadPoolExecutor(max_workers=8) as pool:
            for sym, meta in zip(todo, pool.map(_meta, todo), strict=True):
                if meta["currency"]:
                    _meta_cache[sym] = meta


def get_currencies(symbols: list[str]) -> dict[str, str | None]:
    """Get the quote currency per symbol as Yahoo reports it (may be minor, e.g. GBp).

    Args:
        symbols: Yahoo symbols.

    Returns:
        ``{symbol: currency or None}``.
    """
    _load_meta(symbols)
    return {s: (_meta_cache.get(s) or {}).get("currency") for s in symbols}


def get_timezones(symbols: list[str]) -> dict[str, str | None]:
    """Get the exchange time zone per symbol, e.g. 'Europe/Berlin'.

    Args:
        symbols: Yahoo symbols.

    Returns:
        ``{symbol: IANA time zone or None}``.
    """
    _load_meta(symbols)
    return {s: (_meta_cache.get(s) or {}).get("timezone") for s in symbols}


def async_close_warning(symbols: list[str], interval: str) -> str | None:
    """Warn when daily returns mix markets that close hours apart.

    US markets close ~4.5h after Europe's, so a day's US move shows up in the
    *next* European close: daily correlations and betas between regions are
    biased towards zero. Weekly data largely removes this.

    Args:
        symbols: Yahoo symbols in the analysis.
        interval: Return frequency.

    Returns:
        The warning text, or None if not daily or all in one region.
    """
    if interval != "1d" or len(symbols) < 2:
        return None
    zones = get_timezones(symbols)
    regions = {z.split("/")[0] for z in zones.values() if z}  # "Europe", "America"
    if len(regions) < 2:
        return None
    names = ", ".join(sorted(regions))
    return (
        f"Daily returns mix markets in different time zones ({names}): "
        "cross-region correlations and betas are understated because the "
        "markets close hours apart. Use interval='1wk' for those figures."
    )


def download_fx(
    currencies: set[str], base: str, start: str | None, end: str | None
) -> pd.DataFrame:
    """Download daily FX rates into ``base``, one column per ISO currency.

    Args:
        currencies: ISO codes to convert from (``base`` and "" are skipped).
        base: ISO code to convert into.
        start: First date YYYY-MM-DD, or None.
        end: End date YYYY-MM-DD (exclusive), or None.

    Returns:
        Units of ``base`` per 1 unit of each currency; empty if none needed.

    Raises:
        YahooError: ``fx_unavailable`` if a needed pair has no data, or
            ``upstream_unavailable`` if Yahoo cannot be reached.
    """
    base = base.upper()
    need = sorted({c for c in currencies if c and c != base})
    if not need:
        return pd.DataFrame()
    pairs = {f"{c}{base}=X": c for c in need}  # Yahoo FX symbols, e.g. USDEUR=X
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
    """Download prices, drop bad prints and optionally convert to ``base_currency``.

    Args:
        symbols: Yahoo symbols.
        start: First date YYYY-MM-DD, or None.
        end: End date YYYY-MM-DD (exclusive), or None.
        interval: "1d", "1wk" or "1mo".
        base_currency: ISO code to convert into, or None for local currencies.

    Returns:
        ``(prices, info)``; ``info`` has per-symbol ``currencies``, a list of
        ``missing`` symbols that returned no data and ``removed_bad_prices``.

    Raises:
        YahooError: if no symbol has data, or currencies/FX cannot be resolved.
    """
    close = download_close(symbols, start, end, interval)
    if close.empty:
        raise missing_data_error(symbols)
    close, removed = remove_spikes(close)
    missing = [s for s in symbols if s not in close.columns]
    info: dict[str, Any] = {
        "missing": missing,
        "currencies": {},
        "removed_bad_prices": removed,
    }
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
