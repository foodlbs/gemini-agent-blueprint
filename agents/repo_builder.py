"""Repo Builder — creates a GitHub starter repo. See DESIGN.v2.md §6.8.2."""

from google.adk import Agent

from shared.prompts import REPO_BUILDER_INSTRUCTION
from tools.github_ops import (
    github_commit_files,
    github_create_repo,
    github_set_topics,
)


repo_builder = Agent(
    name="repo_builder",
    model="gemini-3.1-flash",
    instruction=REPO_BUILDER_INSTRUCTION,
    tools=[github_create_repo, github_commit_files, github_set_topics],
    output_key="starter_repo",
)
