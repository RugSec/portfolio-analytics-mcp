"""Fixtures that replace the network (Yahoo, justETF) with offline fakes."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest
import yfinance as yf

from finance_mcp.yahoo import data
from tests.fakes import CURRENCIES, DATES, FX, PRICES, FakeTicker


@pytest.fixture
def fake_yahoo(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Serve prices, currencies, FX and time zones from ``fakes`` instead of Yahoo.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The symbol lists passed to each price download, for call assertions.
    """
    calls: list[list[str]] = []

    def download_close(
        symbols: list[str], start: str | None, end: str | None, interval: str
    ) -> pd.DataFrame:
        """Return the synthetic closes for the known symbols.

        Args:
            symbols: Requested symbols.
            start: First date (inclusive).
            end: Ignored.
            interval: "1d" or "1wk".

        Returns:
            One column per known symbol.
        """
        calls.append(list(symbols))
        cols = {s: PRICES[s] for s in symbols if s in PRICES}
        if not cols:
            return pd.DataFrame()
        df = pd.DataFrame(cols, index=DATES)
        if interval == "1wk":
            df = df.resample("W-MON").last()
        return df.loc[pd.Timestamp(start) :]

    def download_fx(
        currencies: set[str], base: str, start: str | None, end: str | None
    ) -> pd.DataFrame:
        """Return constant FX rates for every needed currency.

        Args:
            currencies: ISO currencies to convert from.
            base: Target currency.
            start: Ignored.
            end: Ignored.

        Returns:
            One constant column per currency other than ``base``.
        """
        need = sorted(c for c in currencies if c != base)
        return pd.DataFrame({c: FX[c] for c in need}, index=DATES)

    monkeypatch.setattr(data, "download_close", download_close)
    monkeypatch.setattr(data, "download_fx", download_fx)
    monkeypatch.setattr(
        data, "get_currencies", lambda syms: {s: CURRENCIES.get(s) for s in syms}
    )
    zones = {"AAPL": "America/New_York", "SPY": "America/New_York"}
    monkeypatch.setattr(
        data,
        "get_timezones",
        lambda syms: {s: zones.get(s, "Europe/Berlin") for s in syms},
    )
    monkeypatch.setattr(data, "yahoo_reachable", lambda: True)
    return calls


@pytest.fixture
def registry_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """Point the justETF cache and learned registry at a temporary directory.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The ``registry`` module, ready to use.
    """
    from finance_mcp.justetf import client, registry

    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    return registry


@pytest.fixture
def fake_yf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace ``yf.Ticker``, the reachability probe and the metadata cache.

    Args:
        monkeypatch: Pytest monkeypatch fixture.
    """
    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    monkeypatch.setattr(data, "yahoo_reachable", lambda: True)
    monkeypatch.setattr(data, "_meta_cache", {})
