"""Keep blocking tools off the event loop.

FastMCP calls a synchronous tool directly on the event loop, so one slow
network call (or a justETF throttle sleep) would stall every other HTTP
client. ``ThreadedFastMCP`` runs sync tools in worker threads instead, with
a cap on how many run at once so upstream sites are not hammered.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

import anyio
import anyio.to_thread
from mcp.server.fastmcp import FastMCP

MAX_CONCURRENT_TOOLS = 4

# Created lazily: a CapacityLimiter must be built inside a running event loop.
_limiter: anyio.CapacityLimiter | None = None


def _get_limiter() -> anyio.CapacityLimiter:
    """Return the shared limiter on tool worker threads.

    Returns:
        The process-wide limiter, created on first use.
    """
    global _limiter
    if _limiter is None:
        _limiter = anyio.CapacityLimiter(MAX_CONCURRENT_TOOLS)
    return _limiter


def run_in_thread(fn: Any) -> Any:
    """Wrap a sync function as an async one that runs it in a worker thread.

    Args:
        fn: The blocking function.

    Returns:
        An async function with the same name, docstring and signature.
    """

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Run ``fn`` in a worker thread, at most MAX_CONCURRENT_TOOLS at once.

        Args:
            *args: Positional arguments for ``fn``.
            **kwargs: Keyword arguments for ``fn``.

        Returns:
            Whatever ``fn`` returns.
        """
        return await anyio.to_thread.run_sync(
            functools.partial(fn, *args, **kwargs), limiter=_get_limiter()
        )

    return wrapper


class ThreadedFastMCP(FastMCP):
    """FastMCP that runs synchronous tools in worker threads."""

    def add_tool(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        """Register a tool, offloading it to a thread if it is synchronous.

        Args:
            fn: The tool function (sync or async).
            *args: Passed to ``FastMCP.add_tool``.
            **kwargs: Passed to ``FastMCP.add_tool``.
        """
        if not inspect.iscoroutinefunction(fn):
            fn = run_in_thread(fn)
        super().add_tool(fn, *args, **kwargs)
