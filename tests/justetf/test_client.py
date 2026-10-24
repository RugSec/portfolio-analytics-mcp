"""justETF HTTP client, ISIN validation and disk cache (HTTP faked)."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from finance_mcp.justetf import client
from finance_mcp.justetf.client import JustEtfError, normalize_isin
from tests.fakes import AJAX, ISIN, PAGE


def test_isin_validation() -> None:
    """ISINs are normalised; bad formats and check digits are rejected."""
    assert normalize_isin(" ie00b4l5y983 ") == "IE00B4L5Y983"
    for bad in ["", "IE00B4L5Y98", "IE00B4L5Y984", "../etc/passwd"]:
        with pytest.raises(JustEtfError):
            normalize_isin(bad)


# Wicket "Show more" link as it appears inside the page's inline JavaScript.
LOAD_MORE = (
    '"u":"/en/etf-profile.html?0-1.0-holdingsSection-countries-'
    'loadMoreCountries&isin=IE00B4L5Y983"'
)


@pytest.fixture
def fake_http(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[httpx.Request]]:
    """Route the client's httpx traffic through a handler, without sleeping.

    Args:
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        A function that installs a request handler and returns the request log.
    """
    monkeypatch.setattr(client, "MIN_INTERVAL_S", 0.0)
    monkeypatch.setattr(client.time, "sleep", lambda s: None)
    real_client = httpx.Client

    def install(
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> list[httpx.Request]:
        """Make every new ``httpx.Client`` use ``handler`` as its transport.

        Args:
            handler: Function answering each request.

        Returns:
            The list every handled request is appended to.
        """
        log: list[httpx.Request] = []

        def logged(request: httpx.Request) -> httpx.Response:
            """Record the request, then answer it.

            Args:
                request: The outgoing request.

            Returns:
                The handler's response.
            """
            log.append(request)
            return handler(request)

        def make_client(**kwargs: Any) -> httpx.Client:
            """Build a real client bound to the mock transport.

            Args:
                **kwargs: Options the code under test passes to ``httpx.Client``.

            Returns:
                The client.
            """
            return real_client(transport=httpx.MockTransport(logged), **kwargs)

        monkeypatch.setattr(client.httpx, "Client", make_client)
        return log

    return install


def test_fetch_profile_pages_with_fragment(
    fake_http: Callable[..., list[httpx.Request]],
) -> None:
    """The page and its 'Show more countries' fragment are both fetched."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Answer the profile page, then the AJAX fragment.

        Args:
            request: The outgoing request.

        Returns:
            Page HTML or fragment XML.
        """
        if request.headers.get("Wicket-Ajax") == "true":
            return httpx.Response(200, text=AJAX)
        return httpx.Response(200, text=PAGE + LOAD_MORE)

    log = fake_http(handler)
    html, fragments = client.fetch_profile_pages(ISIN)
    assert "Test World ETF" in html
    assert set(fragments) == {"countries"}
    assert log[0].url.params["isin"] == ISIN
    assert log[0].headers["User-Agent"] == client.USER_AGENT
    assert "loadMoreCountries" in str(log[1].url)


def test_fetch_profile_pages_skips_failed_fragment(
    fake_http: Callable[..., list[httpx.Request]],
) -> None:
    """A fragment that cannot be loaded is left out instead of failing."""

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the page; refuse the fragment.

        Args:
            request: The outgoing request.

        Returns:
            Page HTML, or HTTP 403 for the fragment.
        """
        if request.headers.get("Wicket-Ajax") == "true":
            return httpx.Response(403)
        return httpx.Response(200, text=PAGE + LOAD_MORE)

    fake_http(handler)
    _, fragments = client.fetch_profile_pages(ISIN)
    assert fragments == {}


@pytest.mark.parametrize(
    ("status", "message"),
    [(404, "not found"), (302, "Unexpected"), (429, "refused"), (403, "refused")],
)
def test_fetch_profile_pages_errors(
    fake_http: Callable[..., list[httpx.Request]], status: int, message: str
) -> None:
    """Not found, odd status codes and blocks raise JustEtfError without retrying."""
    log = fake_http(lambda r: httpx.Response(status))
    with pytest.raises(JustEtfError, match=message):
        client.fetch_profile_pages(ISIN)
    assert len(log) == 1


def test_get_retries_server_and_network_errors(
    fake_http: Callable[..., list[httpx.Request]],
) -> None:
    """5xx and connection errors are retried 3 times, then reported."""
    log = fake_http(lambda r: httpx.Response(503))
    with pytest.raises(JustEtfError, match="Could not reach justETF"):
        client.fetch_profile_pages(ISIN)
    assert len(log) == 3

    def broken(request: httpx.Request) -> httpx.Response:
        """Fail like a network outage.

        Args:
            request: The outgoing request.

        Raises:
            httpx.ConnectError: Always.
        """
        raise httpx.ConnectError("down", request=request)

    log = fake_http(broken)
    with pytest.raises(JustEtfError, match="down"):
        client.fetch_profile_pages(ISIN)
    assert len(log) == 3


def test_throttle_waits_between_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second request within MIN_INTERVAL_S sleeps for the remainder."""
    slept: list[float] = []
    monkeypatch.setattr(client, "MIN_INTERVAL_S", 10.0)
    monkeypatch.setattr(client.time, "sleep", slept.append)
    monkeypatch.setattr(client, "_last_request", client.time.monotonic())
    client._throttle()
    assert slept and 0 < slept[0] <= 10.0


def test_cache_roundtrip_and_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cached profiles are returned until the TTL passes."""
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path / "cache")
    assert client.cache_get(ISIN) is None
    client.cache_put(ISIN, {"isin": ISIN})
    assert client.cache_get(ISIN) == {"isin": ISIN}
    old = client.time.time() - client.CACHE_TTL_S - 60
    os.utime(tmp_path / "cache" / f"{ISIN}.json", (old, old))
    assert client.cache_get(ISIN) is None


def test_cache_put_ignores_write_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache directory that cannot be created never breaks a lookup."""
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setattr(client, "CACHE_DIR", blocker / "sub")
    client.cache_put(ISIN, {"isin": ISIN})  # no exception
