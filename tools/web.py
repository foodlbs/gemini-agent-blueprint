"""Web fetching tool used by the Docs researcher.

DESIGN.md "Tools to implement" lists ``web_fetch`` as ADK built-in. ADK
provides ``url_context`` and ``load_web_page``, but those route through
Gemini's grounding rather than returning page bodies the LLM can pass
through to other tools. The Docs researcher needs explicit fetched
content (to extract code examples and prerequisites), so we provide
``web_fetch`` as a small custom tool here.
"""

import logging
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 15
MAX_BYTES = 200_000  # ~200KB cap to keep LLM context costs sane.
USER_AGENT = "ai-release-pipeline-researcher/0.1"


def web_fetch(url: str) -> dict:
    """Fetch ``url`` over HTTP and return the body as text.

    Used by the Docs researcher to grab release notes, blog posts, and
    documentation pages. Network errors return a dict with ``error`` set
    and ``content`` empty rather than raising — researchers should
    degrade gracefully when one source is offline.

    Args:
        url: HTTP or HTTPS URL.

    Returns:
        dict with:
        - ``status``: int HTTP status code (or 0 on connection failure).
        - ``content``: str, body decoded as UTF-8 and truncated to
          ``MAX_BYTES``.
        - ``error``: Optional[str] — error message if the fetch failed.
    """
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html, text/plain, application/json, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
            data = resp.read(MAX_BYTES)
            return {
                "status": int(getattr(resp, "status", 200)),
                "content": data.decode("utf-8", errors="replace"),
                "error": None,
            }
    except Exception as e:
        logger.warning("web_fetch(%s) failed: %s", url, e)
        return {"status": 0, "content": "", "error": str(e)}
