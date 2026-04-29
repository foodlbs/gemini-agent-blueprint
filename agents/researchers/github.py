"""GitHub researcher — fetches the most relevant repo's metadata, README,
and top-level layout. Writes ``state["github_research"]``.

PyGithub usage lives in ``tools/github_ops.py`` rather than this module so
the file basename ``github`` cannot shadow the upstream ``github`` package
on imports.
"""

from google.adk.agents import LlmAgent

from shared.prompts import GITHUB_RESEARCHER_INSTRUCTION
from tools.github_ops import (
    github_get_readme,
    github_get_repo,
    github_list_files,
)


github_researcher = LlmAgent(
    name="github_researcher",
    model="gemini-3.1-flash-lite-preview",
    instruction=GITHUB_RESEARCHER_INSTRUCTION,
    tools=[github_get_repo, github_get_readme, github_list_files],
    output_key="github_research",
)
