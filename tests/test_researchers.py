"""Tests for the Researcher pool: web_fetch, github_ops, the three
``LlmAgent`` wirings, and the ``ParallelAgent`` composition.

Coverage maps to the user's two required scenarios:
- chosen_release fixture → all three sub-agents are wired to populate their
  respective state keys (``docs_research``, ``github_research``, ``context_research``).
- chosen_release=None → all three instructions begin with the early-exit line.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from shared.models import ChosenRelease
from tools import github_ops, web


def _tool_name(t) -> str:
    """Return a tool's identifying name (works for functions and Tool instances)."""
    return getattr(t, "__name__", None) or getattr(t, "name", "") or t.__class__.__name__


@pytest.fixture
def chosen_release() -> ChosenRelease:
    return ChosenRelease(
        title="Anthropic Skills",
        url="https://github.com/anthropic/skills",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="A new SDK that ships agent capabilities as importable bundles.",
        score=85,
        rationale="Major lab + new SDK + working code = high score.",
        top_alternatives=[],
    )


# --- web_fetch -------------------------------------------------------------


def _mock_urlopen_response(body: bytes, status: int = 200) -> MagicMock:
    response = MagicMock()
    # Mirror urllib's HTTPResponse.read(n): return at most n bytes from the body.
    response.read.side_effect = lambda n=None: body if n is None else body[:n]
    response.status = status
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_web_fetch_returns_decoded_body_on_success():
    body = b"<html><body>release notes</body></html>"
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(body)):
        result = web.web_fetch("https://example.com/release")
    assert result["status"] == 200
    assert result["error"] is None
    assert "release notes" in result["content"]


def test_web_fetch_truncates_to_max_bytes():
    body = b"x" * (web.MAX_BYTES + 5_000)
    with patch("urllib.request.urlopen", return_value=_mock_urlopen_response(body)):
        result = web.web_fetch("https://example.com/big")
    assert len(result["content"]) <= web.MAX_BYTES


def test_web_fetch_returns_error_on_network_failure():
    with patch("urllib.request.urlopen", side_effect=RuntimeError("dns down")):
        result = web.web_fetch("https://nope.example.com")
    assert result["status"] == 0
    assert result["content"] == ""
    assert "dns down" in result["error"]


# --- github_ops: read wrappers --------------------------------------------


def _fake_repo(**overrides):
    """Build a MagicMock that quacks like a PyGithub Repository."""
    repo = MagicMock()
    repo.full_name = overrides.get("full_name", "owner/repo")
    repo.description = overrides.get("description", "A test repo")
    repo.stargazers_count = overrides.get("stars", 100)
    repo.forks_count = overrides.get("forks", 10)
    repo.language = overrides.get("language", "Python")
    repo.default_branch = overrides.get("default_branch", "main")
    repo.html_url = overrides.get("html_url", "https://github.com/owner/repo")
    repo.pushed_at = overrides.get("pushed_at", datetime(2026, 4, 22, tzinfo=timezone.utc))
    repo.get_topics.return_value = overrides.get("topics", ["ai", "sdk"])
    return repo


@pytest.fixture(autouse=True)
def reset_github_client():
    """Each test starts with a fresh module-level GitHub client."""
    github_ops.reset_client(None)
    yield
    github_ops.reset_client(None)


def test_github_get_repo_returns_metadata():
    fake = _fake_repo()
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake
    github_ops.reset_client(fake_client)

    result = github_ops.github_get_repo("owner", "repo")

    assert result["full_name"] == "owner/repo"
    assert result["stars"] == 100
    assert result["language"] == "Python"
    assert result["topics"] == ["ai", "sdk"]
    assert result["default_branch"] == "main"
    assert "pushed_at" in result


def test_github_get_repo_returns_error_on_failure():
    fake_client = MagicMock()
    fake_client.get_repo.side_effect = RuntimeError("404 not found")
    github_ops.reset_client(fake_client)

    result = github_ops.github_get_repo("owner", "missing")
    assert "error" in result
    assert "not found" in result["error"]


def test_github_get_readme_returns_decoded_content():
    fake_readme = MagicMock()
    fake_readme.name = "README.md"
    fake_readme.decoded_content = b"# Project\n\nWelcome."
    fake_readme.html_url = "https://github.com/owner/repo/blob/main/README.md"
    fake_repo = MagicMock()
    fake_repo.get_readme.return_value = fake_readme
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    result = github_ops.github_get_readme("owner", "repo")
    assert result["name"] == "README.md"
    assert "Welcome" in result["content"]
    assert result["html_url"].endswith("README.md")


def test_github_get_readme_returns_error_on_failure():
    fake_repo = MagicMock()
    fake_repo.get_readme.side_effect = RuntimeError("no README")
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    result = github_ops.github_get_readme("owner", "repo")
    assert "error" in result
    assert "no README" in result["error"]


def test_github_list_files_returns_top_level_layout():
    file_a = MagicMock(name="a", path="a.py", type="file", size=120)
    file_a.name = "a.py"  # MagicMock(name=...) is special — re-set explicitly
    file_b = MagicMock()
    file_b.name = "src"
    file_b.path = "src"
    file_b.type = "dir"
    file_b.size = 0
    fake_repo = MagicMock()
    fake_repo.get_contents.return_value = [file_a, file_b]
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    result = github_ops.github_list_files("owner", "repo")
    assert len(result["files"]) == 2
    names = {f["name"] for f in result["files"]}
    assert names == {"a.py", "src"}


def test_github_list_files_handles_single_file_response():
    """get_contents returns a single object (not a list) when path is a file."""
    one_file = MagicMock()
    one_file.name = "README.md"
    one_file.path = "README.md"
    one_file.type = "file"
    one_file.size = 200
    fake_repo = MagicMock()
    fake_repo.get_contents.return_value = one_file  # not a list
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    result = github_ops.github_list_files("owner", "repo", "README.md")
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "README.md"


def test_github_list_files_returns_error_on_failure():
    fake_client = MagicMock()
    fake_client.get_repo.side_effect = RuntimeError("rate limited")
    github_ops.reset_client(fake_client)

    result = github_ops.github_list_files("owner", "repo")
    assert "error" in result


# --- Researcher agent wirings ---------------------------------------------


def test_docs_researcher_wired_with_web_fetch_and_google_search():
    from agents.researchers.docs import docs_researcher
    assert docs_researcher.name == "docs_researcher"
    assert docs_researcher.model == "gemini-3.1-flash-lite-preview"
    assert docs_researcher.output_key == "docs_research"
    names = {_tool_name(t) for t in docs_researcher.tools}
    assert "web_fetch" in names
    assert "google_search" in names


def test_github_researcher_wired_with_three_pygithub_wrappers():
    from agents.researchers.github import github_researcher
    assert github_researcher.name == "github_researcher"
    assert github_researcher.model == "gemini-3.1-flash-lite-preview"
    assert github_researcher.output_key == "github_research"
    names = {_tool_name(t) for t in github_researcher.tools}
    assert names == {"github_get_repo", "github_get_readme", "github_list_files"}


def test_context_researcher_wired_with_only_google_search():
    from agents.researchers.context import context_researcher
    assert context_researcher.name == "context_researcher"
    assert context_researcher.model == "gemini-3.1-flash-lite-preview"
    assert context_researcher.output_key == "context_research"
    names = {_tool_name(t) for t in context_researcher.tools}
    assert names == {"google_search"}


# --- Per-instruction early-exit line --------------------------------------


def test_each_researcher_instruction_starts_with_early_exit_line():
    """[User-required scenario 2] When state['chosen_release'] is None,
    every researcher must exit immediately. Verified by asserting the
    DESIGN.md preamble is the first line of every researcher's prompt."""
    from agents.researchers.context import context_researcher
    from agents.researchers.docs import docs_researcher
    from agents.researchers.github import github_researcher

    expected_first_line = (
        "If state['chosen_release'] is None, end your turn immediately without using tools."
    )
    for agent in (docs_researcher, github_researcher, context_researcher):
        first_line = agent.instruction.splitlines()[0]
        assert first_line == expected_first_line, (
            f"{agent.name} first line was {first_line!r}"
        )


# --- ParallelAgent composition --------------------------------------------


def test_researcher_pool_composes_all_three_sub_agents():
    from main import researcher_pool
    from agents.researchers.context import context_researcher
    from agents.researchers.docs import docs_researcher
    from agents.researchers.github import github_researcher

    assert researcher_pool.name == "researcher_pool"
    sub_names = {a.name for a in researcher_pool.sub_agents}
    assert sub_names == {"docs_researcher", "github_researcher", "context_researcher"}
    # Identity check — same instances, no accidental rebuilds:
    assert docs_researcher in researcher_pool.sub_agents
    assert github_researcher in researcher_pool.sub_agents
    assert context_researcher in researcher_pool.sub_agents


def test_researcher_pool_sub_agents_write_disjoint_state_keys():
    """[User-required scenario 1] Given a chosen_release, the three
    sub-agents are configured to populate three distinct state keys.
    Disjoint output_keys mean ParallelAgent's state merge is conflict-free.
    """
    from main import researcher_pool

    output_keys = [
        getattr(a, "output_key", None) for a in researcher_pool.sub_agents
    ]
    assert sorted(output_keys) == sorted([
        "docs_research", "github_research", "context_research",
    ])
    # No duplicates — parallel writes wouldn't collide.
    assert len(set(output_keys)) == len(output_keys)
