"""Shared-secret authentication for the HTTP transport.

Keys come from ``MCP_API_KEYS`` as comma-separated ``name:token`` pairs (the
name only labels the user in logs). A request is accepted when it carries a
known token as ``Authorization: Bearer <token>`` or as a ``?key=<token>`` query
parameter, for clients that can only be given a URL.
"""

from __future__ import annotations

import hmac
import logging
import os
from urllib.parse import parse_qs

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("finance_mcp.auth")

PUBLIC_PATHS = frozenset({"/health"})


def load_keys(raw: str | None = None) -> dict[str, str]:
    """Parse ``name:token,name:token`` into a ``{token: name}`` mapping.

    Args:
        raw: The key list; defaults to the ``MCP_API_KEYS`` environment variable.

    Returns:
        ``{token: name}``; empty if no keys are configured.

    Raises:
        ValueError: if an entry has no name or a token under 16 characters.
    """
    raw = os.environ.get("MCP_API_KEYS", "") if raw is None else raw
    keys: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        name, sep, token = item.partition(":")
        if not sep or not name.strip() or len(token.strip()) < 16:
            raise ValueError(
                "MCP_API_KEYS entries must look like 'name:token' with a token "
                "of at least 16 characters"
            )
        keys[token.strip()] = name.strip()
    return keys


class ApiKeyMiddleware:
    """ASGI middleware that rejects requests without a known API key (HTTP 401)."""

    def __init__(self, app: ASGIApp, keys: dict[str, str]) -> None:
        """Wrap an ASGI app.

        Args:
            app: The app to protect.
            keys: ``{token: name}`` from ``load_keys``.

        Raises:
            ValueError: if ``keys`` is empty.
        """
        if not keys:
            raise ValueError("ApiKeyMiddleware needs at least one key")
        self.app = app
        self.keys = keys

    def _identify(self, request: Request) -> str | None:
        """Find the user a request's token belongs to.

        Args:
            request: The incoming request.

        Returns:
            The key's name, or None if the token is missing or unknown.
        """
        header = request.headers.get("authorization", "")
        scheme, _, bearer = header.partition(" ")
        candidate = bearer.strip() if scheme.lower() == "bearer" else ""
        if not candidate:
            candidate = parse_qs(request.url.query).get("key", [""])[0]
        # Compare against every key so timing doesn't reveal which one matched.
        match = None
        for token, name in self.keys.items():
            if hmac.compare_digest(candidate.encode(), token.encode()):
                match = name
        return match

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass authorised HTTP requests (and public paths) through, else 401.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.
        """
        if scope["type"] != "http" or scope["path"] in PUBLIC_PATHS:
            await self.app(scope, receive, send)
            return
        user = self._identify(Request(scope))
        if user is None:
            response = JSONResponse(
                {"error": "unauthorized"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        scope.setdefault("state", {})["user"] = user  # available as request.state.user
        logger.info("request from %s: %s", user, scope["path"])
        await self.app(scope, receive, send)
