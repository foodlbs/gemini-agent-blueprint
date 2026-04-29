"""Tests for Scout: pollers (unit) and agent wiring (integration)."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from shared.models import Candidate
from tools import pollers


@pytest.fixture
def since() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=24)


# --- poll_arxiv --------------------------------------------------------------


def test_poll_arxiv_returns_candidates_for_fresh_results(since):
    fresh = datetime.now(timezone.utc)
    fake_result = MagicMock(
        title="A Test Paper on Foo",
        entry_id="https://arxiv.org/abs/2401.00001",
        published=fresh,
        summary="Test paper summary.",
    )
    with patch.object(pollers.arxiv, "Client") as mock_client_cls, \
         patch.object(pollers.arxiv, "Search"):
        mock_client_cls.return_value.results.return_value = iter([fake_result])
        results = pollers.poll_arxiv(since)
    assert len(results) == 1
    assert results[0]["source"] == "arxiv"
    assert results[0]["title"] == "A Test Paper on Foo"
    assert results[0]["url"] == "https://arxiv.org/abs/2401.00001"


def test_poll_arxiv_stops_at_since_boundary(since):
    old_result = MagicMock(
        title="Old Paper",
        entry_id="https://arxiv.org/abs/0001",
        published=since - timedelta(hours=1),
        summary="Old.",
    )
    with patch.object(pollers.arxiv, "Client") as mock_client_cls, \
         patch.object(pollers.arxiv, "Search"):
        mock_client_cls.return_value.results.return_value = iter([old_result])
        results = pollers.poll_arxiv(since)
    assert results == []


def test_poll_arxiv_returns_empty_on_network_error(since):
    with patch.object(pollers.arxiv, "Search", side_effect=RuntimeError("boom")):
        results = pollers.poll_arxiv(since)
    assert results == []


# --- poll_github_trending ----------------------------------------------------


def _mock_urlopen_response(html: str) -> MagicMock:
    response = MagicMock()
    response.read.return_value = html.encode("utf-8")
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_poll_github_trending_extracts_repos(since):
    html = (
        '<h2 class="h3 lh-condensed">'
        '<a href="/owner/repo" class="Link">repo</a></h2>'
        '<h2 class="h3 lh-condensed">'
        '<a href="/owner2/repo2" class="Link">repo2</a></h2>'
    )
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(html)):
        results = pollers.poll_github_trending(since)
    assert len(results) == 2
    assert {r["url"] for r in results} == {
        "https://github.com/owner/repo",
        "https://github.com/owner2/repo2",
    }
    assert all(r["source"] == "github" for r in results)


def test_poll_github_trending_dedupes_repeats(since):
    html = (
        '<h2 class="h3 lh-condensed">'
        '<a href="/owner/repo" class="Link">repo</a></h2>'
        '<h2 class="h3 lh-condensed">'
        '<a href="/owner/repo" class="Link">repo</a></h2>'
    )
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(html)):
        results = pollers.poll_github_trending(since)
    assert len(results) == 1


def test_poll_github_trending_returns_empty_on_network_error(since):
    with patch("urllib.request.urlopen", side_effect=RuntimeError("boom")):
        results = pollers.poll_github_trending(since)
    assert results == []


# --- poll_rss ----------------------------------------------------------------


def _rss_entry(published: datetime, **overrides):
    entry = MagicMock(
        title="A New Release",
        link="https://example.com/post",
        summary="Summary text.",
        published_parsed=published.timetuple()[:9],
        updated_parsed=None,
    )
    for k, v in overrides.items():
        setattr(entry, k, v)
    return entry


def test_poll_rss_returns_fresh_entries(since):
    fresh_entry = _rss_entry(datetime.now(timezone.utc) + timedelta(seconds=30))
    fake_feed = MagicMock(entries=[fresh_entry])
    with patch.object(pollers.feedparser, "parse", return_value=fake_feed):
        results = pollers.poll_rss(since)
    assert len(results) == len(pollers.RSS_FEEDS)
    assert {r["source"] for r in results} == set(pollers.RSS_FEEDS.keys())


def test_poll_rss_skips_old_entries(since):
    old_entry = _rss_entry(since - timedelta(hours=1))
    fake_feed = MagicMock(entries=[old_entry])
    with patch.object(pollers.feedparser, "parse", return_value=fake_feed):
        results = pollers.poll_rss(since)
    assert results == []


def test_poll_rss_returns_empty_when_every_feed_fails(since):
    with patch.object(pollers.feedparser, "parse", side_effect=RuntimeError("dns")):
        results = pollers.poll_rss(since)
    assert results == []


# --- poll_hf_models ----------------------------------------------------------


def test_poll_hf_models_returns_candidates(since):
    fresh_model = MagicMock()
    fresh_model.modelId = "owner/test-model"
    fresh_model.lastModified = datetime.now(timezone.utc)
    fresh_model.id = "owner/test-model"
    with patch.object(pollers.HfApi, "list_models", return_value=[fresh_model]):
        results = pollers.poll_hf_models(since)
    assert len(results) == 1
    assert results[0]["source"] == "huggingface"
    assert results[0]["title"] == "owner/test-model"
    assert results[0]["url"] == "https://huggingface.co/owner/test-model"


def test_poll_hf_models_stops_at_since_boundary(since):
    old_model = MagicMock()
    old_model.modelId = "old/model"
    old_model.lastModified = since - timedelta(hours=1)
    old_model.id = "old/model"
    with patch.object(pollers.HfApi, "list_models", return_value=[old_model]):
        results = pollers.poll_hf_models(since)
    assert results == []


def test_poll_hf_models_returns_empty_on_failure(since):
    with patch.object(pollers.HfApi, "list_models", side_effect=RuntimeError("api")):
        results = pollers.poll_hf_models(since)
    assert results == []


def test_poll_hf_models_no_longer_passes_direction_kwarg(since):
    """Regression: huggingface_hub>=0.25 removed ``direction``; passing it
    raises TypeError. Verify the call site uses only ``sort`` + ``limit``."""
    fresh_model = MagicMock()
    fresh_model.modelId = "owner/m"
    fresh_model.lastModified = datetime.now(timezone.utc)
    fresh_model.id = "owner/m"
    with patch.object(pollers.HfApi, "list_models", return_value=[fresh_model]) as m:
        pollers.poll_hf_models(since)
    call = m.call_args
    assert "direction" not in call.kwargs


# --- since-as-ISO-string (regression for Cloud Run smoke bug) ---------------


def test_pollers_accept_since_as_iso_string():
    """The LlmAgent serializes `since` to ISO 8601 over JSON. All pollers
    must accept that shape. Regression for the production bug:
    ``'<=' not supported between instances of 'datetime' and 'str'``.
    """
    iso = "2025-05-13T09:00:00Z"
    fresh = MagicMock(
        title="t", entry_id="https://arxiv.org/abs/x",
        published=datetime.now(timezone.utc), summary="s",
    )
    with patch.object(pollers.arxiv, "Client") as mc, \
         patch.object(pollers.arxiv, "Search"):
        mc.return_value.results.return_value = iter([fresh])
        out = pollers.poll_arxiv(iso)
    assert len(out) == 1

    fresh_rss = _rss_entry(datetime.now(timezone.utc) + timedelta(seconds=30))
    with patch.object(pollers.feedparser, "parse",
                      return_value=MagicMock(entries=[fresh_rss])):
        out = pollers.poll_rss(iso)
    assert len(out) == len(pollers.RSS_FEEDS)

    fresh_hf = MagicMock()
    fresh_hf.modelId = "o/m"
    fresh_hf.lastModified = datetime.now(timezone.utc)
    fresh_hf.id = "o/m"
    with patch.object(pollers.HfApi, "list_models", return_value=[fresh_hf]):
        out = pollers.poll_hf_models(iso)
    assert len(out) == 1


def test_parse_since_rejects_unparseable_string():
    import pytest as _pytest
    with _pytest.raises(ValueError):
        pollers._parse_since("not-a-date")


# --- poll_hf_papers ---------------------------------------------------------


def test_poll_hf_papers_returns_candidates(since):
    payload = [
        {
            "paper": {
                "id": "2501.12345",
                "title": "A Test Paper on Foo",
                "summary": "Summary.",
                "publishedAt": datetime.now(timezone.utc).isoformat(),
            },
        },
    ]
    body = MagicMock()
    body.read.return_value = __import__("json").dumps(payload).encode("utf-8")
    body.__enter__ = MagicMock(return_value=body)
    body.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=body):
        results = pollers.poll_hf_papers(since)
    assert len(results) == 1
    assert results[0]["source"] == "huggingface_papers"
    assert results[0]["url"] == "https://huggingface.co/papers/2501.12345"


def test_poll_hf_papers_returns_empty_on_failure(since):
    with patch("urllib.request.urlopen", side_effect=RuntimeError("dns")):
        assert pollers.poll_hf_papers(since) == []


# --- poll_hackernews_ai -----------------------------------------------------


def test_poll_hackernews_ai_returns_candidates(since):
    now_ts = int(datetime.now(timezone.utc).timestamp())
    payload = {
        "hits": [
            {
                "objectID": "111",
                "title": "Show HN: My AI Agent",
                "url": "https://example.com/post",
                "created_at_i": now_ts,
                "points": 42,
                "num_comments": 7,
            },
        ],
    }
    body = MagicMock()
    body.read.return_value = __import__("json").dumps(payload).encode("utf-8")
    body.__enter__ = MagicMock(return_value=body)
    body.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=body):
        results = pollers.poll_hackernews_ai(since)
    assert len(results) == 1
    assert results[0]["source"] == "hackernews"
    assert results[0]["url"] == "https://example.com/post"


def test_poll_hackernews_ai_falls_back_to_thread_url_for_self_posts(since):
    payload = {
        "hits": [{
            "objectID": "999",
            "title": "Ask HN: best agent framework?",
            "url": None,
            "created_at_i": int(datetime.now(timezone.utc).timestamp()),
        }],
    }
    body = MagicMock()
    body.read.return_value = __import__("json").dumps(payload).encode("utf-8")
    body.__enter__ = MagicMock(return_value=body)
    body.__exit__ = MagicMock(return_value=False)
    with patch("urllib.request.urlopen", return_value=body):
        results = pollers.poll_hackernews_ai(since)
    assert results[0]["url"] == "https://news.ycombinator.com/item?id=999"


def test_poll_hackernews_ai_returns_empty_on_failure(since):
    with patch("urllib.request.urlopen", side_effect=RuntimeError("net")):
        assert pollers.poll_hackernews_ai(since) == []


# --- poll_anthropic_news ----------------------------------------------------


def test_poll_anthropic_news_extracts_articles(since):
    html = """
    <a href="/news/claude-opus-4-7" class="card">post</a>
    <a href="/news/anthropic-amazon-compute" class="card">post</a>
    <a href="/news/claude-opus-4-7" class="card">duplicate (should dedupe)</a>
    """
    with patch("urllib.request.urlopen",
               return_value=_mock_urlopen_response(html)):
        results = pollers.poll_anthropic_news(since)
    assert len(results) == 2
    titles = {r["title"] for r in results}
    assert "Claude Opus 4 7" in titles
    assert "Anthropic Amazon Compute" in titles
    assert all(r["source"] == "anthropic" for r in results)
    assert all(r["url"].startswith("https://www.anthropic.com/news/") for r in results)


def test_poll_anthropic_news_returns_empty_on_failure(since):
    with patch("urllib.request.urlopen", side_effect=RuntimeError("dns")):
        assert pollers.poll_anthropic_news(since) == []


# --- Scout agent wiring ------------------------------------------------------


def test_scout_agent_wires_all_pollers():
    from agents.scout.agent import scout

    assert scout.name == "scout"
    assert scout.model == "gemini-3.1-flash-lite-preview"
    tool_names = {getattr(t, "__name__", str(t)) for t in scout.tools}
    assert tool_names == {
        "poll_arxiv",
        "poll_github_trending",
        "poll_rss",
        "poll_hf_models",
        "poll_hf_papers",
        "poll_hackernews_ai",
        "poll_anthropic_news",
    }
    assert scout.output_key == "candidates"


def test_scout_agent_instruction_loaded_verbatim_from_prompts():
    from agents.scout.agent import scout
    from shared.prompts import SCOUT_INSTRUCTION

    assert scout.instruction == SCOUT_INSTRUCTION
    assert "Scout" in scout.instruction
    assert 'state["candidates"]' in scout.instruction


# --- Scout state["candidates"] population ------------------------------------


def test_scout_candidates_state_populated_from_pollers(since):
    """The four pollers, when patched, produce a merged Candidate list of
    the shape Scout's instruction commits to writing into ``state["candidates"]``.

    This bypasses the LlmAgent.run() loop (which would call Gemini) and
    asserts the polling-layer contract the agent depends on.
    """
    fake_arxiv = [Candidate(
        title="arxiv-paper",
        url="https://arxiv.org/abs/x",
        source="arxiv",
        published_at=datetime.now(timezone.utc),
        raw_summary="x",
    )]
    fake_gh = [Candidate(
        title="o/r",
        url="https://github.com/o/r",
        source="github",
        published_at=datetime.now(timezone.utc),
        raw_summary="x",
    )]
    fake_rss = [Candidate(
        title="rss-post",
        url="https://example.com/p",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="x",
    )]
    fake_hf = [Candidate(
        title="o/m",
        url="https://huggingface.co/o/m",
        source="huggingface",
        published_at=datetime.now(timezone.utc),
        raw_summary="x",
    )]

    with patch.object(pollers, "poll_arxiv", return_value=fake_arxiv), \
         patch.object(pollers, "poll_github_trending", return_value=fake_gh), \
         patch.object(pollers, "poll_rss", return_value=fake_rss), \
         patch.object(pollers, "poll_hf_models", return_value=fake_hf):

        state: dict = {}
        merged: list[Candidate] = []
        merged.extend(pollers.poll_arxiv(since))
        merged.extend(pollers.poll_github_trending(since))
        merged.extend(pollers.poll_rss(since))
        merged.extend(pollers.poll_hf_models(since))
        state["candidates"] = merged

    assert "candidates" in state
    assert len(state["candidates"]) == 4
    assert {c.source for c in state["candidates"]} == {
        "arxiv", "github", "anthropic", "huggingface"
    }
    assert all(isinstance(c, Candidate) for c in state["candidates"])
