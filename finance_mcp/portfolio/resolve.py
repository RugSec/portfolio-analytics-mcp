"""ISIN -> Yahoo Finance tickers, using the exchange listings on justETF.

justETF lists each exchange (by MIC code and name) with the local ticker;
Yahoo symbols are that ticker plus an exchange suffix (XETRA -> ``.DE``,
Euronext Amsterdam -> ``.AS``, London -> ``.L``...). Venues Yahoo does not
carry (gettex, Tradegate, ...) are reported as unmapped.
"""

from __future__ import annotations

from typing import Any

from ..justetf import service
from ..justetf.client import JustEtfError, normalize_isin

# ISO 10383 MIC -> Yahoo suffix
MIC_SUFFIX = {
    "XETR": ".DE", "XETA": ".DE", "XFRA": ".F", "XSTU": ".SG", "XMUN": ".MU",
    "XDUS": ".DU", "XBER": ".BE", "XHAM": ".HM", "XHAN": ".HA",
    "XAMS": ".AS", "XPAR": ".PA", "XBRU": ".BR", "XLIS": ".LS", "XDUB": ".IR",
    "XMSM": ".IR", "XMIL": ".MI", "MTAA": ".MI", "ETFP": ".MI",
    "XLON": ".L", "XSWX": ".SW", "XVTX": ".SW", "XMAD": ".MC", "BMEX": ".MC",
    "XWBO": ".VI", "XSTO": ".ST", "XHEL": ".HE", "XCSE": ".CO", "XOSL": ".OL",
}  # fmt: skip
# fallback on the exchange's display name (lower-case substring -> suffix)
NAME_SUFFIX = [
    ("xetra", ".DE"), ("london", ".L"), ("amsterdam", ".AS"), ("paris", ".PA"),
    ("brussels", ".BR"), ("lisbon", ".LS"), ("dublin", ".IR"), ("milan", ".MI"),
    ("borsa italiana", ".MI"), ("six swiss", ".SW"), ("swiss", ".SW"),
    ("stuttgart", ".SG"), ("frankfurt", ".F"), ("munich", ".MU"),
    ("düsseldorf", ".DU"), ("dusseldorf", ".DU"), ("berlin", ".BE"),
    ("hamburg", ".HM"), ("hanover", ".HA"), ("hannover", ".HA"),
    ("vienna", ".VI"), ("madrid", ".MC"), ("stockholm", ".ST"),
    ("helsinki", ".HE"), ("copenhagen", ".CO"), ("oslo", ".OL"),
]  # fmt: skip
# most liquid / best covered on Yahoo first
SUFFIX_RANK = [".DE", ".AS", ".L", ".SW", ".PA", ".MI", ".BR", ".MC", ".VI"]


def yahoo_suffix(listing: dict[str, Any]) -> str | None:
    """Yahoo suffix for one justETF listing, or None if Yahoo lacks the venue."""
    mic = (listing.get("mic_code") or "").upper()
    if mic in MIC_SUFFIX:
        return MIC_SUFFIX[mic]
    name = (listing.get("exchange") or "").lower()
    for needle, suffix in NAME_SUFFIX:
        if needle in name:
            return suffix
    return None


def yahoo_candidates(
    listings: list[dict[str, Any]], base_currency: str | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rank Yahoo symbols for an ETF's listings.

    Order: trading currency equal to ``base_currency`` first (no FX noise),
    then by exchange liquidity (SUFFIX_RANK).

    Returns:
        ``(candidates, unmapped_listings)``.
    """
    base = (base_currency or "").upper()
    candidates: dict[str, dict[str, Any]] = {}
    unmapped = []
    for x in listings:
        ticker = (x.get("ticker") or "").strip().upper()
        suffix = yahoo_suffix(x)
        if not ticker or suffix is None:
            unmapped.append({k: x.get(k) for k in ("exchange", "mic_code", "ticker")})
            continue
        symbol = ticker + suffix
        candidates.setdefault(
            symbol,
            {
                "symbol": symbol,
                "exchange": x.get("exchange"),
                "mic_code": x.get("mic_code"),
                "trading_currency": x.get("trading_currency"),
            },
        )

    def rank(c: dict[str, Any]) -> tuple[int, int]:
        suffix = "." + c["symbol"].rsplit(".", 1)[-1]
        same_ccy = 0 if base and (c["trading_currency"] or "").upper() == base else 1
        pos = SUFFIX_RANK.index(suffix) if suffix in SUFFIX_RANK else len(SUFFIX_RANK)
        return same_ccy, pos

    return sorted(candidates.values(), key=rank), unmapped


def _yahoo_search_isin(isin: str) -> list[dict[str, Any]]:
    """Yahoo's own search accepts many ISINs (mostly single stocks)."""
    import yfinance as yf

    quotes = yf.Search(isin, max_results=10, news_count=0).quotes or []
    return [
        {
            "symbol": q["symbol"],
            "name": q.get("longname") or q.get("shortname"),
            "exchange": q.get("exchDisp") or q.get("exchange"),
            "type": q.get("quoteType"),
        }
        for q in quotes
        if q.get("symbol")
    ]


def resolve_isin(isin: str, base_currency: str | None = None) -> dict[str, Any]:
    """Yahoo ticker candidates for an ISIN, best first.

    ETFs: ranked from the exchange listings on justETF (cached 24h).
    Anything justETF does not know (e.g. single stocks): Yahoo search by ISIN.

    Raises:
        JustEtfError: invalid ISIN, or neither source found anything.
    """
    isin = normalize_isin(isin)
    try:
        profile = service.get_profile(isin)
    except JustEtfError as exc:
        try:
            hits = _yahoo_search_isin(isin)
        except Exception:  # noqa: BLE001 - network/library errors
            hits = []
        if not hits:
            raise JustEtfError(f"{exc}; Yahoo search found nothing either") from exc
        return {
            "isin": isin,
            "name": hits[0]["name"],
            "source": "yahoo_search",
            "yahoo_candidates": hits,
            "unmapped_listings": [],
        }
    candidates, unmapped = yahoo_candidates(profile["listings"], base_currency)
    return {
        "isin": profile["isin"],
        "name": profile["name"],
        "source": "justetf_listings",
        "yahoo_candidates": candidates,
        "unmapped_listings": unmapped,
    }
