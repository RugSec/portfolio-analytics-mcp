"""Local ETF registry: seed list and learned profiles."""

from __future__ import annotations

from types import ModuleType

from tests.fakes import make


def test_registry_search_by_name_ticker_and_class(registry_env: ModuleType) -> None:
    """The seed registry finds ETFs by name, ticker and share class."""
    r = registry_env
    assert r.search("iShares Core MSCI World")[0]["isin"] == "IE00B4L5Y983"
    assert r.search("sxr8")[0]["isin"] == "IE00B5BMR087"
    names = [m["name"] for m in r.search("s&p 500 distributing")]
    assert names and all("Dist" in n for n in names)
    assert r.search("zzzz nothing") == []


def test_registry_learns_profiles(registry_env: ModuleType) -> None:
    """A fetched profile becomes searchable by its listing tickers."""
    r = registry_env
    profile = make("IE00B3XXRP09", 0.07, 5000, [], [], [])
    profile.update(
        name="Brand New Fund",
        listings=[{"ticker": "NEWF"}],
        similar_etfs=[{"isin": "IE00BFMXXD54", "name": "Other Fund"}],
    )
    profile["basics"]["index"] = "Some Index"
    r.learn(profile)
    assert r.search("NEWF")[0]["name"] == "Brand New Fund"
