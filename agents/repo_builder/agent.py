"""Repo Builder — creates a curated starter repo for quickstart articles.

DESIGN.md §8: Gemini 3.1 Pro, three tools (``github_create_repo``,
``github_commit_files``, ``github_set_topics``). Wrapped behind the
``repo_router`` agent that only transfers control when ``state["needs_repo"]``
is True. Commits the article's quickstart code, README, license, and the
asset bundle (``assets/cover.png``, ``assets/tutorial.mp4``,
``assets/tutorial-poster.jpg``) when the URLs are available in state.
"""

from google.adk.agents import LlmAgent

from shared.prompts import REPO_BUILDER_INSTRUCTION
from tools.github_ops import (
    github_commit_files,
    github_create_repo,
    github_set_topics,
)


repo_builder = LlmAgent(
    name="repo_builder",
    model="gemini-3.1-pro-preview",
    instruction=REPO_BUILDER_INSTRUCTION,
    tools=[github_create_repo, github_commit_files, github_set_topics],
    output_key="repo_url",
)
