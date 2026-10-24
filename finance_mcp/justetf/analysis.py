"""Portfolio maths on parsed justETF profiles. Pure functions, no network."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

SMALL_FUND_MN = 100.0  # below this, closure/liquidity risk is worth a mention
OTHER = "Other"


def _r(x: float, digits: int = 2) -> float:
    """Round for output.

    Args:
        x: Value to round.
        digits: Decimal places to keep.

    Returns:
        The rounded value.
    """
    return round(x, digits)


def compute_weights(amounts: list[float | None]) -> list[float]:
    """Normalise amounts to weights summing to 1 (equal weights if none given).

    Args:
        amounts: Money or weight per ETF; all None for equal weights.

    Returns:
        One weight per ETF, in input order.

    Raises:
        ValueError: if only some amounts are given, or any is not positive.
    """
    if all(a is None for a in amounts):
        return [1 / len(amounts)] * len(amounts)
    if any(a is None for a in amounts):
        raise ValueError("give an amount for every ETF, or for none (equal weights)")
    values = [float(a) for a in amounts if a is not None]
    if any(v <= 0 for v in values):
        raise ValueError("amounts must be positive")
    total = sum(values)
    return [v / total for v in values]


def _matches(name: str, focus: list[str] | None) -> bool:
    """Check whether a bucket name contains any of the focus strings.

    Args:
        name: Country or sector name.
        focus: Case-insensitive substrings; None or empty matches everything.

    Returns:
        True if the bucket should be shown.
    """
    if not focus:
        return True
    low = name.lower()
    return any(f.strip().lower() in low for f in focus if f.strip())


def aggregate_exposure(
    entries: list[dict[str, Any]],
    group: str,
    top_n: int = 15,
    focus: list[str] | None = None,
) -> dict[str, Any]:
    """Combine one breakdown ('countries' or 'sectors') across ETFs.

    Args:
        entries: ``[{"profile": dict, "weight": float}, ...]``, weights sum to 1.
        group: ``"countries"`` or ``"sectors"``.
        top_n: Max buckets to return when no focus is given.
        focus: Only return buckets whose name contains one of these strings.

    Returns:
        ``{"buckets": [...], "other_pct": float, "unavailable": [isin, ...]}``.
        ``other_pct`` is the part justETF does not itemise ("Other"), so every
        named bucket is a lower bound.
    """
    totals: dict[str, float] = defaultdict(float)
    by_etf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    other = 0.0
    unavailable: list[str] = []
    for entry in entries:
        profile, weight = entry["profile"], entry["weight"]
        rows = profile["holdings"][group]
        if not rows:
            unavailable.append(profile["isin"])
            continue
        for row in rows:
            # Portfolio exposure = ETF weight in the portfolio x bucket weight
            # inside the ETF.
            contribution = weight * row["weight_pct"]
            if row["name"] == OTHER:
                other += contribution
                continue
            totals[row["name"]] += contribution
            by_etf[row["name"]].append(
                {
                    "isin": profile["isin"],
                    "pct_within_etf": row["weight_pct"],
                    "pct_of_portfolio": _r(contribution),
                }
            )
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    if focus:
        ranked = [kv for kv in ranked if _matches(kv[0], focus)]
    else:
        ranked = ranked[:top_n]
    return {
        "buckets": [
            {
                "name": name,
                "pct_of_portfolio": _r(pct),
                "by_etf": sorted(by_etf[name], key=lambda d: -d["pct_of_portfolio"]),
            }
            for name, pct in ranked
        ],
        "other_pct": _r(other),
        "unavailable": unavailable,
    }


def aggregate_holdings(
    entries: list[dict[str, Any]], top_n: int = 15
) -> dict[str, Any]:
    """Look through the top-10 holdings of each ETF to find stock overlap.

    Args:
        entries: ``[{"profile": dict, "weight": float}, ...]``, weights sum to 1.
        top_n: Maximum stocks to return.

    Returns:
        ``top_stocks`` with their portfolio share and the ETFs holding them,
        the portfolio share covered by the listed top 10s, and the stocks held
        by more than one ETF.
    """
    stocks: dict[str, dict[str, Any]] = {}
    for entry in entries:
        profile, weight = entry["profile"], entry["weight"]
        for h in profile["holdings"]["top_10"]:
            key = h["isin"] or h["name"]  # same stock across ETFs, by ISIN
            slot = stocks.setdefault(
                key, {"name": h["name"], "isin": h["isin"], "total": 0.0, "held_by": []}
            )
            contribution = weight * h["weight_pct"]
            slot["total"] += contribution
            slot["held_by"].append(
                {"etf_isin": profile["isin"], "pct_of_portfolio": _r(contribution)}
            )
    ranked = sorted(stocks.values(), key=lambda s: s["total"], reverse=True)
    covered = sum(
        entry["weight"] * (entry["profile"]["holdings"]["top_10_weight_pct"] or 0)
        for entry in entries
    )
    return {
        "top_stocks": [
            {
                "name": s["name"],
                "isin": s["isin"],
                "pct_of_portfolio": _r(s["total"]),
                "number_of_etfs": len(s["held_by"]),
                "held_by": s["held_by"],
            }
            for s in ranked[:top_n]
        ],
        "pct_of_portfolio_in_listed_top10s": _r(covered),
        "stocks_in_multiple_etfs": [s["name"] for s in ranked if len(s["held_by"]) > 1][
            :top_n
        ],
    }


def structure_breakdown(entries: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Compute the share of the portfolio by distribution, replication, domicile...

    Args:
        entries: ``[{"profile": dict, "weight": float}, ...]``, weights sum to 1.

    Returns:
        ``{field: {value: pct_of_portfolio}}``, largest share first.
    """
    fields = {
        "distribution_policy": lambda p: p.get("distribution_policy"),
        "replication": lambda p: p.get("replication"),
        "domicile": lambda p: p["basics"].get("domicile_country"),
        "fund_currency": lambda p: p["basics"].get("fund_currency"),
        "currency_risk": lambda p: p["basics"].get("currency_risk"),
        "provider": lambda p: p["basics"].get("fund_provider"),
        "index": lambda p: p["basics"].get("index"),
    }
    out: dict[str, dict[str, float]] = {}
    for field, getter in fields.items():
        shares: dict[str, float] = defaultdict(float)
        for entry in entries:
            shares[getter(entry["profile"]) or "Unknown"] += entry["weight"] * 100
        out[field] = {
            k: _r(v) for k, v in sorted(shares.items(), key=lambda kv: -kv[1])
        }
    return out


def _pick(positions: list[dict[str, Any]], field: str, fn: Any) -> dict | None:
    """Find the position with the max/min of ``field``.

    Args:
        positions: Rows from ``cost_and_size``.
        field: ``"ter_pct"`` or ``"fund_size"``.
        fn: ``max`` or ``min``.

    Returns:
        ``{"isin", "name", field}`` of that position, or None if no position
        has the field.
    """
    valued = [x for x in positions if x[field] is not None]
    if not valued:
        return None
    key = (
        (lambda x: x[field]["amount_mn"])
        if field == "fund_size"
        else (lambda x: x[field])
    )
    best = fn(valued, key=key)
    return {"isin": best["isin"], "name": best["name"], field: best[field]}


def cost_and_size(
    entries: list[dict[str, Any]], amounts: list[float | None]
) -> dict[str, Any]:
    """Compute the weighted TER, yearly cost per ETF and fund-size flags.

    Args:
        entries: ``[{"profile": dict, "weight": float}, ...]``, weights sum to 1.
        amounts: Money per ETF (all None when weights were equal).

    Returns:
        Per-position rows plus ``weighted_ter_pct``, ``total_annual_cost``,
        ``most_expensive`` and ``smallest_fund``.
    """
    have_amounts = all(a is not None for a in amounts)
    positions = []
    weighted = 0.0
    weight_with_ter = 0.0
    total_amount = sum(a for a in amounts if a is not None) if have_amounts else None
    for entry, amount in zip(entries, amounts, strict=True):
        p, w = entry["profile"], entry["weight"]
        ter = p.get("ter_pct")
        size = p.get("fund_size")
        if ter is not None:
            weighted += w * ter
            weight_with_ter += w
        flags = []
        if size and size["amount_mn"] < SMALL_FUND_MN:
            flags.append(
                f"small fund (< {SMALL_FUND_MN:.0f}m): higher closure/liquidity risk"
            )
        positions.append(
            {
                "isin": p["isin"],
                "name": p["name"],
                "weight_pct": _r(w * 100),
                "amount": amount,
                "ter_pct": ter,
                "annual_cost": _r(amount * ter / 100)
                if (amount is not None and ter is not None)
                else None,
                "fund_size": size,
                "flags": flags,
            }
        )
    # Average only over ETFs with a known TER, re-scaled to their weight.
    weighted_ter = weighted / weight_with_ter if weight_with_ter else None
    return {
        "positions": positions,
        "weighted_ter_pct": _r(weighted_ter, 3) if weighted_ter is not None else None,
        "total_amount": total_amount,
        "total_annual_cost": _r(total_amount * weighted_ter / 100)
        if (total_amount is not None and weighted_ter is not None)
        else None,
        "most_expensive": _pick(positions, "ter_pct", max),
        "smallest_fund": _pick(positions, "fund_size", min),
    }


def analyze_portfolio(
    profiles: list[dict],
    amounts: list[float | None],
    top_n: int = 15,
    focus_countries: list[str] | None = None,
    focus_sectors: list[str] | None = None,
) -> dict[str, Any]:
    """Analyse ETFs as one portfolio: cost, size, structure and exposure.

    Args:
        profiles: Parsed profiles, one per ETF.
        amounts: Money or weight per ETF, or all None for equal weights.
        top_n: Buckets to return per breakdown when no focus is given.
        focus_countries: Only return countries containing one of these names.
        focus_sectors: Only return sectors containing one of these names.

    Returns:
        ``cost_and_size``, ``structure_pct``, ``country_exposure``,
        ``sector_exposure``, ``stock_look_through``, ``holdings_as_of`` and
        ``notes``.
    """
    weights = compute_weights(amounts)
    entries = [
        {"profile": p, "weight": w} for p, w in zip(profiles, weights, strict=True)
    ]
    as_of = sorted({p["holdings"]["as_of"] for p in profiles if p["holdings"]["as_of"]})
    return {
        "cost_and_size": cost_and_size(entries, amounts),
        "structure_pct": structure_breakdown(entries),
        "country_exposure": aggregate_exposure(
            entries, "countries", top_n, focus_countries
        ),
        "sector_exposure": aggregate_exposure(entries, "sectors", top_n, focus_sectors),
        "stock_look_through": aggregate_holdings(entries, top_n),
        "holdings_as_of": as_of,
        "notes": [
            "Exposure = sum over ETFs of (portfolio weight x ETF bucket weight).",
            "justETF itemises only the largest countries/sectors; 'other_pct' is "
            "the rest, so named buckets are lower bounds.",
            "Stock look-through covers only each ETF's top 10 holdings.",
            "Country/sector names follow justETF's own classification.",
        ],
    }
