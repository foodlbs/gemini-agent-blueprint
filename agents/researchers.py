"""Three parallel researchers — docs, github, context. See DESIGN.v2.md §6.4."""

from google.adk import Agent

from shared.prompts import (
    CONTEXT_RESEARCHER_INSTRUCTION,
    DOCS_RESEARCHER_INSTRUCTION,
    GITHUB_RESEARCHER_INSTRUCTION,
)
from tools.github_ops import github_get_readme, github_get_repo, github_list_files
from tools.web import web_fetch

# `google_search` is the ADK-built-in tool. Only docs_researcher and
# context_researcher use it.
try:
    from google.adk.tools import google_search
    _SEARCH_TOOL = [google_search]
except ImportError:
    _SEARCH_TOOL = []  # ADK 2.0 may rename this; safe fallback.


docs_researcher = Agent(
    name="docs_researcher",
    model="gemini-3.1-flash",
    instruction=DOCS_RESEARCHER_INSTRUCTION,
    tools=[web_fetch, *_SEARCH_TOOL],
    output_key="docs_research",
)


github_researcher = Agent(
    name="github_researcher",
    model="gemini-3.1-flash-lite-preview",
    instruction=GITHUB_RESEARCHER_INSTRUCTION,
    tools=[github_get_repo, github_get_readme, github_list_files],
    output_key="github_research",
)


context_researcher = Agent(
    name="context_researcher",
    model="gemini-3.1-flash",
    instruction=CONTEXT_RESEARCHER_INSTRUCTION,
    tools=[web_fetch, *_SEARCH_TOOL],
    output_key="context_research",
)
