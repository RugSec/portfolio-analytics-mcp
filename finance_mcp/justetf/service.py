"""Fetch + parse + cache: the one place the tools get ETF data from."""

from __future__ import annotations

from datetime import UTC, datetime

from . import client, parser, registry
from .client import JustEtfError, normalize_isin

MAX_ETFS_PER_CALL = 15


def get_profile(isin: str, refresh: bool = False) -> dict:
    """Return the parsed profile for one ISIN (cached for the configured TTL).

    Args:
        isin: ETF ISIN, e.g. IE00B4L5Y983.
        refresh: Ignore the cache and download the page again.

    Raises:
        JustEtfError: invalid ISIN, unknown ETF, blocked or unreachable site.
    """
    isin = normalize_isin(isin)
    if not refresh and (cached := client.cache_get(isin)) is not None:
        cached["from_cache"] = True
        return cached
    html, fragments = client.fetch_profile_pages(isin)
    try:
        profile = parser.parse_profile(html, fragments)
    except ValueError as exc:
        raise JustEtfError(f"{isin}: {exc}") from exc
    profile["fetched_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    profile["from_cache"] = False
    client.cache_put(isin, {**profile, "from_cache": True})
    registry.learn(profile)
    return profile


def get_profiles(
    isins: list[str], refresh: bool = False
) -> tuple[dict[str, dict], dict[str, str]]:
    """Load several ETFs; failures are collected instead of aborting the batch.

    Returns:
        ``(profiles_by_isin, errors_by_input)``.
    """
    cleaned: list[str] = []
    errors: dict[str, str] = {}
    for raw in isins:
        try:
            isin = normalize_isin(raw)
        except JustEtfError as exc:
            errors[raw] = str(exc)
            continue
        if isin not in cleaned:
            cleaned.append(isin)
    if len(cleaned) > MAX_ETFS_PER_CALL:
        extra = cleaned[MAX_ETFS_PER_CALL:]
        cleaned = cleaned[:MAX_ETFS_PER_CALL]
        for isin in extra:
            errors[isin] = f"skipped: at most {MAX_ETFS_PER_CALL} ETFs per call"
    profiles: dict[str, dict] = {}
    for isin in cleaned:
        try:
            profiles[isin] = get_profile(isin, refresh=refresh)
        except JustEtfError as exc:
            errors[isin] = str(exc)
    return profiles, errors
