"""Browser client wrapper for the F5 web verifier.

Phase 1 speed variant: rather than wire up the full Browser Use Cloud SDK
(which needs an account + API key), we ship a thin httpx-based fallback
that fetches a single URL, strips HTML tags with a regex, and returns the
text. Good enough for the verifier's "did the page say this?" prompt.

The public surface (`browser_session` + `BrowserSession.fetch_page`) is
shaped so a real BrowserUse implementation can drop in without touching
the mini-agent.
"""

from __future__ import annotations

import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from pydantic import BaseModel

from app.logging import get_logger

log = get_logger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_HTTP_TIMEOUT_S = 10.0
_MAX_TEXT_CHARS = 20_000


class PageFetchResult(BaseModel):
    ok: bool
    url: str
    text: str | None = None
    error: str | None = None


def _strip_html(raw: str) -> str:
    no_tags = _HTML_TAG_RE.sub(" ", raw)
    collapsed = _WS_RE.sub(" ", no_tags).strip()
    return collapsed[:_MAX_TEXT_CHARS]


class BrowserSession:
    """One per-claim browser session.

    In the speed variant this just owns an httpx.AsyncClient (lazily
    constructed on first fetch). The full Browser Use Cloud impl will
    swap this out and keep the same `fetch_page` contract.
    """

    def __init__(self, name: str, timeout_ms: int) -> None:
        self.name = name
        self.timeout_s = max(1.0, timeout_ms / 1000.0)
        self._client: object | None = None

    async def fetch_page(self, url: str) -> PageFetchResult:
        try:
            import httpx
        except ImportError as e:
            log.warning("browser_client_httpx_missing", error=str(e))
            return PageFetchResult(ok=False, url=url, error="httpx_not_installed")

        timeout = min(self.timeout_s, _HTTP_TIMEOUT_S)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (compatible; vof-web-verifier/0.1; "
                        "+https://github.com/vof)"
                    ),
                },
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                text = _strip_html(resp.text)
                return PageFetchResult(ok=True, url=str(resp.url), text=text)
        except Exception as e:  # noqa: BLE001 - want the broad net here
            log.info(
                "browser_client_fetch_failed",
                url=url,
                error=f"{type(e).__name__}: {e}",
            )
            return PageFetchResult(ok=False, url=url, error=f"{type(e).__name__}: {e}")


@asynccontextmanager
async def browser_session(name: str, timeout_ms: int = 30_000) -> AsyncIterator[BrowserSession]:
    """Mint a browser session for a single verifier invocation.

    `name` is a short label (used for log correlation, and would become the
    Browser Use Cloud session name once we wire that SDK in).
    """
    if os.environ.get("BROWSER_USE_API_KEY", ""):
        log.info("browser_use_api_key_present_but_using_httpx_fallback", session=name)
    session = BrowserSession(name=name, timeout_ms=timeout_ms)
    try:
        yield session
    finally:
        # httpx clients are scoped per-fetch in the fallback, so nothing
        # to tear down here. Kept for parity with the future SDK impl.
        pass
