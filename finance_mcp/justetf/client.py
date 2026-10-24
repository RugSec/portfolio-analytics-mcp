"""Polite HTTP access to justETF: honest User-Agent, rate limit, disk cache.

Only intended for personal, on-demand lookups (see docs/JUSTETF_PLAN.md).
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per request

BASE_URL = "https://www.justetf.com"
PROFILE_PATH = "/en/etf-profile.html"
USER_AGENT = "portfolio-analytics-mcp/0.1 (personal on-demand lookups; not a crawler)"

MIN_INTERVAL_S = float(os.environ.get("JUSTETF_MIN_INTERVAL_S", "1.5"))
CACHE_TTL_S = float(os.environ.get("JUSTETF_CACHE_TTL_HOURS", "24")) * 3600
CACHE_DIR = Path(
    os.environ.get(
        "JUSTETF_CACHE_DIR",
        Path.home() / ".cache" / "portfolio-analytics-mcp" / "justetf",
    )
)

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
_lock = threading.Lock()
_last_request = 0.0


class JustEtfError(Exception):
    """Raised for any expected failure (bad ISIN, not found, blocked, network)."""


def normalize_isin(isin: str) -> str:
    """Return the upper-case ISIN, or raise JustEtfError if it is not valid.

    Validates the format and the check digit, so only real ISINs ever reach
    the site (and no arbitrary text ends up in a URL).
    """
    value = (isin or "").strip().upper()
    if not _ISIN_RE.match(value):
        raise JustEtfError(f"'{isin}' is not a valid ISIN (expected e.g. IE00B4L5Y983)")
    digits = "".join(str(int(c, 36)) for c in value)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    if total % 10 != 0:
        raise JustEtfError(f"'{isin}' has an invalid ISIN check digit")
    return value


def _throttle() -> None:
    """Block until at least MIN_INTERVAL_S has passed since the last request."""
    global _last_request
    with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()


def _get(client: httpx.Client, url: str, **kwargs: Any) -> httpx.Response:
    """GET with throttling and a couple of retries on transient errors."""
    last_exc: Exception | None = None
    for attempt in range(3):
        _throttle()
        try:
            resp = client.get(url, **kwargs)
        except httpx.HTTPError as exc:
            last_exc = exc
            time.sleep(2**attempt)
            continue
        if resp.status_code in (403, 429):
            # Do not retry or work around: respect being blocked / rate limited.
            raise JustEtfError(
                f"justETF refused the request (HTTP {resp.status_code}). "
                "Wait a while before trying again."
            )
        if resp.status_code >= 500:
            last_exc = JustEtfError(f"justETF server error (HTTP {resp.status_code})")
            time.sleep(2**attempt)
            continue
        return resp
    raise JustEtfError(f"Could not reach justETF: {last_exc}")


def fetch_profile_pages(isin: str) -> tuple[str, dict[str, str]]:
    """Download the profile page and the "Show more" fragments for one ISIN.

    Returns:
        The profile HTML and a dict ``{"countries": xml, "sectors": xml}`` with
        the AJAX responses (a missing key means that fragment could not be
        loaded, and the page only shows the shortened list).

    Raises:
        JustEtfError: if the ISIN is unknown or the site cannot be reached.
    """
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
    with httpx.Client(
        base_url=BASE_URL, headers=headers, timeout=20, follow_redirects=True
    ) as client:
        resp = _get(client, PROFILE_PATH, params={"isin": isin})
        if resp.status_code == 404:
            raise JustEtfError(f"ISIN {isin} was not found on justETF")
        if resp.status_code != 200:
            raise JustEtfError(f"Unexpected response from justETF: {resp.status_code}")
        html = resp.text

        fragments: dict[str, str] = {}
        for key, name in (
            ("countries", "loadMoreCountries"),
            ("sectors", "loadMoreSectors"),
        ):
            match = re.search(
                r'"u":"(/en/etf-profile\.html\?[^"]*-' + name + r'&[^"]*)"', html
            )
            if not match:
                continue
            try:
                ajax = _get(
                    client,
                    match.group(1).replace("\\/", "/"),
                    headers={
                        "Wicket-Ajax": "true",
                        "Wicket-Ajax-BaseURL": f"en/etf-profile.html?isin={isin}",
                    },
                )
            except JustEtfError:
                continue
            if ajax.status_code == 200:
                fragments[key] = ajax.text
        return html, fragments


# ------------------------------------------------------------------ cache
def cache_get(isin: str) -> dict | None:
    """Return the cached parsed profile if it is younger than the TTL."""
    path = CACHE_DIR / f"{isin}.json"
    try:
        if time.time() - path.stat().st_mtime > CACHE_TTL_S:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_put(isin: str, profile: dict) -> None:
    """Store a parsed profile; cache problems never break a lookup."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{isin}.json").write_text(
            json.dumps(profile, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass
