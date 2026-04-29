"""GitHub PAT smoke test: create a private repo, commit a README, delete.

Reads GITHUB_TOKEN and (optionally) GITHUB_ORG from env. Creates a private
test repo, commits one README, then deletes the repo. Confirms the PAT
has the required scopes (repo: full control if private, public_repo if
public; delete_repo).

Exit code 0 = round-trip succeeded.
Exit code 1 = any step failed.
"""

import os
import sys
import time

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from tools import github_ops  # noqa: E402


def main() -> int:
    if not os.environ.get("GITHUB_TOKEN"):
        print("SKIP: GITHUB_TOKEN not set")
        return 0

    repo_name = f"agent-cli-smoke-test-{int(time.time())}"
    org = os.environ.get("GITHUB_ORG", "")

    # Reset the singleton so the env-var-driven token is picked up.
    github_ops.reset_client(None)

    print(f"Creating private repo {org or '<user>'}/{repo_name}...")
    info = github_ops.github_create_repo(
        repo_name,
        description="Smoke test for the AI release pipeline (auto-deleted).",
        private=True,
    )
    if "error" in info:
        print(f"FAIL: github_create_repo: {info['error']}")
        return 1
    print(f"Created: {info['html_url']}")
    owner, name = info["full_name"].split("/")

    try:
        commit = github_ops.github_commit_files(
            owner, name,
            files=[{"path": "README.md", "content": "# smoke test\n"}],
            message="initial commit",
        )
        if "error" in commit:
            print(f"FAIL: github_commit_files: {commit['error']}")
            return 1
        print(f"Committed: {commit['committed']} (sha={commit['commit_sha']})")
    finally:
        # Always try to delete, even if commit failed.
        try:
            client = github_ops._client()
            client.get_repo(info["full_name"]).delete()
            print(f"Deleted: {info['full_name']}")
        except Exception as e:
            print(f"WARN: delete failed (manual cleanup needed): {e}")
            return 1

    print("OK: GitHub PAT round-trip succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
