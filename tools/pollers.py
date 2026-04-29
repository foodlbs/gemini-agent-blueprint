"""Pollers for the Scout agent.

Each function takes a ``since`` cutoff (datetime or ISO 8601 string — the
LLM passes JSON-serializable strings) and returns a list of ``Candidate``
dicts newer than ``since``. Every poller is network-bound and degrades to
``[]`` on failure rather than raising; Scout merges across sources and one
outage should not abort a polling cycle.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional, Union

import arxiv
import feedparser
from huggingface_hub import HfApi

from shared.models import Candidate

logger = logging.getLogger(__name__)


# Lab + community RSS feeds. Each key MUST be a valid SourceType Literal in
# shared/models.py — adding a new feed here may require extending that union.
# URLs are validated by tests/smoke/pollers_smoke.py against live HTTP. Drop
# any feed that 404s rather than letting it silently swallow a polling cycle.
#
# Notable absences:
#   anthropic — has no RSS endpoint. Covered by ``poll_anthropic_news`` which
#               scrapes the /news index page directly.
#   mistral   — has no RSS endpoint. Their model releases land on Hugging
#               Face and so are picked up by ``poll_hf_models``.
RSS_FEEDS: dict[str, str] = {
    "google":           "https://blog.google/technology/ai/rss/",
    "openai":           "https://openai.com/news/rss.xml",
    "deepmind":         "https://deepmind.google/blog/rss.xml",
    "meta":             "https://research.facebook.com/feed/",
    "huggingface_blog": "https://huggingface.co/blog/feed.xml",
    "nvidia":           "https://blogs.nvidia.com/blog/category/deep-learning/feed/",
    "microsoft":        "https://www.microsoft.com/en-us/research/feed/",
    "bair":             "https://bair.berkeley.edu/blog/feed.xml",
}

# Anthropic news index URL — scraped because Anthropic publishes no RSS feed.
ANTHROPIC_NEWS_URL = "https://www.anthropic.com/news"
_ANTHROPIC_ARTICLE_PATTERN = re.compile(
    r'<a[^>]+href="(/news/[^"#?]+)"[^>]*>',
    re.IGNORECASE,
)
_ANTHROPIC_TITLE_PATTERN = re.compile(
    r'<h\d[^>]*>([^<]+)</h\d>',
    re.IGNORECASE,
)

ARXIV_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL"
ARXIV_MAX_RESULTS = 50

GITHUB_TRENDING_URL = (
    "https://github.com/trending?since=daily&spoken_language_code=en"
)
HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HN_AI_SEARCH_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?tags=story&query=AI&hitsPerPage=50"
)
HTTP_TIMEOUT_SECONDS = 10
USER_AGENT = "ai-release-pipeline-scout/0.1"

_TRENDING_REPO_PATTERN = re.compile(
    r'<h2[^>]*class="[^"]*h3[^"]*lh-condensed[^"]*"[^>]*>\s*'
    r'<a[^>]*href="/([^"/?#]+)/([^"/?#]+)"',
    re.IGNORECASE | re.DOTALL,
)


def poll_arxiv(since: Union[datetime, str]) -> list[dict]:
    """Poll arXiv for recent submissions in the AI/ML categories.

    Queries ``cs.AI``, ``cs.LG``, and ``cs.CL`` sorted by ``SubmittedDate``
    descending, then filters in-process for entries published after
    ``since``. Network or parse errors are logged and an empty list is
    returned — a failed arXiv call must not block Scout's other sources.

    Args:
        since: UTC cutoff. Accepts ``datetime`` or ISO 8601 string (the
            LLM passes JSON-serializable strings).

    Returns:
        ``list[Candidate]`` with ``source="arxiv"``. Empty on any failure.
    """
    try:
        cutoff = _parse_since(since)
        search = arxiv.Search(
            query=ARXIV_QUERY,
            max_results=ARXIV_MAX_RESULTS,
            sort_by=arxiv.SortCriterion.SubmittedDate,
            sort_order=arxiv.SortOrder.Descending,
        )
        client = arxiv.Client()
        candidates: list[Candidate] = []
        for result in client.results(search):
            published = _ensure_utc(result.published)
            if published is None:
                continue
            if published <= cutoff:
                break
            candidates.append(
                Candidate(
                    title=result.title.strip(),
                    url=result.entry_id,
                    source="arxiv",
                    published_at=published,
                    raw_summary=result.summary.strip(),
                )
            )
        return [c.model_dump(mode="json") for c in candidates]
    except Exception as e:
        logger.warning("poll_arxiv failed: %s", e)
        return []


def poll_github_trending(since: Union[datetime, str]) -> list[dict]:
    """Scrape ``github.com/trending`` for the daily top repositories.

    GitHub does not expose trending via an official API, so this fetches
    the public HTML and extracts repo slugs from the section headers.
    The ``since`` argument is accepted for parity with the other pollers
    but trending is windowed by GitHub itself (daily) — ``published_at``
    is set to "now", and deduplication against prior cycles is delegated
    to Memory Bank in Triage.

    Args:
        since: Accepted for API parity (``datetime`` or ISO 8601 string);
            not used for filtering since GitHub windows trending itself.

    Returns:
        ``list[Candidate]`` with ``source="github"``. Empty on any failure.
    """
    try:
        _parse_since(since)  # Validate format; result unused (trending is daily-windowed).
        req = urllib.request.Request(
            GITHUB_TRENDING_URL,
            headers={"User-Agent": USER_AGENT},
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        seen: set[str] = set()
        candidates: list[Candidate] = []
        now = datetime.now(timezone.utc)
        for owner, repo in _TRENDING_REPO_PATTERN.findall(html):
            slug = f"{owner}/{repo}".strip()
            if slug in seen:
                continue
            seen.add(slug)
            candidates.append(
                Candidate(
                    title=slug,
                    url=f"https://github.com/{owner}/{repo}",
                    source="github",
                    published_at=now,
                    raw_summary=f"Trending GitHub repository: {slug}",
                )
            )
        return [c.model_dump(mode="json") for c in candidates]
    except Exception as e:
        logger.warning("poll_github_trending failed: %s", e)
        return []


def poll_rss(since: Union[datetime, str]) -> list[dict]:
    """Poll the configured lab-blog RSS feeds for posts after ``since``.

    Each feed in ``RSS_FEEDS`` is mapped to a SourceType label (e.g.
    ``anthropic``, ``deepmind``, ``mistral``). Per-feed errors are logged
    and skipped; one bad feed does not break the others. Entries lacking
    a parseable published/updated date are dropped.

    Args:
        since: UTC cutoff. Accepts ``datetime`` or ISO 8601 string.

    Returns:
        ``list[Candidate]`` aggregated across all feeds. Empty if every
        feed fails or yields nothing newer than ``since``.
    """
    cutoff = _parse_since(since)
    candidates: list[Candidate] = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(
                url, request_headers={"User-Agent": USER_AGENT}
            )
            for entry in feed.entries:
                published = _entry_published_at(entry)
                if published is None or published <= cutoff:
                    continue
                title = (getattr(entry, "title", "") or "").strip()
                link = (getattr(entry, "link", "") or "").strip()
                summary = (getattr(entry, "summary", "") or "").strip()
                if not title or not link:
                    continue
                candidates.append(
                    Candidate(
                        title=title,
                        url=link,
                        source=source,
                        published_at=published,
                        raw_summary=summary,
                    )
                )
        except Exception as e:
            logger.warning("poll_rss(%s) failed: %s", url, e)
    return [c.model_dump(mode="json") for c in candidates]


def poll_hf_models(since: Union[datetime, str]) -> list[dict]:
    """Poll Hugging Face for models updated since ``since``.

    Uses ``HfApi.list_models`` sorted by ``lastModified``; the API returns
    newest-first naturally for time fields, so we filter in-process and
    stop on the first stale entry. Iteration is bounded by ``limit`` to
    cap pagination cost.

    Args:
        since: UTC cutoff. Accepts ``datetime`` or ISO 8601 string.

    Returns:
        ``list[Candidate]`` with ``source="huggingface"``. Empty on any
        failure.
    """
    try:
        cutoff = _parse_since(since)
        api = HfApi()
        # Note: ``direction`` was removed from huggingface_hub.list_models
        # in 0.25; sort="lastModified" returns newest-first by default.
        models = api.list_models(sort="lastModified", limit=100)
        candidates: list[Candidate] = []
        for model in models:
            modified = _ensure_utc(
                getattr(model, "lastModified", None)
                or getattr(model, "last_modified", None)
            )
            if modified is None:
                continue
            if modified <= cutoff:
                break
            model_id = getattr(model, "modelId", None) or getattr(model, "id", "")
            if not model_id:
                continue
            candidates.append(
                Candidate(
                    title=model_id,
                    url=f"https://huggingface.co/{model_id}",
                    source="huggingface",
                    published_at=modified,
                    raw_summary=f"Hugging Face model updated: {model_id}",
                )
            )
        return [c.model_dump(mode="json") for c in candidates]
    except Exception as e:
        logger.warning("poll_hf_models failed: %s", e)
        return []


def poll_hf_papers(since: Union[datetime, str]) -> list[dict]:
    """Poll the Hugging Face daily-papers feed for new submissions.

    Uses ``GET /api/daily_papers`` (the same endpoint that powers
    https://huggingface.co/papers). Fail-open returns ``[]``; any single
    paper that fails to parse is skipped without aborting the batch.

    Args:
        since: UTC cutoff. Accepts ``datetime`` or ISO 8601 string.

    Returns:
        ``list[Candidate]`` with ``source="huggingface_papers"``.
    """
    try:
        cutoff = _parse_since(since)
        req = urllib.request.Request(
            HF_PAPERS_URL, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        candidates: list[Candidate] = []
        for item in payload:
            paper = item.get("paper") or {}
            arxiv_id = paper.get("id") or item.get("id")
            title = (paper.get("title") or item.get("title") or "").strip()
            if not arxiv_id or not title:
                continue
            published_raw = (
                paper.get("publishedAt")
                or item.get("publishedAt")
                or item.get("submittedOnDailyAt")
            )
            published = _parse_iso(published_raw)
            if published is None or published <= cutoff:
                continue
            summary = (paper.get("summary") or "").strip()
            candidates.append(
                Candidate(
                    title=title,
                    url=f"https://huggingface.co/papers/{arxiv_id}",
                    source="huggingface_papers",
                    published_at=published,
                    raw_summary=summary or f"Hugging Face daily paper: {title}",
                )
            )
        return [c.model_dump(mode="json") for c in candidates]
    except Exception as e:
        logger.warning("poll_hf_papers failed: %s", e)
        return []


def poll_anthropic_news(since: Union[datetime, str]) -> list[dict]:
    """Scrape ``anthropic.com/news`` for the latest news/release entries.

    Anthropic publishes no RSS or JSON feed; this pulls the index HTML and
    extracts the unique ``/news/<slug>`` links shown on the landing page.
    The slug is humanized into a title (e.g. ``claude-opus-4-7`` →
    ``Claude Opus 4 7``); ``published_at`` is set to "now" because the
    index page does not expose per-entry dates and Triage delegates
    dedup to Memory Bank either way.

    Args:
        since: Accepted for API parity (``datetime`` or ISO 8601 string);
            not used for filtering since the index has no dates.

    Returns:
        ``list[Candidate]`` with ``source="anthropic"``. Empty on any failure.
    """
    try:
        _parse_since(since)
        req = urllib.request.Request(
            ANTHROPIC_NEWS_URL, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        seen: set[str] = set()
        candidates: list[Candidate] = []
        now = datetime.now(timezone.utc)
        for path in _ANTHROPIC_ARTICLE_PATTERN.findall(html):
            slug = path.rsplit("/", 1)[-1]
            if not slug or slug in seen:
                continue
            seen.add(slug)
            title = slug.replace("-", " ").strip().title()
            candidates.append(
                Candidate(
                    title=title,
                    url=f"https://www.anthropic.com{path}",
                    source="anthropic",
                    published_at=now,
                    raw_summary=f"Anthropic news entry: {title}",
                )
            )
            if len(candidates) >= 15:
                break
        return [c.model_dump(mode="json") for c in candidates]
    except Exception as e:
        logger.warning("poll_anthropic_news failed: %s", e)
        return []


def poll_hackernews_ai(since: Union[datetime, str]) -> list[dict]:
    """Poll the Hacker News Algolia API for AI-tagged stories after ``since``.

    Uses ``hn.algolia.com/api/v1/search_by_date`` to page newest-first.
    Captures up to 50 hits per call. Fail-open returns ``[]``.

    Args:
        since: UTC cutoff. Accepts ``datetime`` or ISO 8601 string.

    Returns:
        ``list[Candidate]`` with ``source="hackernews"``.
    """
    try:
        cutoff = _parse_since(since)
        req = urllib.request.Request(
            HN_AI_SEARCH_URL, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_SECONDS) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        candidates: list[Candidate] = []
        for hit in payload.get("hits", []):
            ts = hit.get("created_at_i")
            if ts is None:
                continue
            published = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            if published <= cutoff:
                # Algolia returns newest-first with `search_by_date`; once
                # we cross the cutoff every subsequent hit is older.
                break
            title = (hit.get("title") or hit.get("story_title") or "").strip()
            url = (hit.get("url") or hit.get("story_url") or "").strip()
            if not title:
                continue
            if not url:
                # Self-post / Ask HN — link to the discussion thread.
                url = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            candidates.append(
                Candidate(
                    title=title,
                    url=url,
                    source="hackernews",
                    published_at=published,
                    raw_summary=(
                        f"Hacker News story (points={hit.get('points', 0)}, "
                        f"comments={hit.get('num_comments', 0)})"
                    ),
                )
            )
        return [c.model_dump(mode="json") for c in candidates]
    except Exception as e:
        logger.warning("poll_hackernews_ai failed: %s", e)
        return []


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Coerce a naive datetime to UTC; leave aware datetimes unchanged."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _parse_since(value: Union[datetime, str]) -> datetime:
    """Coerce a ``since`` argument to a UTC ``datetime``.

    The Scout LlmAgent calls these functions through ADK, which serializes
    arguments to JSON. Datetimes therefore arrive as ISO 8601 strings even
    though the Python type hint says ``datetime``. Accept both shapes and
    raise ``TypeError`` on anything else (caller catches and fails-open).
    """
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, str):
        parsed = _parse_iso(value)
        if parsed is None:
            raise ValueError(f"unparseable since value: {value!r}")
        return parsed
    raise TypeError(
        f"since must be datetime or ISO 8601 string, got {type(value).__name__}"
    )


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Best-effort ISO 8601 parse. Accepts ``Z`` suffix and naive strings."""
    if not value:
        return None
    candidate = value.strip()
    # ``datetime.fromisoformat`` (3.11+) accepts ``Z`` as the UTC marker, but
    # older inputs may have ``Z`` followed by trailing whitespace; be defensive.
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        return _ensure_utc(datetime.fromisoformat(candidate))
    except ValueError:
        # Fall back for inputs like ``2026-04-28`` (date only).
        try:
            return datetime.strptime(candidate, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def _entry_published_at(entry) -> Optional[datetime]:
    """Pull a UTC datetime from a feedparser entry's published/updated tuple."""
    parsed = (
        getattr(entry, "published_parsed", None)
        or getattr(entry, "updated_parsed", None)
    )
    if parsed is None:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
