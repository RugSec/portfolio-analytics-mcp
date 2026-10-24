"""Name / ticker -> ISIN search for ETFs.

Order: (1) a valid ISIN is returned as is, (2) the local registry, (3) Yahoo
Finance search for fuzzy names and listings, mapped onto ISINs via the registry
(by ticker, then by exact name). Unmapped Yahoo hits are returned with
``isin: null`` instead of guessing.
"""

from __future__ import annotations

from typing import Any

from . import registry
from .client import JustEtfError, normalize_isin

ETF_TYPES = {"ETF", "MUTUALFUND"}


def _yahoo_candidates(query: str, limit: int) -> list[dict[str, Any]]:
    """Search Yahoo for funds matching a query.

    Args:
        query: Free-text query.
        limit: Maximum Yahoo results.

    Returns:
        Yahoo quotes of ETFs and mutual funds only.
    """
    import yfinance as yf

    quotes = yf.Search(query, max_results=limit, news_count=0).quotes or []
    return [q for q in quotes if q.get("symbol") and q.get("quoteType") in ETF_TYPES]


def _resolve_yahoo(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group Yahoo listings of the same fund and attach an ISIN when known.

    Args:
        quotes: Yahoo search quotes.

    Returns:
        One group per fund: ``isin`` (or None), ``name`` and ``yahoo_listings``.
    """
    tickers = registry.by_ticker()
    names = registry.by_name()
    known = registry.load()
    groups: dict[str, dict[str, Any]] = {}
    for q in quotes:
        symbol = str(q["symbol"])
        name = q.get("longname") or q.get("shortname") or symbol
        base = symbol.split(".")[0].lower()  # "IWDA.AS" -> "iwda"
        isin = None
        candidates = tickers.get(base, [])
        if len(candidates) == 1:
            isin = candidates[0]
        elif len(candidates) > 1:  # same ticker on different funds: use the name
            isin = names.get(" ".join(registry.tokens(name)))
        else:
            isin = names.get(" ".join(registry.tokens(name)))
        # Group by ISIN when known, else by normalised name.
        key = isin or " ".join(registry.tokens(name))
        group = groups.setdefault(
            key,
            {
                "isin": isin,
                "name": known[isin]["name"] if isin else name,
                "yahoo_listings": [],
            },
        )
        group["yahoo_listings"].append(
            {"symbol": symbol, "exchange": q.get("exchDisp") or q.get("exchange")}
        )
    return list(groups.values())


def search_etf(
    query: str, max_results: int = 8, use_yahoo: bool = True
) -> dict[str, Any]:
    """Find ETFs (with ISIN) matching a name, ticker or ISIN.

    Args:
        query: Fund name, ticker, index or ISIN.
        max_results: Maximum matches to return.
        use_yahoo: Query Yahoo when the registry has no full match.

    Returns:
        ``matches`` (with ``isin`` and ``match`` type), optional
        ``unresolved_candidates`` and ``warnings``, and a ``note`` for the agent.
    """
    query = (query or "").strip()
    if not query:
        return {"error": "query is empty"}
    try:  # an ISIN needs no search
        isin = normalize_isin(query)
        known = registry.load().get(isin, {})
        return {
            "query": query,
            "matches": [{"isin": isin, "name": known.get("name"), "match": "isin"}],
        }
    except JustEtfError:
        pass

    matches = registry.search(query, max_results)
    warnings: list[str] = []
    yahoo: list[dict[str, Any]] = []
    if use_yahoo and not any(m["match"] == "full" for m in matches):
        try:
            yahoo = _resolve_yahoo(_yahoo_candidates(query, 10))
        except Exception as exc:  # noqa: BLE001 - network/library errors
            warnings.append(f"Yahoo search failed: {exc}")
        seen = {m["isin"] for m in matches}
        for group in yahoo:
            if group["isin"] and group["isin"] not in seen:
                matches.append({**group, "match": "yahoo"})
        yahoo = [g for g in yahoo if not g["isin"]]

    out: dict[str, Any] = {"query": query, "matches": matches[:max_results]}
    if yahoo:
        out["unresolved_candidates"] = yahoo[:max_results]
    if warnings:
        out["warnings"] = warnings
    matches_out = out["matches"]
    if not matches_out or all(m["match"] in ("partial", "yahoo") for m in matches_out):
        out["note"] = (
            "No exact match with a known ISIN. Ask the user for the ISIN (broker "
            "page / KID) or look it up on the web, then call get_etf_profile to "
            "confirm; the ETF is remembered for next time."
        )
    elif len(matches_out) > 1 or matches_out[0]["match"] != "isin":
        out["note"] = (
            "Several share classes can look alike (accumulating vs distributing, "
            "hedged, currency). Confirm with the user which one before analysing."
        )
    return out
