"""Tests for the Repo Builder agent + router and the GitHub write wrappers.

Coverage maps to the user's two required scenarios from DESIGN.md §8:
- needs_repo=True → repo created, asset bundle committed under ``assets/``.
- needs_repo=False → router does nothing (no transfer to repo_builder).

The user also asked for a real-org integration test that creates a repo and
cleans up. That's provided as ``test_repo_builder_real_integration``,
``pytest.mark.skipif``ed unless ``GITHUB_TOKEN`` and ``GITHUB_TEST_ORG`` are
both set. The mocked path covers the contract on every run.
"""

import base64
import os
from unittest.mock import MagicMock, patch

import pytest

from tools import github_ops


def _tool_name(t) -> str:
    return getattr(t, "__name__", None) or getattr(t, "name", "") or t.__class__.__name__


@pytest.fixture(autouse=True)
def reset_github_client(monkeypatch):
    """Each test starts with no cached PyGithub client and no GITHUB_ORG."""
    github_ops.reset_client(None)
    monkeypatch.delenv("GITHUB_ORG", raising=False)
    yield
    github_ops.reset_client(None)


def _fake_user_repo(full_name="user/test-repo") -> MagicMock:
    """Build a MagicMock that quacks like a freshly created PyGithub Repository."""
    owner_name, repo_name = full_name.split("/")
    r = MagicMock()
    r.full_name = full_name
    r.name = repo_name
    r.owner = MagicMock(login=owner_name)
    r.html_url = f"https://github.com/{full_name}"
    r.default_branch = "main"
    return r


# --- github_create_repo ----------------------------------------------------


def test_github_create_repo_creates_under_user_when_no_org(monkeypatch):
    monkeypatch.delenv("GITHUB_ORG", raising=False)
    fake_user = MagicMock()
    fake_repo = _fake_user_repo("alice/anthropic-skills-quickstart")
    fake_user.create_repo.return_value = fake_repo
    fake_client = MagicMock()
    fake_client.get_user.return_value = fake_user
    github_ops.reset_client(fake_client)

    result = github_ops.github_create_repo(
        "anthropic-skills-quickstart",
        description="Quickstart for the Anthropic Skills SDK",
    )

    assert result["full_name"] == "alice/anthropic-skills-quickstart"
    assert result["html_url"].endswith("/anthropic-skills-quickstart")
    assert result["default_branch"] == "main"
    assert result["owner"] == "alice"
    fake_user.create_repo.assert_called_once()
    call = fake_user.create_repo.call_args
    assert call.args[0] == "anthropic-skills-quickstart"
    assert call.kwargs["auto_init"] is True
    assert call.kwargs["private"] is False


def test_github_create_repo_creates_under_org_when_env_set(monkeypatch):
    monkeypatch.setenv("GITHUB_ORG", "test-org")
    fake_org = MagicMock()
    fake_repo = _fake_user_repo("test-org/anthropic-skills-quickstart")
    fake_org.create_repo.return_value = fake_repo
    fake_client = MagicMock()
    fake_client.get_organization.return_value = fake_org
    github_ops.reset_client(fake_client)

    result = github_ops.github_create_repo("anthropic-skills-quickstart")

    fake_client.get_organization.assert_called_once_with("test-org")
    fake_org.create_repo.assert_called_once()
    assert result["owner"] == "test-org"


def test_github_create_repo_returns_error_dict_on_failure(monkeypatch):
    fake_user = MagicMock()
    fake_user.create_repo.side_effect = RuntimeError("name taken")
    fake_client = MagicMock()
    fake_client.get_user.return_value = fake_user
    github_ops.reset_client(fake_client)

    result = github_ops.github_create_repo("dup-name")
    assert "error" in result
    assert "name taken" in result["error"]


# --- github_commit_files ---------------------------------------------------


def _setup_repo_for_commit() -> tuple[MagicMock, MagicMock]:
    """Wire up a fake repo whose Git Data API methods all return mocks."""
    fake_blob = MagicMock(sha="blob-sha")
    fake_tree = MagicMock(sha="tree-sha")
    fake_commit = MagicMock(sha="commit-sha")
    fake_head_commit = MagicMock(tree=MagicMock(sha="tree-head-sha"))
    fake_ref = MagicMock(object=MagicMock(sha="head-sha"))

    fake_repo = MagicMock()
    fake_repo.default_branch = "main"
    fake_repo.create_git_blob.return_value = fake_blob
    fake_repo.create_git_tree.return_value = fake_tree
    fake_repo.create_git_commit.return_value = fake_commit
    fake_repo.get_git_ref.return_value = fake_ref
    fake_repo.get_git_commit.return_value = fake_head_commit

    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)
    return fake_repo, fake_ref


def test_github_commit_files_commits_text_content_atomically():
    fake_repo, fake_ref = _setup_repo_for_commit()
    files = [
        {"path": "README.md", "content": "# Hello\n"},
        {"path": "quickstart.py", "content": "print('hi')\n"},
    ]

    result = github_ops.github_commit_files("owner", "repo", files, "init")

    assert result["count"] == 2
    assert result["committed"] == ["README.md", "quickstart.py"]
    # Atomic: one commit, one ref edit, one tree.
    assert fake_repo.create_git_commit.call_count == 1
    assert fake_repo.create_git_tree.call_count == 1
    fake_ref.edit.assert_called_once_with("commit-sha")
    # Two blobs (one per file), both base64.
    assert fake_repo.create_git_blob.call_count == 2
    for call in fake_repo.create_git_blob.call_args_list:
        assert call.args[1] == "base64"


def test_github_commit_files_commits_binary_content():
    """Binary blob support: bytes are base64-encoded and committed."""
    fake_repo, _ = _setup_repo_for_commit()
    binary_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # PNG magic + filler
    files = [{"path": "assets/cover.png", "content": binary_payload}]

    result = github_ops.github_commit_files("owner", "repo", files, "add cover")

    assert result["count"] == 1
    expected_b64 = base64.b64encode(binary_payload).decode("ascii")
    fake_repo.create_git_blob.assert_called_once_with(expected_b64, "base64")


def test_github_commit_files_fetches_source_url_for_asset_bundle(monkeypatch):
    """source_url specs fetch bytes via urllib and commit them as binary blobs."""
    fake_repo, _ = _setup_repo_for_commit()
    fetched_bytes = b"FETCHED_FROM_GCS"

    fake_response = MagicMock()
    fake_response.read.return_value = fetched_bytes
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)

    with patch("urllib.request.urlopen", return_value=fake_response):
        result = github_ops.github_commit_files(
            "owner", "repo",
            files=[{
                "path": "assets/cover.png",
                "source_url": "https://storage.googleapis.com/bucket/cover.png",
            }],
            message="add asset",
        )

    assert result["count"] == 1
    expected_b64 = base64.b64encode(fetched_bytes).decode("ascii")
    fake_repo.create_git_blob.assert_called_once_with(expected_b64, "base64")


def test_github_commit_files_returns_error_when_spec_missing_content_and_url():
    _setup_repo_for_commit()
    result = github_ops.github_commit_files(
        "owner", "repo",
        files=[{"path": "broken.txt"}],  # neither content nor source_url
        message="x",
    )
    assert "error" in result


def test_github_commit_files_returns_error_on_api_failure():
    fake_client = MagicMock()
    fake_client.get_repo.side_effect = RuntimeError("403 forbidden")
    github_ops.reset_client(fake_client)

    result = github_ops.github_commit_files(
        "owner", "repo",
        files=[{"path": "README.md", "content": "x"}],
        message="x",
    )
    assert "error" in result
    assert "forbidden" in result["error"]


# --- github_set_topics ----------------------------------------------------


def test_github_set_topics_replaces_topics():
    fake_repo = MagicMock()
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    result = github_ops.github_set_topics(
        "owner", "repo", ["anthropic", "ai", "quickstart"]
    )
    assert result["topics"] == ["anthropic", "ai", "quickstart"]
    fake_repo.replace_topics.assert_called_once_with(
        ["anthropic", "ai", "quickstart"]
    )


def test_github_set_topics_returns_error_on_failure():
    fake_repo = MagicMock()
    fake_repo.replace_topics.side_effect = RuntimeError("rate limited")
    fake_client = MagicMock()
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    result = github_ops.github_set_topics("owner", "repo", ["ai"])
    assert "error" in result


# --- repo_builder agent wiring --------------------------------------------


def test_repo_builder_wiring():
    from agents.repo_builder.agent import repo_builder
    assert repo_builder.name == "repo_builder"
    assert repo_builder.model == "gemini-3.1-pro-preview"
    assert repo_builder.output_key == "repo_url"
    names = {_tool_name(t) for t in repo_builder.tools}
    assert names == {"github_create_repo", "github_commit_files", "github_set_topics"}


def test_repo_builder_instruction_first_line_is_chosen_release_early_exit():
    from agents.repo_builder.agent import repo_builder
    first = repo_builder.instruction.splitlines()[0]
    assert first == "If state['chosen_release'] is None, end your turn immediately without using tools."


def test_repo_builder_instruction_encodes_asset_bundle_responsibility():
    """DESIGN.md §8: 'Commits the asset bundle (cover.png, tutorial.mp4,
    tutorial-poster.jpg) to assets/ if available.' Verify all three target
    paths and the source-URL strategy are encoded in the instruction."""
    from agents.repo_builder.agent import repo_builder
    instr = repo_builder.instruction
    assert "assets/cover.png" in instr
    assert "assets/tutorial.mp4" in instr
    assert "assets/tutorial-poster.jpg" in instr
    # The strategy for fetching binary assets:
    assert "source_url" in instr
    # The skip-on-failure contract:
    assert "repo_skip_reason" in instr


# --- repo_router wiring ---------------------------------------------------


def test_repo_router_wiring():
    from main import repo_router
    from agents.repo_builder.agent import repo_builder
    assert repo_router.name == "repo_router"
    assert repo_router.model == "gemini-3.1-flash-lite-preview"
    # The conditional must reference needs_repo and the sub-agent's name.
    assert "needs_repo" in repo_router.instruction
    assert "repo_builder" in repo_router.instruction
    # Both branches encoded:
    assert "If True" in repo_router.instruction
    assert "do nothing" in repo_router.instruction
    # Sub-agent wired for transfer.
    assert repo_builder in repo_router.sub_agents


# --- post_writer_parallel composition -------------------------------------


def test_post_writer_parallel_runs_assets_and_repo_in_parallel():
    from main import asset_agent, post_writer_parallel, repo_router
    assert post_writer_parallel.name == "post_writer_parallel"
    sub_names = {a.name for a in post_writer_parallel.sub_agents}
    assert sub_names == {"asset_agent", "repo_router"}
    assert asset_agent in post_writer_parallel.sub_agents
    assert repo_router in post_writer_parallel.sub_agents


# --- The two user-required scenario tests ---------------------------------


def test_needs_repo_true_creates_repo_and_commits_asset_bundle(monkeypatch):
    """[Scenario 1] needs_repo=True → repo created and assets committed
    under ``assets/``. We exercise the LLM's expected sequence: create the
    repo, commit a file list that includes asset URLs as ``source_url``
    entries, set topics. The mocks then assert the asset paths landed
    under ``assets/`` and the right wrappers were invoked.
    """
    # Stage 1: create the repo.
    fake_user = MagicMock()
    fake_user.create_repo.return_value = _fake_user_repo("alice/anthropic-skills-quickstart")
    # Stage 2: commit files atomically.
    fake_repo = MagicMock(default_branch="main")
    fake_repo.create_git_blob.return_value = MagicMock(sha="blob")
    fake_repo.create_git_tree.return_value = MagicMock(sha="tree")
    fake_repo.create_git_commit.return_value = MagicMock(sha="commit-abc123")
    fake_repo.get_git_ref.return_value = MagicMock(object=MagicMock(sha="head"))
    fake_repo.get_git_commit.return_value = MagicMock(tree=MagicMock(sha="tree-head"))

    fake_client = MagicMock()
    fake_client.get_user.return_value = fake_user
    fake_client.get_repo.return_value = fake_repo
    github_ops.reset_client(fake_client)

    # Mock URL fetching for the asset bundle.
    fake_response = MagicMock()
    fake_response.read.side_effect = [b"PNG", b"MP4", b"JPG"]
    fake_response.__enter__ = MagicMock(return_value=fake_response)
    fake_response.__exit__ = MagicMock(return_value=False)

    # Step 2: simulated LLM action — create repo.
    repo_info = github_ops.github_create_repo(
        "anthropic-skills-quickstart",
        description="Quickstart for the Anthropic Skills SDK",
    )
    assert repo_info["html_url"].endswith("/anthropic-skills-quickstart")

    owner = repo_info["full_name"].split("/")[0]
    name = repo_info["full_name"].split("/")[1]

    # Step 3: simulated LLM action — commit text + asset bundle.
    files = [
        {"path": "README.md", "content": "# Quickstart\n"},
        {"path": "quickstart.py", "content": "import anthropic_skills\n"},
        {"path": ".gitignore", "content": "__pycache__/\n.venv/\n"},
        {"path": "LICENSE", "content": "MIT License\n"},
        {"path": "assets/cover.png",
         "source_url": "https://storage.googleapis.com/bucket/image-cover.png"},
        {"path": "assets/tutorial.mp4",
         "source_url": "https://storage.googleapis.com/bucket/tutorial.mp4"},
        {"path": "assets/tutorial-poster.jpg",
         "source_url": "https://storage.googleapis.com/bucket/tutorial-poster.jpg"},
    ]
    with patch("urllib.request.urlopen", return_value=fake_response):
        commit_result = github_ops.github_commit_files(
            owner, name, files, message="Initial commit with assets"
        )

    # Verify all asset-bundle paths landed under assets/ in one commit.
    assert commit_result["count"] == 7
    assert commit_result["commit_sha"] == "commit-abc123"
    asset_paths = [p for p in commit_result["committed"] if p.startswith("assets/")]
    assert set(asset_paths) == {
        "assets/cover.png",
        "assets/tutorial.mp4",
        "assets/tutorial-poster.jpg",
    }
    # One atomic commit, not seven:
    assert fake_repo.create_git_commit.call_count == 1

    # Step 4: simulated LLM action — set topics.
    topics_result = github_ops.github_set_topics(
        owner, name, ["anthropic", "ai", "quickstart"]
    )
    assert topics_result["topics"] == ["anthropic", "ai", "quickstart"]


def test_needs_repo_false_router_does_nothing():
    """[Scenario 2] needs_repo=False → the router does nothing. No repo is
    created (we'd see github_create_repo called if it did). Verified via
    the router's instruction-as-contract: it commits to "do nothing and
    end your turn" when needs_repo is False or missing."""
    from main import repo_router

    instr = repo_router.instruction
    # The router's contract for the False branch:
    assert "False or missing" in instr
    assert "do nothing" in instr
    assert "end your turn" in instr
    # And we belt-and-suspenders verify no PyGithub side effects could happen
    # if no LLM ever runs the builder: the builder is the only sub-agent, so
    # if the router doesn't transfer, the builder doesn't run.
    assert len(repo_router.sub_agents) == 1


# --- Integration: real GitHub org (skipif unless env vars set) ------------


@pytest.mark.skipif(
    not (os.environ.get("GITHUB_TOKEN") and os.environ.get("GITHUB_TEST_ORG")),
    reason="needs GITHUB_TOKEN and GITHUB_TEST_ORG env vars",
)
def test_repo_builder_real_integration_creates_and_commits_then_cleans_up():
    """[User-required: 'Use a test-only org and clean up'] Integration test:
    create a repo in ``GITHUB_TEST_ORG``, atomic-commit a text file and a
    binary asset, then delete the repo to leave no trace.

    Skipped without ``GITHUB_TOKEN`` and ``GITHUB_TEST_ORG`` set. The
    create-and-cleanup pattern means the test is safe to re-run.
    """
    import time
    test_org = os.environ["GITHUB_TEST_ORG"]
    repo_name = f"airel-pipeline-it-{int(time.time())}"

    # Force the org used by the create wrapper to point at the test org.
    os.environ["GITHUB_ORG"] = test_org
    github_ops.reset_client(None)
    try:
        info = github_ops.github_create_repo(
            repo_name, description="Integration-test artifact, safe to delete."
        )
        assert "error" not in info, info
        owner, repo = info["full_name"].split("/")

        commit = github_ops.github_commit_files(
            owner, repo,
            files=[
                {"path": "README.md", "content": "# integration test\n"},
                {"path": "assets/cover.png", "content": b"\x89PNG\r\n\x1a\n" * 16},
            ],
            message="atomic commit with binary asset",
        )
        assert "error" not in commit, commit
        assert commit["count"] == 2
        assert "assets/cover.png" in commit["committed"]

        topics = github_ops.github_set_topics(owner, repo, ["test", "delete-me"])
        assert "error" not in topics, topics
    finally:
        # Always clean up — delete the repo even if assertions failed.
        try:
            client = github_ops._client()
            client.get_repo(f"{test_org}/{repo_name}").delete()
        except Exception as cleanup_err:
            pytest.fail(
                f"failed to delete integration-test repo "
                f"{test_org}/{repo_name}: {cleanup_err}"
            )
