import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from finance_mcp.auth import ApiKeyMiddleware, load_keys

TOKEN = "alice-secret-token-123"


def _client() -> TestClient:
    async def ok(_):
        return PlainTextResponse("hi")

    app = Starlette(routes=[Route("/mcp", ok), Route("/health", ok)])
    return TestClient(ApiKeyMiddleware(app, load_keys(f"alice:{TOKEN},bob:{TOKEN}x")))


def test_load_keys_parses_pairs():
    assert load_keys("a:0123456789abcdef, b:fedcba9876543210") == {
        "0123456789abcdef": "a",
        "fedcba9876543210": "b",
    }


@pytest.mark.parametrize("raw", ["nocolon", ":0123456789abcdef", "a:short"])
def test_load_keys_rejects_bad_entries(raw):
    with pytest.raises(ValueError):
        load_keys(raw)


def test_rejects_missing_and_wrong_token():
    c = _client()
    assert c.get("/mcp").status_code == 401
    assert c.get("/mcp", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert c.get("/mcp?key=nope").status_code == 401


def test_accepts_bearer_and_query_token():
    c = _client()
    assert (
        c.get("/mcp", headers={"Authorization": f"Bearer {TOKEN}"}).status_code == 200
    )
    assert c.get(f"/mcp?key={TOKEN}").status_code == 200


def test_health_is_public():
    assert _client().get("/health").status_code == 200
