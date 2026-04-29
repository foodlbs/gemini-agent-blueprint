"""GitHub API wrappers used by the GitHub researcher and Repo Builder.

Read wrappers (Step 4): ``github_get_repo``, ``github_get_readme``,
``github_list_files``.

Write wrappers (Step 8): ``github_create_repo``, ``github_commit_files``
(atomic multi-file commit via the Git Data API, with text+binary support
and optional ``source_url`` fetching for asset-bundle blobs), and
``github_set_topics``.

All wrappers degrade to ``{"error": "..."}`` on failure rather than raising
— researchers and the repo builder both fall back gracefully when GitHub
is offline or the target doesn't exist.
"""

import base64
import logging
import os
import urllib.request
from typing import Optional

from github import Github, GithubException
from github.InputGitTreeElement import InputGitTreeElement

logger = logging.getLogger(__name__)

DEFAULT_FILE_LIST_LIMIT = 50
SOURCE_URL_TIMEOUT_SECONDS = 30
SOURCE_URL_USER_AGENT = "ai-release-pipeline-repo-builder/0.1"

_client_singleton: Optional[Github] = None


def _client() -> Github:
    """Lazily build a single Github client. Reads ``GITHUB_TOKEN`` if set."""
    global _client_singleton
    if _client_singleton is None:
        token = os.environ.get("GITHUB_TOKEN")
        _client_singleton = Github(token) if token else Github()
    return _client_singleton


def reset_client(client: Optional[Github] = None) -> None:
    """Test/dev helper: replace or clear the module-level Github client."""
    global _client_singleton
    _client_singleton = client


def github_get_repo(owner: str, repo: str) -> dict:
    """Fetch repository metadata for ``owner/repo`` on GitHub.

    Args:
        owner: Repository owner (user or org login).
        repo: Repository name.

    Returns:
        dict with ``full_name``, ``description``, ``stars``, ``forks``,
        ``language``, ``topics``, ``default_branch``, ``html_url``, and
        ``pushed_at`` (ISO8601). On any error, ``{"error": "..."}``.
    """
    try:
        r = _client().get_repo(f"{owner}/{repo}")
        try:
            topics = list(r.get_topics())
        except GithubException:
            topics = []
        return {
            "full_name": r.full_name,
            "description": r.description or "",
            "stars": r.stargazers_count,
            "forks": r.forks_count,
            "language": r.language or "",
            "topics": topics,
            "default_branch": r.default_branch,
            "html_url": r.html_url,
            "pushed_at": r.pushed_at.isoformat() if r.pushed_at else None,
        }
    except Exception as e:
        logger.warning("github_get_repo(%s/%s) failed: %s", owner, repo, e)
        return {"error": str(e)}


def github_get_readme(owner: str, repo: str) -> dict:
    """Fetch and decode the README for ``owner/repo``.

    Args:
        owner: Repository owner.
        repo: Repository name.

    Returns:
        dict with ``name``, ``content`` (UTF-8 decoded body), and
        ``html_url``. On any error, ``{"error": "..."}``.
    """
    try:
        r = _client().get_repo(f"{owner}/{repo}")
        readme = r.get_readme()
        return {
            "name": readme.name,
            "content": readme.decoded_content.decode("utf-8", errors="replace"),
            "html_url": readme.html_url,
        }
    except Exception as e:
        logger.warning("github_get_readme(%s/%s) failed: %s", owner, repo, e)
        return {"error": str(e)}


def github_list_files(owner: str, repo: str, path: str = "") -> dict:
    """List files and directories at ``path`` in ``owner/repo``.

    Args:
        owner: Repository owner.
        repo: Repository name.
        path: Subpath within the repo. Empty string for the repo root.

    Returns:
        dict with ``files`` — a list of ``{name, path, type, size}``
        entries (``type`` is ``"file"`` or ``"dir"``). Capped at
        ``DEFAULT_FILE_LIST_LIMIT``. On any error, ``{"error": "..."}``.
    """
    try:
        r = _client().get_repo(f"{owner}/{repo}")
        contents = r.get_contents(path)
        if not isinstance(contents, list):
            contents = [contents]
        files = [
            {"name": c.name, "path": c.path, "type": c.type, "size": c.size}
            for c in contents[:DEFAULT_FILE_LIST_LIMIT]
        ]
        return {"files": files}
    except Exception as e:
        logger.warning(
            "github_list_files(%s/%s, %s) failed: %s", owner, repo, path, e
        )
        return {"error": str(e)}


# --- Write wrappers (Step 8) ----------------------------------------------


def github_create_repo(
    name: str,
    description: str = "",
    private: bool = False,
) -> dict:
    """Create a new repository.

    If ``GITHUB_ORG`` is set, the repo is created under that organization;
    otherwise it's created under the authenticated user. The repo is
    auto-initialized with an initial commit so subsequent
    ``github_commit_files`` calls have a base ref to write against.

    Args:
        name: Repo name (kebab-case recommended).
        description: One-line summary used as the repo's description.
        private: True for a private repo. Defaults to False.

    Returns:
        dict with ``full_name``, ``html_url``, ``default_branch``,
        ``owner``, ``name``. On any error, ``{"error": "..."}``.
    """
    try:
        client = _client()
        org_name = os.environ.get("GITHUB_ORG")
        if org_name:
            owner_obj = client.get_organization(org_name)
        else:
            owner_obj = client.get_user()
        r = owner_obj.create_repo(
            name,
            description=description or "",
            private=private,
            auto_init=True,
        )
        return {
            "full_name": r.full_name,
            "html_url": r.html_url,
            "default_branch": r.default_branch,
            "owner": r.owner.login,
            "name": r.name,
        }
    except Exception as e:
        logger.warning("github_create_repo(%s) failed: %s", name, e)
        return {"error": str(e)}


def github_commit_files(
    owner: str,
    repo: str,
    files: list[dict],
    message: str = "Update files",
) -> dict:
    """Commit one or more files to a repo as a single atomic Git commit.

    Each entry in ``files`` is one of:

    - ``{"path": <repo path>, "content": <str or bytes>}`` — inline content.
      ``str`` is encoded as UTF-8; ``bytes`` is committed as a binary blob.
    - ``{"path": <repo path>, "source_url": <https URL>}`` — bytes fetched
      from the URL (used for asset-bundle binaries hosted on GCS) and
      committed as a binary blob.

    Internally uses the Git Data API: one ``create_git_blob`` per file,
    one ``create_git_tree`` rooted on the current HEAD's tree, one
    ``create_git_commit`` parented at HEAD, then ``ref.edit`` to advance
    the default branch. The result is a single, clean commit per call.

    Args:
        owner: Repository owner.
        repo: Repository name.
        files: List of file specs as described above.
        message: Commit message.

    Returns:
        dict with ``commit_sha``, ``committed`` (list of paths), and
        ``count``. On any error, ``{"error": "..."}``.
    """
    try:
        r = _client().get_repo(f"{owner}/{repo}")

        tree_elements = []
        committed_paths = []
        for spec in files:
            path = spec.get("path")
            if not path:
                return {"error": "file spec missing 'path'"}
            content_bytes = _resolve_file_bytes(spec)
            if content_bytes is None:
                return {"error": f"file {path}: missing content or source_url"}

            encoded = base64.b64encode(content_bytes).decode("ascii")
            blob = r.create_git_blob(encoded, "base64")
            tree_elements.append(InputGitTreeElement(
                path=path, mode="100644", type="blob", sha=blob.sha,
            ))
            committed_paths.append(path)

        ref = r.get_git_ref(f"heads/{r.default_branch}")
        head_commit = r.get_git_commit(ref.object.sha)
        new_tree = r.create_git_tree(tree_elements, base_tree=head_commit.tree)
        new_commit = r.create_git_commit(message, new_tree, [head_commit])
        ref.edit(new_commit.sha)

        return {
            "commit_sha": new_commit.sha,
            "committed": committed_paths,
            "count": len(committed_paths),
        }
    except Exception as e:
        logger.warning("github_commit_files(%s/%s) failed: %s", owner, repo, e)
        return {"error": str(e)}


def github_set_topics(owner: str, repo: str, topics: list[str]) -> dict:
    """Replace the repo's topics for discoverability.

    Args:
        owner: Repository owner.
        repo: Repository name.
        topics: List of lowercase topic strings.

    Returns:
        dict with ``topics``. On any error, ``{"error": "..."}``.
    """
    try:
        r = _client().get_repo(f"{owner}/{repo}")
        r.replace_topics(list(topics))
        return {"topics": list(topics)}
    except Exception as e:
        logger.warning("github_set_topics(%s/%s) failed: %s", owner, repo, e)
        return {"error": str(e)}


def _resolve_file_bytes(spec: dict) -> Optional[bytes]:
    """Pull bytes from a file spec's ``content`` or ``source_url``."""
    if "content" in spec:
        content = spec["content"]
        if isinstance(content, str):
            return content.encode("utf-8")
        if isinstance(content, (bytes, bytearray)):
            return bytes(content)
        return None
    if "source_url" in spec:
        return _fetch_url_bytes(spec["source_url"])
    return None


def _fetch_url_bytes(url: str) -> bytes:
    """Fetch raw bytes from an HTTP(S) URL."""
    req = urllib.request.Request(
        url, headers={"User-Agent": SOURCE_URL_USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=SOURCE_URL_TIMEOUT_SECONDS) as resp:
        return resp.read()
