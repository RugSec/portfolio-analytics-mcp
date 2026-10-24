"""Local ETF registry (ISIN, name, tickers) used for name -> ISIN lookup.

justETF's own search is not an option (its AJAX endpoint is disallowed by
robots.txt) and Yahoo cannot return ISINs, so we keep a small registry:

* a seed list shipped in ``data/etfs.json`` (popular ETFs, each verified
  against its justETF profile page), and
* entries learned from every profile that is fetched (the ETF itself, with all
  its listing tickers, plus the "similar ETFs" it mentions).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import client

SEED_FILE = Path(__file__).parent / "data" / "etfs.json"
_IGNORED = {
    "ucits",
    "etf",
    "the",
    "ucit",
    "fund",
    "usd",
    "eur",
    "gbp",
    "chf",
    "ucitsetf",
}
_SYNONYMS = {
    "accumulating": "acc",
    "accumulation": "acc",
    "distributing": "dist",
    "distribution": "dist",
    "income": "dist",
    "hedged": "hedged",
}


def _learned_file() -> Path:
    """Get the path of the learned registry (inside the cache directory).

    Returns:
        The JSON file path.
    """
    return client.CACHE_DIR / "registry.json"


def tokens(text: str) -> list[str]:
    """Split text into lower-case search tokens, share-class synonyms normalised.

    Filler words ("UCITS", "ETF", currency codes) are dropped.

    Args:
        text: A fund name, index or query.

    Returns:
        The tokens, e.g. "Accumulating" -> "acc".
    """
    out = []
    for tok in re.findall(r"[a-z0-9]+", text.lower()):
        tok = _SYNONYMS.get(tok, tok)
        if tok not in _IGNORED:
            out.append(tok)
    return out


def _read(path: Path) -> list[dict[str, Any]]:
    """Read registry entries from the seed list or the learned file.

    Args:
        path: JSON file: a list (seed) or a dict keyed by ISIN (learned).

    Returns:
        Entries with an ISIN; empty if the file is missing or invalid.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):  # learned file is keyed by ISIN
        data = list(data.values())
    return [e for e in data if isinstance(e, dict) and e.get("isin")]


def load() -> dict[str, dict[str, Any]]:
    """Load all known ETFs by ISIN; learned data extends/overrides the seed.

    Returns:
        ``{isin: {"isin", "name", "tickers", "index"}}``; tickers are merged.
    """
    merged: dict[str, dict[str, Any]] = {}
    for entry in _read(SEED_FILE) + _read(_learned_file()):
        slot = merged.setdefault(entry["isin"], {"isin": entry["isin"], "tickers": []})
        slot.update({k: v for k, v in entry.items() if v and k != "tickers"})
        slot["tickers"] = sorted(set(slot["tickers"]) | set(entry.get("tickers") or []))
    return merged


def learn(profile: dict[str, Any]) -> None:
    """Remember a fetched profile (and its similar ETFs) for later name lookups.

    Args:
        profile: A parsed profile from ``parser.parse_profile``.
    """
    entries = [
        {
            "isin": profile["isin"],
            "name": profile["name"],
            "tickers": sorted(
                {x["ticker"] for x in profile["listings"] if x["ticker"]}
            ),
            "index": profile["basics"].get("index"),
        }
    ]
    entries += [
        {"isin": s["isin"], "name": s["name"], "tickers": []}
        for s in profile.get("similar_etfs", [])
    ]
    try:
        path = _learned_file()
        known = {e["isin"]: e for e in _read(path)}
        for e in entries:
            old = known.get(e["isin"], {})
            # do not let a name-only "similar" entry wipe known tickers
            e["tickers"] = sorted(set(old.get("tickers", [])) | set(e["tickers"]))
            known[e["isin"]] = {**old, **{k: v for k, v in e.items() if v}}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def search(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Registry entries matching a name, ticker or index; best matches first.

    Every meaningful query word must match a name/ticker/index word (prefixes
    allowed). If nothing matches fully, entries matching at least 60% of the
    words are returned with ``match: "partial"``.

    Args:
        query: Fund name, ticker or index words.
        limit: Maximum entries to return.

    Returns:
        Matching entries with ``isin``, ``name``, ``tickers``, ``index`` and
        ``match`` ("full" or "partial").
    """
    q = tokens(query)
    if not q:
        return []
    results = []
    for entry in load().values():
        name_tokens = tokens(entry.get("name", "") + " " + (entry.get("index") or ""))
        tickers = {t.lower() for t in entry.get("tickers", [])}
        hits = sum(
            1
            for w in q
            if w in tickers or any(n == w or n.startswith(w) for n in name_tokens)
        )
        if not hits:
            continue
        # Share of query words matched, plus a bonus for an exact ticker hit
        # so "IWDA" ranks the fund with that ticker above name matches.
        score = hits / len(q) + (1.0 if " ".join(q) in tickers else 0.0)
        results.append((score, entry))
    results.sort(key=lambda r: (-r[0], r[1].get("name", "")))
    full = [(s, e) for s, e in results if s >= 1]
    chosen, match = (
        (full, "full")
        if full
        else (
            [(s, e) for s, e in results if s >= 0.6],
            "partial",
        )
    )
    return [
        {
            "isin": e["isin"],
            "name": e.get("name"),
            "tickers": e.get("tickers", []),
            "index": e.get("index"),
            "match": match,
        }
        for _, e in chosen[:limit]
    ]


def by_ticker() -> dict[str, list[str]]:
    """Map each lower-case ticker to the ISINs that use it.

    Returns:
        ``{ticker: [isin, ...]}`` (a ticker can be reused across exchanges).
    """
    out: dict[str, list[str]] = {}
    for isin, e in load().items():
        for t in e.get("tickers", []):
            out.setdefault(t.lower(), []).append(isin)
    return out


def by_name() -> dict[str, str]:
    """Map each normalised fund name to its ISIN.

    Returns:
        ``{" ".join(tokens(name)): isin}``.
    """
    return {
        " ".join(tokens(e["name"])): isin for isin, e in load().items() if e.get("name")
    }
