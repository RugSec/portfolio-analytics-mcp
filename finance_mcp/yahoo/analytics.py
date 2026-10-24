"""Return and risk maths on price series. Pure pandas/numpy, no network.

Every function takes prices that are already in one currency and on one
calendar; ``align_prices`` and ``to_base_currency`` get them there.
"""

from __future__ import annotations

import math
from typing import Any, Literal

import numpy as np
import pandas as pd

PERIODS_PER_YEAR = {"1d": 252, "1wk": 52, "1mo": 12}
# Yahoo quotes some listings in minor units (e.g. LSE in pence, "GBp").
MINOR_CURRENCIES: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 0.01),
    "GBX": ("GBP", 0.01),
    "ZAc": ("ZAR", 0.01),
    "ILA": ("ILS", 0.01),
}
HoldingMethod = Literal["current_holdings", "constant_weights"]
EPS = 1e-12  # treat smaller dispersion as zero (float noise)


def num(x: Any, digits: int = 4) -> float | None:
    """Rounded float, or None for missing, NaN, infinite or non-numeric input."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, digits)


def pct(x: Any, digits: int = 2) -> float | None:
    """A fraction as a rounded percentage (0.1234 -> 12.34)."""
    value = num(x, 10)
    return None if value is None else round(value * 100, digits)


def day(x: Any) -> str:
    """Any date-like index value as YYYY-MM-DD."""
    return pd.Timestamp(x).strftime("%Y-%m-%d")


# ------------------------------------------------------------------ currency
def major_currency(code: str | None) -> tuple[str | None, float]:
    """Map a Yahoo currency code to (ISO currency, factor to convert into it).

    >>> major_currency("GBp")
    ('GBP', 0.01)
    """
    if not code:
        return None, 1.0
    if code in MINOR_CURRENCIES:
        return MINOR_CURRENCIES[code]
    return code.upper(), 1.0


def to_base_currency(
    prices: pd.DataFrame,
    currencies: dict[str, str | None],
    fx: pd.DataFrame,
    base: str,
) -> pd.DataFrame:
    """Convert each column of local-currency prices into ``base``.

    Args:
        prices: One column per symbol, in that symbol's quote currency.
        currencies: Yahoo currency code per symbol (minor units like "GBp" ok).
        fx: One column per ISO currency: units of ``base`` per 1 unit of it,
            on any (e.g. daily) calendar; it is forward-filled onto ``prices``.
        base: ISO code of the target currency, e.g. "EUR".

    Raises:
        ValueError: if a currency is unknown or its FX rate is missing.
    """
    base = base.upper()
    out: dict[str, pd.Series] = {}
    for col in prices.columns:
        major, factor = major_currency(currencies.get(str(col)))
        if major is None:
            raise ValueError(f"unknown quote currency for {col}")
        series = prices[col] * factor
        if major != base:
            if major not in fx.columns:
                raise ValueError(f"no FX rate {major}->{base} for {col}")
            rate = fx[major].dropna()
            rate = (
                rate.reindex(rate.index.union(series.index))
                .sort_index()
                .ffill()
                .bfill(limit=5)  # first bar may predate the first FX print
            )
            series = series * rate.reindex(series.index)
        out[str(col)] = series
    return pd.DataFrame(out, index=prices.index)


# ------------------------------------------------------------------ data quality
def remove_spikes(
    prices: pd.DataFrame, threshold: float = 0.15
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Drop one-day bad prints: a jump that is fully reversed the next period.

    A price is treated as bad when it moves more than ``threshold`` from the
    previous price, the next price moves back by a similar amount in the other
    direction, and the next price is close to the previous one. Yahoo has such
    prints on some listings (e.g. a London ETF recorded once in US cents
    instead of pence). Real moves that stick are kept. The last price cannot
    be checked (there is no next one).

    Returns:
        ``(cleaned prices, {symbol: [removed dates]})``; removed prices become
        NaN, which ``align_prices`` later forward-fills.
    """
    cleaned = prices.copy()
    removed: dict[str, list[str]] = {}
    for col in cleaned.columns:
        s = cleaned[col].dropna()
        v = np.array(s, dtype=float)  # writable copy (pandas 3 is copy-on-write)
        bad: list[int] = []
        i = 1
        while i < len(v) - 1:
            prev = v[i - 1]
            up = v[i] / prev - 1
            back = v[i + 1] / v[i] - 1
            if (
                abs(up) > threshold
                and up * back < 0
                and abs(v[i + 1] / prev - 1) < threshold / 3
            ):
                bad.append(i)
                v[i] = prev  # so the next comparison uses a sane base
                i += 2
                continue
            i += 1
        if bad:
            dates = [s.index[j] for j in bad]
            cleaned.loc[dates, col] = np.nan
            removed[str(col)] = [day(d) for d in dates]
    return cleaned, removed


# ------------------------------------------------------------------ calendar
def align_prices(prices: pd.DataFrame, max_gap: int = 5) -> pd.DataFrame:
    """Put series from different exchanges on one calendar.

    Exchange holidays (and a last quote that lags by a day or two) are
    forward-filled for at most ``max_gap`` periods, then only dates where every
    series has a price are kept, i.e. the common window.
    """
    return prices.sort_index().ffill(limit=max_gap).dropna(how="any")


def window_report(prices: pd.DataFrame) -> dict[str, Any]:
    """First/last valid date per series and which series limit the window."""
    first: dict[str, pd.Timestamp] = {}
    last: dict[str, pd.Timestamp] = {}
    for col in prices.columns:
        s = prices[col].dropna()
        if len(s):
            first[str(col)] = pd.Timestamp(s.index[0])
            last[str(col)] = pd.Timestamp(s.index[-1])
    if not first:
        return {
            "first_dates": {},
            "last_dates": {},
            "window_limited_by": [],
            "stale": {},
        }
    latest_start = max(first.values())
    newest = max(last.values())
    limiting = [k for k, v in first.items() if v == latest_start]
    return {
        "first_dates": {k: day(v) for k, v in first.items()},
        "last_dates": {k: day(v) for k, v in last.items()},
        "window_limited_by": limiting if len(limiting) < len(first) else [],
        "stale": {k: day(v) for k, v in last.items() if (newest - v).days > 3},
    }


# ------------------------------------------------------------------ single series
def max_drawdown(values: pd.Series) -> dict[str, Any]:
    """Deepest peak-to-trough fall, with peak, trough and recovery dates."""
    v = values.to_numpy(dtype=float)
    dd = v / np.maximum.accumulate(v) - 1
    trough = int(np.argmin(dd))
    peak = int(np.argmax(v[: trough + 1]))
    recovered = np.nonzero(v[trough:] >= v[peak])[0]
    if dd[trough] >= 0:  # never fell below a previous high
        return {
            "max_drawdown_pct": 0.0,
            "peak_date": None,
            "trough_date": None,
            "recovery_date": None,
        }
    return {
        "max_drawdown_pct": pct(dd[trough]),
        "peak_date": day(values.index[peak]),
        "trough_date": day(values.index[trough]),
        "recovery_date": day(values.index[trough + int(recovered[0])])
        if len(recovered)
        else None,
    }


def _per_period_rf(risk_free_rate: float, periods_per_year: int) -> float:
    return (1 + risk_free_rate) ** (1 / periods_per_year) - 1


def series_stats(
    prices: pd.Series, periods_per_year: int, risk_free_rate: float = 0.0
) -> dict[str, Any]:
    """Return and risk statistics of one (total-return) price series.

    Args:
        prices: Adjusted prices or portfolio values, oldest first.
        periods_per_year: 252 for daily, 52 weekly, 12 monthly.
        risk_free_rate: Annual rate as a fraction (0.02 = 2%), for Sharpe/Sortino.

    Annualised return is only given for windows of at least one year, so a
    short lucky stretch is not extrapolated.

    Raises:
        ValueError: with fewer than 3 prices.
    """
    s = prices.dropna()
    if len(s) < 3:
        raise ValueError("not enough data (need at least 3 prices)")
    rets = s.pct_change().dropna()
    first, last = pd.Timestamp(s.index[0]), pd.Timestamp(s.index[-1])
    years = (last - first).days / 365.25
    total = float(s.iloc[-1] / s.iloc[0] - 1)
    cagr = (1 + total) ** (1 / years) - 1 if years >= 1 else None
    std = float(rets.std(ddof=1))
    vol = std * math.sqrt(periods_per_year)
    excess = rets - _per_period_rf(risk_free_rate, periods_per_year)
    sharpe = (
        float(excess.mean()) / std * math.sqrt(periods_per_year) if std > EPS else None
    )
    downside = float(np.sqrt((np.minimum(excess, 0) ** 2).mean()))
    sortino = (
        float(excess.mean()) / downside * math.sqrt(periods_per_year)
        if downside > EPS
        else None
    )
    dd = max_drawdown(s)
    mdd = (dd["max_drawdown_pct"] or 0) / 100
    calmar = cagr / abs(mdd) if cagr is not None and mdd < 0 else None
    return {
        "from": day(first),
        "to": day(last),
        "observations": len(rets),
        "years": round(years, 2),
        "total_return_pct": pct(total),
        "annualized_return_pct": pct(cagr) if cagr is not None else None,
        "annualized_volatility_pct": pct(vol),
        "sharpe_ratio": num(sharpe, 2),
        "sortino_ratio": num(sortino, 2),
        "calmar_ratio": num(calmar, 2),
        **dd,
        "best_period_return_pct": pct(rets.max()),
        "worst_period_return_pct": pct(rets.min()),
    }


def relative_stats(
    asset: pd.Series,
    benchmark: pd.Series,
    periods_per_year: int,
    risk_free_rate: float = 0.0,
) -> dict[str, Any]:
    """Beta, Jensen's alpha, correlation, tracking error, information ratio.

    Both inputs are price series; their returns are compared on common dates.
    """
    rets = pd.concat([asset, benchmark], axis=1).pct_change().dropna()
    if len(rets) < 3:
        raise ValueError("not enough overlapping data with the benchmark")
    a, b = rets.iloc[:, 0], rets.iloc[:, 1]
    var_b = float(b.var(ddof=1))
    beta = float(a.cov(b)) / var_b if var_b > EPS else None
    rf = _per_period_rf(risk_free_rate, periods_per_year)
    alpha = (
        (float((a - rf).mean()) - beta * float((b - rf).mean())) * periods_per_year
        if beta is not None
        else None
    )
    active = a - b
    te = float(active.std(ddof=1)) * math.sqrt(periods_per_year)
    info = float(active.mean()) * periods_per_year / te if te > EPS else None
    return {
        "beta": num(beta, 3),
        "alpha_annualized_pct": pct(alpha) if alpha is not None else None,
        "correlation": num(a.corr(b), 3),
        "tracking_error_pct": pct(te),
        "information_ratio": num(info, 2),
    }


# ------------------------------------------------------------------ portfolio
def normalize_weights(weights: pd.Series) -> pd.Series:
    """Scale positive weights to sum to 1."""
    if (weights <= 0).any():
        raise ValueError("weights must be positive")
    return weights / weights.sum()


def portfolio_values(
    prices: pd.DataFrame,
    weights: pd.Series,
    method: HoldingMethod = "current_holdings",
) -> pd.Series:
    """Value of a portfolio through time, starting at 100.

    ``current_holdings``: today's units held unchanged over the whole window
    (weights drift with prices and match ``weights`` on the last date).
    ``constant_weights``: rebalanced back to ``weights`` every period.
    """
    w = normalize_weights(weights.reindex(prices.columns))
    if method == "current_holdings":
        units = w / prices.iloc[-1]
        values = (prices * units).sum(axis=1)
    elif method == "constant_weights":
        rets = prices.pct_change().fillna(0.0)
        values = (1 + rets.mul(w, axis=1).sum(axis=1)).cumprod()
    else:
        raise ValueError("method must be 'current_holdings' or 'constant_weights'")
    return values / values.iloc[0] * 100


def risk_contributions(
    prices: pd.DataFrame, weights: pd.Series, periods_per_year: int
) -> dict[str, Any]:
    """Split portfolio volatility into each position's contribution.

    Uses the covariance of returns and the given (current) weights:
    contribution_i = w_i * (Cov w)_i / vol, which sums to the portfolio vol.
    ``diversification_ratio`` is sum(w_i * vol_i) / portfolio vol (1 = none).
    """
    rets = prices.pct_change().dropna()
    cov = rets.cov() * periods_per_year
    w = normalize_weights(weights.reindex(cov.columns)).to_numpy(dtype=float)
    sigma = cov.to_numpy(dtype=float)
    port_vol = float(math.sqrt(w @ sigma @ w))
    if port_vol < EPS:
        raise ValueError("portfolio has zero volatility")
    marginal = sigma @ w / port_vol
    contrib = w * marginal
    vols = np.sqrt(np.diag(sigma))
    return {
        "portfolio_volatility_pct": pct(port_vol),
        "diversification_ratio": num(float(w @ vols) / port_vol, 3),
        "by_position": {
            str(sym): {
                "weight_pct": pct(w[i]),
                "volatility_pct": pct(vols[i]),
                "risk_contribution_pct": pct(contrib[i] / port_vol),
                "marginal_volatility_pct": pct(marginal[i]),
            }
            for i, sym in enumerate(cov.columns)
        },
    }


def correlation_matrix(prices: pd.DataFrame, digits: int = 3) -> dict[str, Any]:
    """Pairwise correlation of returns as a nested dict."""
    corr = prices.pct_change().dropna().corr()
    return {
        str(a): {str(b): num(corr.loc[a, b], digits) for b in corr.columns}
        for a in corr.index
    }
