"""MCP tools backed by justETF. ``register(mcp)`` adds them to a FastMCP server."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import analysis, search, service
from .client import JustEtfError

SOURCE = (
    "justETF (https://www.justetf.com), personal use; data may lag the fund provider."
)


def _with_source(data: dict) -> dict:
    return {**data, "source": SOURCE}


def _load(isin: str, refresh: bool = False) -> dict:
    """Profile, or ``{"error": ...}`` for the tool to return as is."""
    try:
        return service.get_profile(isin, refresh=refresh)
    except JustEtfError as exc:
        return {"error": str(exc)}


def _split_positions(
    positions: list[dict[str, Any]],
) -> tuple[list[str], list[float | None]]:
    isins, amounts = [], []
    for pos in positions:
        isins.append(str(pos.get("isin", "")))
        raw = pos.get("amount", pos.get("weight"))
        amounts.append(None if raw in (None, "") else float(raw))
    return isins, amounts


def register(mcp: FastMCP) -> None:
    """Register all justETF tools on the given server."""

    @mcp.tool()
    def search_etf(query: str, max_results: int = 8, use_yahoo: bool = True) -> dict:
        """Find an ETF's ISIN from its name, ticker or index (use this first).

        Accepts e.g. "iShares Core MSCI World", "IWDA", "vanguard all world acc"
        or an ISIN. Returns matches with ISIN, name and tickers. Yahoo Finance is
        used as a fallback for fuzzy names; hits that cannot be mapped to an ISIN
        come back in `unresolved_candidates` (isin null). Accumulating vs
        distributing and hedged variants look alike: if several matches are
        plausible, ASK THE USER which one they hold. All other justETF tools
        need the ISIN.

        Args:
            query: Fund name, ticker, index name or ISIN.
            max_results: Maximum matches to return.
            use_yahoo: Also query Yahoo Finance when the registry has no full match.
        """
        return search.search_etf(query, max(1, min(max_results, 20)), use_yahoo)

    @mcp.tool()
    def get_etf_profile(isin: str, refresh: bool = False) -> dict:
        """Key facts about an ETF from justETF, looked up by ISIN.

        Returns name, ticker, TER (% p.a.), fund size, distribution policy
        (accumulating/distributing), replication, index, fund currency and
        currency hedging, domicile, provider, inception date, number of holdings,
        legal structure, tax status per country, securities lending and a
        description. Example ISIN: IE00B4L5Y983 (iShares Core MSCI World, Acc).

        Args:
            isin: ETF ISIN (12 characters).
            refresh: Bypass the 24h cache and re-download the page.
        """
        p = _load(isin, refresh)
        if "error" in p:
            return p
        keys = [
            "isin", "name", "ticker", "url", "ter_pct", "fund_size",
            "distribution_policy", "replication", "inception_date",
            "number_of_holdings", "description", "basics", "legal_structure",
            "replication_details", "tax_status", "warnings", "from_cache",
        ]  # fmt: skip
        return _with_source({k: p.get(k) for k in keys})

    @mcp.tool()
    def get_etf_exposure(
        isin: str,
        section: str = "all",
        refresh: bool = False,
    ) -> dict:
        """Country, sector and top-10 holdings breakdown of one ETF (justETF).

        justETF lists the largest ~10 countries and ~13 sectors; the remainder
        is reported as "Other". Top holdings are limited to the top 10.

        Args:
            isin: ETF ISIN.
            section: "countries", "sectors", "holdings" or "all".
            refresh: Bypass the 24h cache.
        """
        section = section.strip().lower()
        if section not in {"all", "countries", "sectors", "holdings"}:
            return {
                "error": "section must be one of: all, countries, sectors, holdings"
            }
        p = _load(isin, refresh)
        if "error" in p:
            return p
        h = p["holdings"]
        out: dict[str, Any] = {
            "isin": p["isin"],
            "name": p["name"],
            "as_of": h["as_of"],
            "number_of_holdings": p["number_of_holdings"],
        }
        if section in ("all", "countries"):
            out["countries"] = h["countries"]
        if section in ("all", "sectors"):
            out["sectors"] = h["sectors"]
        if section in ("all", "holdings"):
            out["top_10_holdings"] = h["top_10"]
            out["top_10_weight_pct"] = h["top_10_weight_pct"]
        out["warnings"] = p["warnings"]
        return _with_source(out)

    @mcp.tool()
    def get_etf_performance(isin: str, refresh: bool = False) -> dict:
        """Returns and risk of an ETF from justETF.

        Period returns (YTD, 1m, 3m, 6m, 1y, 3y, 5y, since inception), calendar
        year returns, volatility (1/3/5y), return per risk and maximum drawdown.
        Returns are in the currency named in `currency` (EUR by default).
        Past performance does not predict future results.

        Args:
            isin: ETF ISIN.
            refresh: Bypass the 24h cache.
        """
        p = _load(isin, refresh)
        if "error" in p:
            return p
        return _with_source(
            {
                "isin": p["isin"],
                "name": p["name"],
                "performance": p["performance"],
                "risk": p["risk"],
                "from_cache": p["from_cache"],
            }
        )

    @mcp.tool()
    def get_etf_listings(isin: str, refresh: bool = False) -> dict:
        """Exchanges where an ETF trades: currency, ticker, Bloomberg/Reuters codes.

        Useful to find the ticker for a specific exchange (e.g. XETRA vs London).

        Args:
            isin: ETF ISIN.
            refresh: Bypass the 24h cache.
        """
        p = _load(isin, refresh)
        if "error" in p:
            return p
        return _with_source(
            {"isin": p["isin"], "name": p["name"], "listings": p["listings"]}
        )

    @mcp.tool()
    def get_similar_etfs(isin: str, refresh: bool = False) -> dict:
        """ETFs on the same index (justETF's "further ETFs") with size, TER, policy.

        Good for "is there a cheaper ETF tracking the same index?".

        Args:
            isin: ETF ISIN.
            refresh: Bypass the 24h cache.
        """
        p = _load(isin, refresh)
        if "error" in p:
            return p
        base = {"ter_pct": p["ter_pct"], "fund_size": p["fund_size"]}
        return _with_source(
            {
                "isin": p["isin"],
                "name": p["name"],
                "index": p["basics"]["index"],
                "this_etf": base,
                "similar_etfs": p["similar_etfs"],
                "note": "fund_size_mn is in millions of the page currency.",
            }
        )

    @mcp.tool()
    def compare_etfs(isins: list[str], refresh: bool = False) -> dict:
        """Side-by-side comparison of up to 15 ETFs by ISIN.

        Cost (TER), fund size, distribution, replication, domicile, index,
        currency, hedging, inception, returns, volatility and holdings count,
        plus who is cheapest / largest.

        Args:
            isins: List of ETF ISINs.
            refresh: Bypass the 24h cache.
        """
        profiles, errors = service.get_profiles(isins, refresh=refresh)
        rows = []
        for p in profiles.values():
            ret = p["performance"]["period_returns_pct"]
            rows.append(
                {
                    "isin": p["isin"],
                    "name": p["name"],
                    "ter_pct": p["ter_pct"],
                    "fund_size": p["fund_size"],
                    "distribution_policy": p["distribution_policy"],
                    "replication": p["replication"],
                    "domicile": p["basics"]["domicile_country"],
                    "index": p["basics"]["index"],
                    "fund_currency": p["basics"]["fund_currency"],
                    "currency_risk": p["basics"]["currency_risk"],
                    "inception_date": p["inception_date"],
                    "number_of_holdings": p["number_of_holdings"],
                    "return_1y_pct": ret.get("1y"),
                    "return_3y_pct": ret.get("3y"),
                    "return_5y_pct": ret.get("5y"),
                    "volatility_1y_pct": p["basics"]["volatility_1y_pct"],
                }
            )
        priced = [r for r in rows if r["ter_pct"] is not None]
        sized = [r for r in rows if r["fund_size"]]
        return _with_source(
            {
                "etfs": rows,
                "cheapest": min(priced, key=lambda r: r["ter_pct"])["isin"]
                if priced
                else None,
                "largest": max(sized, key=lambda r: r["fund_size"]["amount_mn"])["isin"]
                if sized
                else None,
                "errors": errors,
            }
        )

    @mcp.tool()
    def analyze_portfolio(
        positions: list[dict[str, Any]],
        top_n: int = 15,
        focus_countries: list[str] | None = None,
        focus_sectors: list[str] | None = None,
        refresh: bool = False,
    ) -> dict:
        """Analyse a list of ETFs: cost, fund size, structure and look-through exposure.

        Give each position as {"isin": "...", "amount": 5000}. `amount` is the
        money (any currency, used for weights and yearly cost) or a weight; give
        it for every position or for none (equal weights).

        Returns weighted TER and yearly fees, fund size per ETF (with small-fund
        flags), portfolio share by distribution/replication/domicile/currency/
        provider/index, and combined exposure by country, sector and top stocks
        with each ETF's contribution. Use `focus_countries` / `focus_sectors`
        (e.g. ["United States"], ["Technology"]) to get only those buckets.
        Named buckets are lower bounds: justETF lumps the tail into "Other".

        Args:
            positions: List of {"isin": str, "amount": number (optional)}.
            top_n: Buckets to return per breakdown when no focus is given.
            focus_countries: Only return countries containing one of these names.
            focus_sectors: Only return sectors containing one of these names.
            refresh: Bypass the 24h cache.
        """
        if not positions:
            return {"error": "positions is empty"}
        try:
            isins, amounts = _split_positions(positions)
        except (TypeError, ValueError) as exc:
            return {"error": f"invalid positions: {exc}"}
        profiles, errors = service.get_profiles(isins, refresh=refresh)
        # keep amounts aligned with the ETFs that loaded successfully
        by_isin: dict[str, float | None] = {}
        for raw, amount in zip(isins, amounts, strict=True):
            try:
                key = service.normalize_isin(raw)
            except JustEtfError:
                continue
            if amount is not None:
                by_isin[key] = (by_isin.get(key) or 0) + amount
            else:
                by_isin.setdefault(key, None)
        loaded = list(profiles.values())
        if not loaded:
            return {"error": "no ETF could be loaded", "errors": errors}
        try:
            result = analysis.analyze_portfolio(
                loaded,
                [by_isin[p["isin"]] for p in loaded],
                top_n=max(1, min(top_n, 50)),
                focus_countries=focus_countries,
                focus_sectors=focus_sectors,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        if errors:
            result["errors"] = errors
            result["notes"].append(
                "Some ETFs failed to load and are excluded; weights were renormalised."
            )
        return _with_source(result)
