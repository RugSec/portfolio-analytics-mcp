"""Portfolio risk/return in one base currency, from Yahoo prices.

Joins the pieces an agent would otherwise stitch together by hand:
ISIN -> ticker resolution, price download, quote currency + FX conversion
(including pence-quoted London listings), a common calendar, and the
statistics in ``yahoo.analytics``.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..justetf.client import JustEtfError
from ..yahoo import analytics as an
from ..yahoo import data
from ..yahoo.data import YahooError
from .resolve import resolve_isin

MAX_POSITIONS = 30
MAX_ISIN_FALLBACKS = 4
MIN_OBSERVATIONS = 10


class Position(BaseModel):
    """One holding. Give ``symbol`` or ``isin``, and ``quantity`` or ``value``."""

    model_config = ConfigDict(extra="forbid")

    symbol: str | None = Field(
        None,
        description="Yahoo ticker incl. exchange suffix, e.g. VWCE.DE, ASML.AS, AAPL.",
    )
    isin: str | None = Field(
        None,
        description="ISIN instead of symbol; resolved to a Yahoo ticker (ETFs via "
        "justETF listings, stocks via Yahoo search).",
    )
    quantity: float | None = Field(
        None, gt=0, description="Shares/units held (value = quantity x last price)."
    )
    value: float | None = Field(
        None, gt=0, description="Current market value in the base currency."
    )

    @model_validator(mode="after")
    def _check(self) -> Position:
        if not (self.symbol or self.isin):
            raise ValueError("each position needs a symbol or an isin")
        if self.quantity is not None and self.value is not None:
            raise ValueError("give quantity or value, not both")
        return self


def default_start(end_date: str | None) -> str:
    """Three years before ``end_date`` (or today)."""
    end = pd.Timestamp(end_date) if end_date else pd.Timestamp.today()
    return an.day(end - pd.DateOffset(years=3))


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _justetf_code(exc: JustEtfError) -> str:
    """Error code for a failed ISIN lookup: bad input, outage, or unknown."""
    msg = str(exc)
    if "not a valid ISIN" in msg or "check digit" in msg:
        return "invalid_input"
    if any(k in msg for k in ("Could not reach", "refused", "server error")):
        return "upstream_unavailable"
    return "no_data"


def _resolve(
    positions: list[Position], base: str
) -> tuple[list[list[str]], list[dict[str, Any]]]:
    """Candidate symbols per position (one for symbols, ranked for ISINs)."""
    options: list[list[str]] = []
    resolved: list[dict[str, Any]] = []
    for p in positions:
        if p.symbol:
            options.append(data.clean_symbols([p.symbol]))
            resolved.append({})
            continue
        try:
            r = resolve_isin(p.isin or "", base)
        except JustEtfError as exc:
            raise YahooError(
                _justetf_code(exc),
                f"Could not resolve ISIN {p.isin}: {exc}",
                "Pass a Yahoo symbol instead (find it with search_symbol).",
            ) from exc
        syms = [c["symbol"] for c in r["yahoo_candidates"]][:MAX_ISIN_FALLBACKS]
        if not syms:
            raise YahooError(
                "no_data",
                f"ISIN {p.isin} has no listing on an exchange Yahoo covers.",
                "Pass a Yahoo symbol instead (find it with search_symbol).",
            )
        options.append(syms)
        resolved.append({"isin": r["isin"], "name": r["name"]})
    return options, resolved


def _download_with_fallback(
    options: list[list[str]],
    benchmark: str | None,
    start: str,
    end: str | None,
    interval: str,
) -> tuple[pd.DataFrame, list[str]]:
    """Download first choices; for ISINs, try the next listing if one is empty."""
    chosen = [o[0] for o in options]
    wanted = _unique(chosen + ([benchmark] if benchmark else []))
    close = data.download_close(wanted, start, end, interval)
    for i, opts in enumerate(options):
        for alt in opts[1:]:
            if chosen[i] in close.columns:
                break
            extra = data.download_close([alt], start, end, interval)
            if not extra.empty:
                close = extra if close.empty else close.join(extra, how="outer")
                chosen[i] = alt
    missing = [s for s in _unique(chosen) if s not in close.columns]
    if close.empty or missing:
        raise data.missing_data_error(missing or wanted)
    return close, chosen


def analyze_portfolio_risk(
    positions: list[Position],
    base_currency: str = "EUR",
    benchmark: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    interval: str = "1wk",
    method: an.HoldingMethod = "current_holdings",
    risk_free_rate_pct: float = 0.0,
) -> dict[str, Any]:
    """See the MCP tool docstring in ``portfolio.tools``.

    Raises:
        YahooError: invalid input, unresolvable ISIN, missing data or FX.
    """
    if not positions:
        raise YahooError("invalid_input", "positions is empty")
    if len(positions) > MAX_POSITIONS:
        raise YahooError("invalid_input", f"at most {MAX_POSITIONS} positions per call")
    base = (base_currency or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", base):
        raise YahooError(
            "invalid_input", "base_currency must be an ISO code like EUR or USD"
        )
    if interval not in an.PERIODS_PER_YEAR:
        raise YahooError("invalid_input", "interval must be 1d, 1wk or 1mo")
    sized = [p.quantity is not None or p.value is not None for p in positions]
    if any(sized) and not all(sized):
        raise YahooError(
            "invalid_input",
            "give quantity or value for every position, or for none (equal weights)",
        )
    start = start_date or default_start(end_date)
    bench = data.clean_symbols([benchmark])[0] if benchmark else None
    warnings: list[str] = []

    options, resolved = _resolve(positions, base)
    close, chosen = _download_with_fallback(options, bench, start, end_date, interval)
    close, removed = an.remove_spikes(close)
    for sym, dates in removed.items():
        warnings.append(
            f"{sym}: dropped {len(dates)} bad price(s) that jumped and fully "
            f"reversed next period (Yahoo data error): {', '.join(dates)}"
        )
    if bench and bench not in close.columns:
        warnings.append(f"benchmark {bench} returned no data and was skipped")
        bench = None

    currencies = data.get_currencies(list(close.columns))
    unknown = [s for s, c in currencies.items() if not c]
    if unknown:
        raise YahooError(
            "no_data",
            f"Could not determine the quote currency of: {', '.join(unknown)}.",
            "Retry; Yahoo's quote endpoint may be rate limiting.",
        )
    majors = {an.major_currency(c)[0] or "" for c in currencies.values()}
    fx = data.download_fx(majors, base, start, end_date)
    try:
        base_px = an.to_base_currency(close, currencies, fx, base)
    except ValueError as exc:
        raise YahooError("fx_unavailable", str(exc)) from exc

    # current value per symbol (positions on the same symbol are merged)
    values: dict[str, float] = defaultdict(float)
    for p, sym in zip(positions, chosen, strict=True):
        if p.value is not None:
            values[sym] += p.value
        elif p.quantity is not None:
            values[sym] += p.quantity * float(base_px[sym].dropna().iloc[-1])
        else:
            values[sym] += 1.0
    pos_syms = list(values)
    weights = an.normalize_weights(pd.Series(values, dtype=float))

    cols = _unique(pos_syms + ([bench] if bench else []))
    report = an.window_report(base_px[cols])
    aligned = an.align_prices(base_px[cols])
    if len(aligned) < MIN_OBSERVATIONS:
        raise YahooError(
            "insufficient_data",
            f"Only {len(aligned)} common dates across the positions.",
            "Use an earlier start_date, a finer interval, or drop the position "
            f"with the shortest history ({', '.join(report['window_limited_by'])}).",
        )
    if report["window_limited_by"]:
        warnings.append(
            f"Common window starts {an.day(aligned.index[0])}, limited by the "
            f"shorter history of {', '.join(report['window_limited_by'])}."
        )
    if report["stale"]:
        warnings.append(
            "Last price older than the others (forward-filled): "
            + ", ".join(f"{k} ({v})" for k, v in report["stale"].items())
        )
    tz_warning = data.async_close_warning(cols, interval)
    if tz_warning:
        warnings.append(tz_warning)
    minor = sorted({c for c in currencies.values() if c in an.MINOR_CURRENCIES})
    if minor:
        warnings.append(
            f"Quotes in minor units ({', '.join(minor)}) converted to major units."
        )

    ppy = an.PERIODS_PER_YEAR[interval]
    rf = risk_free_rate_pct / 100
    port_px = aligned[pos_syms]
    port_values = an.portfolio_values(port_px, weights, method)
    portfolio = an.series_stats(port_values, ppy, rf)
    bench_out: dict[str, Any] | None = None
    if bench:
        portfolio["vs_benchmark"] = an.relative_stats(
            port_values, aligned[bench], ppy, rf
        )
        bench_out = {"symbol": bench, **an.series_stats(aligned[bench], ppy, rf)}
    risk = an.risk_contributions(port_px, weights, ppy) if len(pos_syms) > 1 else None

    keep = (
        "total_return_pct",
        "annualized_return_pct",
        "annualized_volatility_pct",
        "sharpe_ratio",
        "max_drawdown_pct",
    )
    rows = []
    for sym in pos_syms:
        stats = an.series_stats(aligned[sym], ppy, rf)
        row: dict[str, Any] = {
            "symbol": sym,
            "quote_currency": currencies[sym],
            "last_price_local": an.num(close[sym].dropna().iloc[-1]),
            "last_price_base": an.num(base_px[sym].dropna().iloc[-1]),
            "value_base": an.num(values[sym], 2) if all(sized) else None,
            "weight_pct": an.pct(weights[sym]),
            **{k: stats[k] for k in keep},
        }
        if bench:
            rel = an.relative_stats(aligned[sym], aligned[bench], ppy, rf)
            row["beta"] = rel["beta"]
            row["correlation_to_benchmark"] = rel["correlation"]
        if risk:
            row["risk_contribution_pct"] = risk["by_position"][sym][
                "risk_contribution_pct"
            ]
        rows.append(row)

    isin_notes = []
    for opts, sym, info in zip(options, chosen, resolved, strict=True):
        if info:
            isin_notes.append(
                {**info, "symbol": sym, "alternatives": [o for o in opts if o != sym]}
            )
    fx_used = (
        {str(c): an.num(fx[c].dropna().iloc[-1], 6) for c in fx.columns}
        if not fx.empty
        else {}
    )

    return {
        "base_currency": base,
        "window": {
            "from": an.day(aligned.index[0]),
            "to": an.day(aligned.index[-1]),
            "interval": interval,
            "observations": len(aligned) - 1,
        },
        "method": method,
        "risk_free_rate_pct": risk_free_rate_pct,
        "total_value": an.num(sum(values.values()), 2) if all(sized) else None,
        "portfolio": portfolio,
        "benchmark": bench_out,
        "risk": (
            {
                "portfolio_volatility_pct": risk["portfolio_volatility_pct"],
                "diversification_ratio": risk["diversification_ratio"],
            }
            if risk
            else None
        ),
        "positions": rows,
        "correlation": an.correlation_matrix(port_px) if len(pos_syms) > 1 else None,
        "isin_resolution": isin_notes,
        "fx_rates_used": {f"{c}{base}": r for c, r in fx_used.items()},
        "warnings": warnings,
        "notes": [
            f"All prices converted to {base} with daily FX, so currency moves are "
            "part of the risk and return.",
            "Prices are adjusted for splits and dividends (total return).",
            "current_holdings = today's units held through the whole window; "
            "constant_weights = rebalanced to today's weights every period.",
            "Risk contributions use today's weights and sum to 100%.",
            "Past performance does not predict future results.",
        ],
    }
