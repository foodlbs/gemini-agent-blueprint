"""Repo Builder — creates a GitHub starter repo. See DESIGN.v2.md §6.8.2."""

from google.adk import Agent

from tools.github_ops import (
    github_commit_files,
    github_create_repo,
    github_set_topics,
)


# TODO §6.8.2 — fill in REPO_BUILDER_INSTRUCTION:
#   - Compute repo name: airel-{article_type}-{slug(title)}, ≤100 chars.
#   - Create public repo under GITHUB_ORG.
#   - Compose starter file set: README.md (with image URLs injected),
#     examples/quickstart.{lang}, requirements.txt, .gitignore.
#   - Atomic commit via Git Data API (github_commit_files handles this).
#   - Set topics: source + ai-release-pipeline + article_type.
repo_builder = Agent(
    name="repo_builder",
    model="gemini-3.1-flash",
    instruction=(
        "TODO §6.8.2 — create public repo airel-{article_type}-{slug}, "
        "commit README + examples/quickstart + requirements + .gitignore, "
        "set topics. Emit StarterRepo(url, files_committed, sha)."
    ),
    tools=[github_create_repo, github_commit_files, github_set_topics],
    output_key="starter_repo",
)
