"""Offline tests: synthetic HTML mirroring justETF's markup, made-up numbers."""

import pytest

from finance_mcp.justetf import analysis, parser
from finance_mcp.justetf.client import JustEtfError, normalize_isin

PAGE = """
<div data-testid="etf-profile-header_etf-name">Test World ETF (Acc)</div>
<span data-testid="etf-profile-header_isin-value">IE00B4L5Y983</span>
<span data-testid="etf-profile-header_identifier-value-ticker">TWLD</span>
<span data-testid="etf-profile-header_ter-value">0.20% p.a.</span>
<div data-testid="etf-profile-header_fund-size-value-wrapper"><span> EUR 1,500 </span> m</div>
<div data-testid="etf-profile-header_holdings-value">1,252</div>
<div data-testid="etf-profile-header_distribution-policy-value">Accumulating</div>
<div data-testid="tl_etf-basics_value_domicile-country">Ireland</div>
<table><tbody>
<tr data-testid="etf-holdings_countries_row">
 <td data-testid="tl_etf-holdings_countries_value_name">United States</td>
 <td><span data-testid="tl_etf-holdings_countries_value_percentage">70.00%</span></td></tr>
<tr data-testid="etf-holdings_countries_row">
 <td data-testid="tl_etf-holdings_countries_value_name">Other</td>
 <td><span data-testid="tl_etf-holdings_countries_value_percentage">30.00%</span></td></tr>
</tbody></table>
<table><tbody><tr data-testid="etf-holdings_top-holdings_row">
 <td><a data-testid="tl_etf-holdings_top-holdings_link_name" href="/en/stock-profiles/US0378331005"><span>Apple</span></a></td>
 <td><span data-testid="tl_etf-holdings_top-holdings_value_percentage">5.00%</span></td></tr></tbody></table>
<div data-testid="tl_etf-holdings_reference-date">As of 31/08/2026</div>
"""

AJAX = """<ajax-response><component id="t"><![CDATA[<table>
<tr data-testid="etf-holdings_countries_row"><td data-testid="tl_etf-holdings_countries_value_name">United States</td>
<td><span data-testid="tl_etf-holdings_countries_value_percentage">70.00%</span></td></tr>
<tr data-testid="etf-holdings_countries_row"><td data-testid="tl_etf-holdings_countries_value_name">Japan</td>
<td><span data-testid="tl_etf-holdings_countries_value_percentage">10.00%</span></td></tr>
<tr data-testid="etf-holdings_countries_row"><td data-testid="tl_etf-holdings_countries_value_name">Other</td>
<td><span data-testid="tl_etf-holdings_countries_value_percentage">20.00%</span></td></tr>
</table>]]></component></ajax-response>"""


def make(isin, ter, size, countries, sectors, top, **extra):
    return {
        "isin": isin,
        "name": isin,
        "ter_pct": ter,
        "fund_size": {"currency": "EUR", "amount_mn": size},
        "distribution_policy": "Accumulating",
        "replication": "Physical",
        "basics": {
            "domicile_country": "Ireland",
            "fund_currency": "USD",
            "currency_risk": "unhedged",
            "fund_provider": "X",
            "index": "I",
        },
        "holdings": {
            "countries": [{"name": n, "weight_pct": w} for n, w in countries],
            "sectors": [{"name": n, "weight_pct": w} for n, w in sectors],
            "top_10": [{"name": n, "isin": n, "weight_pct": w} for n, w in top],
            "top_10_weight_pct": sum(w for _, w in top),
            "as_of": "31/08/2026",
        },
        **extra,
    }


def test_parse_profile_basic():
    p = parser.parse_profile(PAGE)
    assert p["isin"] == "IE00B4L5Y983" and p["ticker"] == "TWLD"
    assert p["ter_pct"] == 0.2
    assert p["fund_size"] == {"currency": "EUR", "amount_mn": 1500.0}
    assert p["number_of_holdings"] == 1252
    assert p["holdings"]["top_10"][0]["isin"] == "US0378331005"
    assert p["holdings"]["as_of"] == "31/08/2026"
    assert any("full countries" in w for w in p["warnings"])


def test_parse_profile_uses_full_lists_from_ajax():
    p = parser.parse_profile(PAGE, {"countries": AJAX})
    assert [c["name"] for c in p["holdings"]["countries"]] == [
        "United States",
        "Japan",
        "Other",
    ]
    assert not any("countries" in w for w in p["warnings"])


def test_parse_rejects_other_pages():
    with pytest.raises(ValueError):
        parser.parse_profile("<html>nope</html>")


def test_to_number():
    assert parser.to_number("+16.97%") == 16.97
    assert parser.to_number("-6.47%") == -6.47
    assert parser.to_number("1,252") == 1252
    assert parser.to_number("-") is None


def test_isin_validation():
    assert normalize_isin(" ie00b4l5y983 ") == "IE00B4L5Y983"
    for bad in ["", "IE00B4L5Y98", "IE00B4L5Y984", "../etc/passwd"]:
        with pytest.raises(JustEtfError):
            normalize_isin(bad)


def test_weights():
    assert analysis.compute_weights([None, None]) == [0.5, 0.5]
    assert analysis.compute_weights([300, 100]) == [0.75, 0.25]
    with pytest.raises(ValueError):
        analysis.compute_weights([100, None])
    with pytest.raises(ValueError):
        analysis.compute_weights([100, -1])


def test_portfolio_analysis():
    a = make(
        "A",
        0.2,
        1000,
        [("United States", 70), ("Japan", 10), ("Other", 20)],
        [("Technology", 30), ("Other", 70)],
        [("Apple", 5), ("Nvidia", 4)],
    )
    b = make(
        "B",
        0.4,
        50,
        [("United States", 50), ("Other", 50)],
        [("Technology", 50), ("Other", 50)],
        [("Apple", 3)],
    )
    r = analysis.analyze_portfolio([a, b], [7500, 2500])
    cost = r["cost_and_size"]
    assert cost["weighted_ter_pct"] == 0.25
    assert cost["total_annual_cost"] == 25.0
    assert cost["positions"][1]["flags"]  # B is a small fund
    us = r["country_exposure"]["buckets"][0]
    assert us["name"] == "United States" and us["pct_of_portfolio"] == 65.0
    assert us["by_etf"][0]["isin"] == "A"
    assert r["country_exposure"]["other_pct"] == 27.5
    tech = r["sector_exposure"]["buckets"][0]
    assert tech["pct_of_portfolio"] == 35.0
    apple = r["stock_look_through"]["top_stocks"][0]
    assert apple["name"] == "Apple" and apple["number_of_etfs"] == 2
    assert apple["pct_of_portfolio"] == 4.5


def test_focus_filter():
    a = make(
        "A",
        0.2,
        1000,
        [("United States", 70), ("Japan", 10), ("Other", 20)],
        [("Technology", 30), ("Other", 70)],
        [],
    )
    r = analysis.analyze_portfolio([a], [None], focus_countries=["jap"])
    assert [b["name"] for b in r["country_exposure"]["buckets"]] == ["Japan"]


# ----------------------------------------------------------------- search
@pytest.fixture
def registry_env(tmp_path, monkeypatch):
    from finance_mcp.justetf import client, registry

    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    return registry


def test_registry_search_by_name_ticker_and_class(registry_env):
    r = registry_env
    assert r.search("iShares Core MSCI World")[0]["isin"] == "IE00B4L5Y983"
    assert r.search("sxr8")[0]["isin"] == "IE00B5BMR087"
    names = [m["name"] for m in r.search("s&p 500 distributing")]
    assert names and all("Dist" in n for n in names)
    assert r.search("zzzz nothing") == []


def test_registry_learns_profiles(registry_env):
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


def test_search_isin_passthrough_and_empty():
    from finance_mcp.justetf import search

    assert search.search_etf("ie00b4l5y983")["matches"][0]["match"] == "isin"
    assert "error" in search.search_etf("  ")


def test_search_maps_yahoo_listings_to_isin(registry_env, monkeypatch):
    from finance_mcp.justetf import search

    quotes = [
        {
            "symbol": "IWDA.AS",
            "quoteType": "ETF",
            "longname": "x",
            "exchDisp": "Amsterdam",
        },
        {"symbol": "EUNL.DE", "quoteType": "ETF", "longname": "x", "exchDisp": "XETRA"},
        {
            "symbol": "ZZZ.L",
            "quoteType": "ETF",
            "longname": "Unknown Fund",
            "exchDisp": "London",
        },
    ]
    monkeypatch.setattr(search, "_yahoo_candidates", lambda q, n: quotes)
    out = search.search_etf("something obscure")
    resolved = [m for m in out["matches"] if m["match"] == "yahoo"]
    assert (
        resolved[0]["isin"] == "IE00B4L5Y983"
        and len(resolved[0]["yahoo_listings"]) == 2
    )
    assert out["unresolved_candidates"][0]["isin"] is None
