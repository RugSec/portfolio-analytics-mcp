"""yfinance wrapper: downloads, metadata, FX, errors (yfinance faked)."""

from __future__ import annotations

from typing import Any

import httpx
import numpy as np
import pandas as pd
import pytest

from finance_mcp.yahoo import data
from finance_mcp.yahoo.data import YahooError


def test_yahoo_error_to_dict() -> None:
    """YahooError serialises with and without a hint."""
    assert YahooError("no_data", "nothing").to_dict() == {
        "error": "nothing",
        "error_code": "no_data",
    }
    assert YahooError("no_data", "x", "try y").to_dict()["hint"] == "try y"


def test_download_close_parses_yfinance_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real wrapper, with yf.download faked in its multi-index shape."""
    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06"], tz="Europe/Amsterdam")
    cols = pd.MultiIndex.from_product([["Close", "Volume"], ["AAPL", "DEAD"]])
    frame = pd.DataFrame(
        [[1.0, np.nan, 10, np.nan], [2.0, np.nan, 20, np.nan]], index=idx, columns=cols
    )
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: frame)
    out = data.download_close(["AAPL", "DEAD"], "2026-01-01", None, "1d")
    assert list(out.columns) == ["AAPL"]  # all-NaN column dropped
    assert out.index.tz is None and out["AAPL"].tolist() == [1.0, 2.0]
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: pd.DataFrame())
    assert data.download_close(["X"], None, None, "1d").empty
    with pytest.raises(YahooError):
        data.download_close(["X"], None, None, "5m")


def test_clean_symbols() -> None:
    """Symbols are stripped, upper-cased and de-duplicated; strings are split."""
    assert data.clean_symbols("aapl, msft; AAPL ,") == ["AAPL", "MSFT"]
    assert data.clean_symbols(["spy", " ", "Spy"]) == ["SPY"]


def test_yahoo_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any HTTP answer counts as reachable; transport errors do not."""
    monkeypatch.setattr(data.httpx, "get", lambda *a, **k: httpx.Response(404))
    assert data.yahoo_reachable() is True

    def down(*args: Any, **kwargs: Any) -> httpx.Response:
        """Fail like a network outage.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            httpx.ConnectError: Always.
        """
        raise httpx.ConnectError("down")

    monkeypatch.setattr(data.httpx, "get", down)
    assert data.yahoo_reachable() is False


def test_download_close_errors_and_single_series(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Library errors become upstream_unavailable; a flat frame still works."""

    def boom(*args: Any, **kwargs: Any) -> pd.DataFrame:
        """Fail like yfinance does.

        Args:
            *args: Ignored.
            **kwargs: Ignored.

        Raises:
            RuntimeError: Always.
        """
        raise RuntimeError("rate limited")

    monkeypatch.setattr(data.yf, "download", boom)
    with pytest.raises(YahooError) as exc:
        data.download_close(["AAPL"], None, None, "1d")
    assert exc.value.code == "upstream_unavailable"
    with pytest.raises(YahooError):
        data.download_close([], None, None, "1d")

    # one ticker can come back with flat columns, so df["Close"] is a Series
    idx = pd.DatetimeIndex(["2026-01-05", "2026-01-06"])
    flat = pd.DataFrame({"Close": [1.0, 2.0], "Volume": [10, 20]}, index=idx)
    monkeypatch.setattr(data.yf, "download", lambda *a, **k: flat)
    out = data.download_close(["AAPL"], None, None, "1d")
    assert out["AAPL"].tolist() == [1.0, 2.0]


def test_metadata_lookup_and_cache(fake_yf: None) -> None:
    """Currencies and time zones are fetched once per known symbol."""
    assert data.get_currencies(["AAPL", "VUSA.L", "NOPE"]) == {
        "AAPL": "USD", "VUSA.L": "GBp", "NOPE": None,
    }  # fmt: skip
    assert data.get_timezones(["AAPL"]) == {"AAPL": "America/New_York"}
    assert set(data._meta_cache) == {"AAPL", "VUSA.L"}  # unknown not cached


def test_async_close_warning(fake_yf: None) -> None:
    """Only daily data across regions is warned about."""
    assert data.async_close_warning(["AAPL"], "1d") is None
    assert data.async_close_warning(["AAPL", "VUSA.L"], "1wk") is None
    warning = data.async_close_warning(["AAPL", "VUSA.L"], "1d")
    assert warning and "America, Europe" in warning


def test_download_fx(monkeypatch: pytest.MonkeyPatch) -> None:
    """FX pairs are requested as XXXBASE=X and renamed to the currency."""
    idx = pd.DatetimeIndex(["2026-01-05"])
    asked: list[list[str]] = []

    def close(symbols: list[str], *args: Any) -> pd.DataFrame:
        """Return only the USD pair.

        Args:
            symbols: Requested FX symbols.
            *args: Ignored.

        Returns:
            The closes that exist.
        """
        asked.append(symbols)
        return pd.DataFrame({"USDEUR=X": [0.9]}, index=idx)

    monkeypatch.setattr(data, "download_close", close)
    assert data.download_fx({"EUR", ""}, "eur", None, None).empty
    fx = data.download_fx({"USD", "EUR"}, "EUR", None, None)
    assert list(fx.columns) == ["USD"] and asked == [["USDEUR=X"]]
    with pytest.raises(YahooError) as exc:
        data.download_fx({"USD", "XYZ"}, "EUR", None, None)
    assert exc.value.code == "fx_unavailable"

    monkeypatch.setattr(data, "download_close", lambda *a: pd.DataFrame())
    monkeypatch.setattr(data, "yahoo_reachable", lambda: False)
    with pytest.raises(YahooError) as exc:
        data.download_fx({"USD"}, "EUR", None, None)
    assert exc.value.code == "upstream_unavailable"


def test_prices_in_currency_unknown_currency(
    fake_yahoo: list[list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A symbol whose quote currency is unknown cannot be converted."""
    monkeypatch.setattr(data, "get_currencies", lambda syms: dict.fromkeys(syms))
    with pytest.raises(YahooError) as exc:
        data.prices_in_currency(["AAPL"], "2026-01-01", None, "1d", "EUR")
    assert exc.value.code == "no_data" and "AAPL" in exc.value.message
