"""Fetch + parse + cache service for justETF profiles."""

from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from finance_mcp.justetf import client, service
from finance_mcp.justetf.client import JustEtfError
from tests.fakes import FULL_PAGE, ISIN

REGISTRY_ISINS = [
    e["isin"]
    for e in json.loads(
        (Path(client.__file__).parent / "data" / "etfs.json").read_text()
    )
]


def test_get_profile_fetches_parses_caches_and_learns(
    registry_env: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh profile is downloaded once, then served from the cache."""
    fetched: list[str] = []

    def fetch(isin: str) -> tuple[str, dict[str, str]]:
        """Return the synthetic page.

        Args:
            isin: Requested ISIN.

        Returns:
            Page HTML and no fragments.
        """
        fetched.append(isin)
        return FULL_PAGE, {}

    monkeypatch.setattr(client, "fetch_profile_pages", fetch)
    first = service.get_profile(ISIN.lower())
    assert first["from_cache"] is False and "fetched_at" in first
    second = service.get_profile(ISIN)
    assert second["from_cache"] is True and fetched == [ISIN]
    service.get_profile(ISIN, refresh=True)
    assert fetched == [ISIN, ISIN]
    assert registry_env.load()[ISIN]["name"] == "Test World ETF (Acc)"


def test_get_profile_wraps_parse_errors(
    registry_env: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page that is not an ETF profile becomes a JustEtfError."""
    monkeypatch.setattr(client, "fetch_profile_pages", lambda i: ("<html/>", {}))
    with pytest.raises(JustEtfError, match=ISIN):
        service.get_profile(ISIN)


def test_get_profiles_collects_errors_and_caps_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad ISINs, failures and anything past the limit go into ``errors``."""

    def get_profile(isin: str, refresh: bool = False) -> dict[str, Any]:
        """Fail for one ISIN, succeed for the others.

        Args:
            isin: Requested ISIN.
            refresh: Ignored.

        Returns:
            A tiny profile.

        Raises:
            JustEtfError: For the first registry ISIN.
        """
        if isin == REGISTRY_ISINS[0]:
            raise JustEtfError("boom")
        return {"isin": isin}

    monkeypatch.setattr(service, "get_profile", get_profile)
    isins = ["nope", *REGISTRY_ISINS[:17], REGISTRY_ISINS[1]]  # last is a duplicate
    profiles, errors = service.get_profiles(isins)
    assert len(profiles) == service.MAX_ETFS_PER_CALL - 1
    assert errors[REGISTRY_ISINS[0]] == "boom"
    assert "not a valid ISIN" in errors["nope"]
    skipped = [k for k, v in errors.items() if v.startswith("skipped")]
    assert skipped == REGISTRY_ISINS[15:17]
