"""Turn a justETF ETF profile page into a plain dict.

The page exposes stable ``data-testid`` attributes, which we rely on instead of
CSS classes. Anything missing becomes ``None`` so a layout change degrades
one field instead of breaking the whole profile.
"""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup, Tag

_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")


# ------------------------------------------------------------------ helpers
def _text(node: Tag | None) -> str | None:
    """Get the whitespace-normalised text of a node.

    Args:
        node: A parsed tag, or None.

    Returns:
        The text, or None if the node is missing, empty or just "-".
    """
    if node is None:
        return None
    value = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
    return value if value and value != "-" else None


def _tid(root: Tag | BeautifulSoup, testid: str) -> Tag | None:
    """Find the first element with a given ``data-testid``.

    Args:
        root: Where to search.
        testid: The ``data-testid`` value.

    Returns:
        The element, or None.
    """
    return root.select_one(f'[data-testid="{testid}"]')


def _tid_text(root: Tag | BeautifulSoup, testid: str) -> str | None:
    """Get the text of the first element with a given ``data-testid``.

    Args:
        root: Where to search.
        testid: The ``data-testid`` value.

    Returns:
        The normalised text, or None.
    """
    return _text(_tid(root, testid))


def to_number(value: str | None) -> float | None:
    """Parse '+16.97%', '1,252', '0.20% p.a.' or '1.71' to a float.

    Args:
        value: Text containing one number, or None.

    Returns:
        The first number in the text, or None if there is none.
    """
    if not value:
        return None
    match = _NUM_RE.search(value.replace("−", "-"))  # Unicode minus -> ASCII
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _slug(label: str) -> str:
    """Turn a label into a snake_case key ("Fund Structure" -> "fund_structure").

    Args:
        label: Human-readable label.

    Returns:
        The key.
    """
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")


def parse_fund_size(value: str | None) -> dict[str, Any] | None:
    """Parse a fund size like 'EUR 132,896 m' into currency and millions.

    Args:
        value: Fund size text with a currency, amount and m/bn/k unit.

    Returns:
        ``{"currency", "amount_mn"}``, or None if it cannot be parsed.
    """
    if not value:
        return None
    match = re.search(r"([A-Z]{3})\s*([\d,.]+)\s*(m|bn|k)?", value)
    if not match:
        return None
    amount = float(match.group(2).replace(",", ""))
    factor = {"bn": 1000.0, "k": 0.001}.get(match.group(3) or "m", 1.0)
    return {"currency": match.group(1), "amount_mn": amount * factor}


def _kv_rows(panel: Tag | None) -> dict[str, str | None]:
    """Read label/value pairs from a two-column table (td.vallabel + next td).

    Args:
        panel: The element containing the table, or None.

    Returns:
        ``{slug(label): value}``; empty if the panel is missing.
    """
    out: dict[str, str | None] = {}
    if panel is None:
        return out
    for row in panel.select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) >= 2 and "vallabel" in (cells[0].get("class") or []):
            out[_slug(_text(cells[0]) or "")] = _text(cells[1])
    return out


def _weight_rows(root: Tag | BeautifulSoup, group: str) -> list[dict[str, Any]]:
    """Read name/percentage rows for 'countries' or 'sectors'.

    Args:
        root: Page or fragment to search.
        group: ``"countries"`` or ``"sectors"``.

    Returns:
        ``[{"name", "weight_pct"}, ...]`` in page order.
    """
    rows = []
    for row in root.select(f'[data-testid="etf-holdings_{group}_row"]'):
        name = _tid_text(row, f"tl_etf-holdings_{group}_value_name")
        pct = to_number(_tid_text(row, f"tl_etf-holdings_{group}_value_percentage"))
        if name and pct is not None:
            rows.append({"name": name, "weight_pct": pct})
    return rows


def _ajax_html(xml: str) -> BeautifulSoup:
    """Concatenate the CDATA payloads of a Wicket ajax-response.

    Args:
        xml: The raw ``<ajax-response>`` text.

    Returns:
        The embedded HTML, parsed.
    """
    parts = re.findall(r"<!\[CDATA\[(.*?)\]\]>", xml, re.S)
    return BeautifulSoup("".join(parts), "html.parser")


# ------------------------------------------------------------------ sections
def _parse_basics(soup: BeautifulSoup) -> dict[str, Any]:
    """Read the "Basics" table (index, replication, currency, domicile...).

    Args:
        soup: The profile page.

    Returns:
        One entry per basics field, None when missing.
    """

    def g(key: str) -> str | None:
        """Get one basics value by its key.

        Args:
            key: Suffix of the ``tl_etf-basics_value_`` test id.

        Returns:
            The value text, or None.
        """
        return _tid_text(soup, f"tl_etf-basics_value_{key}")

    return {
        "index": g("index-name"),
        "investment_focus": g("investment-focus"),
        "replication": g("replication"),
        "replication_method": g("replication-method"),
        "strategy_risk": g("strategy-risk"),
        "sustainable": g("sustainable"),
        "fund_currency": g("fund-currency"),
        "currency_risk": g("currency-hedge"),
        "volatility_1y_pct": to_number(g("volatility")),
        "launch_date": g("launch-date"),
        "distribution_policy": g("distribution-policy"),
        "distribution_interval": g("distribution-interval"),
        "domicile_country": g("domicile-country"),
        "fund_provider": g("fund-provider"),
    }


def _parse_panels(soup: BeautifulSoup) -> dict[str, Any]:
    """Read the collapsible legal, replication and tax panels.

    Args:
        soup: The profile page.

    Returns:
        ``legal_structure``, ``replication_details`` and ``tax_status`` dicts.
    """
    legal = _kv_rows(soup.select_one("#collapse-legal"))
    replication = _kv_rows(soup.select_one("#collapse-replication"))
    tax: dict[str, str | None] = {}
    panel = soup.select_one("#collapse-tax")
    if panel:
        for row in panel.select("tr"):
            # Country / status rows; skip empty cells (icons, spacers).
            cells = [_text(c) for c in row.find_all("td", recursive=False)]
            cells = [c for c in cells if c]
            if len(cells) >= 2:
                tax[cells[0]] = cells[1]
    return {
        "legal_structure": legal,
        "replication_details": replication,
        "tax_status": tax,
    }


def _parse_returns(soup: BeautifulSoup) -> dict[str, Any]:
    """Read period and calendar-year returns and the currency they are in.

    Args:
        soup: The profile page.

    Returns:
        ``currency``, ``period_returns_pct`` and ``calendar_year_returns_pct``.
    """
    periods = {
        "ytd": "ytd-return",
        "1m": "month-return",
        "3m": "3month-return",
        "6m": "6month-return",
        "1y": "1year-return",
        "3y": "3year-return",
        "5y": "5year-return",
        "since_inception": "max-return",
    }
    cumulative = {
        key: to_number(_tid_text(soup, f"etf-returns-section_{tid}"))
        for key, tid in periods.items()
    }
    calendar: dict[str, float | None] = {}
    # Calendar years are numbered columns 1..n; stop at the first missing one.
    for i in range(1, 12):
        year = _tid_text(soup, f"etf-returns-section_year-title-{i}")
        if not year:
            break
        calendar[year] = to_number(
            _tid_text(soup, f"etf-returns-section_year-return-{i}")
        )
    selected = soup.select_one(
        '[data-testid="etf-returns-section_currencies-select"] option[selected]'
    )
    return {
        "currency": _text(selected),
        "period_returns_pct": cumulative,
        "calendar_year_returns_pct": calendar,
    }


def _parse_risk(soup: BeautifulSoup) -> dict[str, float | None]:
    """Read the risk table (volatility, max drawdown, return per risk).

    Args:
        soup: The profile page.

    Returns:
        ``{slug(label): number}``.
    """
    raw = _kv_rows(_tid(soup, "etf-risk_table_panel"))
    return {key: to_number(value) for key, value in raw.items()}


def _parse_listings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Read the stock exchange listings table.

    Args:
        soup: The profile page.

    Returns:
        One dict per listing: MIC code, exchange, currency, ticker, codes.
    """
    listings = []
    pattern = re.compile(r"^etf-trade-data-panel_row-([a-z0-9]+)$")
    for row in soup.select('[data-testid^="etf-trade-data-panel_row-"]'):
        match = pattern.match(str(row.get("data-testid", "")))
        if not match:  # cells share the row prefix (e.g. ..._row-xetr_ticker)
            continue
        code = match.group(1)
        prefix = f"etf-trade-data-panel_row-{code}_"

        # Default arguments bind this row/prefix (not the loop's last values).
        def g(suffix: str, row: Tag = row, prefix: str = prefix) -> str | None:
            """Get one cell of this listing row.

            Args:
                suffix: Cell name, e.g. "ticker".
                row: The listing row.
                prefix: Test id prefix of the row.

            Returns:
                The cell text, or None.
            """
            return _tid_text(row, prefix + suffix)

        listings.append(
            {
                "mic_code": code.upper(),
                "exchange": g("listing"),
                "trading_currency": g("trade-currency"),
                "ticker": g("ticker"),
                "bloomberg": g("bloomberg"),
                "reuters": g("reuters"),
            }
        )
    return listings


def _parse_similar(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Read the "further ETFs on the same index" table.

    Args:
        soup: The profile page.

    Returns:
        One dict per ETF: ISIN, name, fund size, TER, policy, replication.
    """
    similar = []
    for row in soup.select('[data-testid^="etf-further-info-en_related-etf-row-"]'):
        isin = str(row["data-testid"]).rsplit("-", 1)[-1]  # ...-row-<ISIN>
        cells = [_text(c) for c in row.find_all("td", recursive=False)]
        if len(cells) < 5:
            continue
        similar.append(
            {
                "isin": isin,
                "name": cells[0],
                "fund_size_mn": to_number(cells[1]),
                "ter_pct": to_number(cells[2]),
                "distribution_policy": cells[3],
                "replication": cells[4],
            }
        )
    return similar


def _parse_top_holdings(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Read the top-10 holdings table.

    Args:
        soup: The profile page.

    Returns:
        One dict per holding: name, ISIN (from the link) and weight.
    """
    holdings = []
    for row in soup.select('[data-testid="etf-holdings_top-holdings_row"]'):
        link = _tid(row, "tl_etf-holdings_top-holdings_link_name")
        weight = to_number(
            _tid_text(row, "tl_etf-holdings_top-holdings_value_percentage")
        )
        if link is None or weight is None:
            continue
        href = str(link.get("href", ""))  # /en/stock-profiles/<ISIN>
        holdings.append(
            {
                "name": _text(link),
                "isin": href.rstrip("/").rsplit("/", 1)[-1] or None,
                "weight_pct": weight,
            }
        )
    return holdings


# ------------------------------------------------------------------ public
def parse_profile(html: str, fragments: dict[str, str] | None = None) -> dict[str, Any]:
    """Parse a profile page (plus optional 'Show more' fragments) into a dict.

    Args:
        html: The ETF profile page HTML.
        fragments: Optional Wicket ajax responses keyed by ``countries`` and
            ``sectors`` that contain the full (not shortened) lists.

    Returns:
        The structured profile. ``warnings`` lists anything that could not be
        parsed or loaded.

    Raises:
        ValueError: if the page does not look like an ETF profile.
    """
    soup = BeautifulSoup(html, "html.parser")
    isin = _tid_text(soup, "etf-profile-header_isin-value")
    name = _tid_text(soup, "etf-profile-header_etf-name")
    if not isin or not name:
        raise ValueError("page does not look like a justETF ETF profile")

    warnings: list[str] = []
    fragments = fragments or {}
    countries = _weight_rows(soup, "countries")
    sectors = _weight_rows(soup, "sectors")
    # The page shows ~5 rows per list; the "Show more" fragment has the full
    # list. Use it unless it came back shorter (a broken fragment).
    for key, current in (("countries", countries), ("sectors", sectors)):
        if key in fragments:
            full = _weight_rows(_ajax_html(fragments[key]), key)
            if len(full) >= len(current):
                if key == "countries":
                    countries = full
                else:
                    sectors = full
                continue
        warnings.append(f"full {key} list not loaded; showing the shortened list")

    fund_size = parse_fund_size(
        _tid_text(soup, "etf-profile-header_fund-size-value-wrapper")
    )
    count_text = _tid_text(soup, "tl_etf-holdings_top-holdings_count")
    total_holdings = to_number(
        _tid_text(soup, "etf-profile-header_holdings-value")
    ) or to_number(count_text)

    profile: dict[str, Any] = {
        "isin": isin,
        "name": name,
        "ticker": _tid_text(soup, "etf-profile-header_identifier-value-ticker"),
        "url": f"https://www.justetf.com/en/etf-profile.html?isin={isin}",
        "ter_pct": to_number(_tid_text(soup, "etf-profile-header_ter-value")),
        "fund_size": fund_size,
        "distribution_policy": _tid_text(
            soup, "etf-profile-header_distribution-policy-value"
        ),
        "replication": _tid_text(soup, "etf-profile-header_replication-value"),
        "inception_date": _tid_text(soup, "etf-profile-header_inception-date-value"),
        "number_of_holdings": int(total_holdings) if total_holdings else None,
        "description": _tid_text(soup, "etf-quote-section_description-label"),
        "basics": _parse_basics(soup),
        **_parse_panels(soup),
        "holdings": {
            "top_10": _parse_top_holdings(soup),
            "top_10_weight_pct": to_number(
                _tid_text(soup, "tl_etf-holdings_top-holdings_weight")
            ),
            "countries": countries,
            "sectors": sectors,
            "as_of": (_tid_text(soup, "tl_etf-holdings_reference-date") or "")
            .removeprefix("As of")
            .strip()
            or None,
        },
        "performance": _parse_returns(soup),
        "risk": _parse_risk(soup),
        "listings": _parse_listings(soup),
        "similar_etfs": _parse_similar(soup),
        "warnings": warnings,
    }
    if profile["ter_pct"] is None:
        warnings.append("TER not found on the page")
    if fund_size is None:
        warnings.append("fund size not found on the page")
    return profile
