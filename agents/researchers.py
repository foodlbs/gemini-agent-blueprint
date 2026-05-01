"""Three parallel researchers — docs, github, context. See DESIGN.v2.md §6.4.

Tool composition follows Gemini's API restriction: an LlmAgent cannot
mix a built-in search tool (`google_search`) with custom function tools.
So we split:
  - docs_researcher    → `web_fetch` only  (URL is in chosen_release)
  - github_researcher  → github_ops only   (no web/search needed)
  - context_researcher → `google_search` only (must discover URLs)
"""

from google.adk import Agent

from shared.prompts import (
    CONTEXT_RESEARCHER_INSTRUCTION,
    DOCS_RESEARCHER_INSTRUCTION,
    GITHUB_RESEARCHER_INSTRUCTION,
)
from tools.github_ops import github_get_readme, github_get_repo, github_list_files
from tools.web import web_fetch

try:
    from google.adk.tools import google_search
    _SEARCH_TOOL = [google_search]
except ImportError:
    _SEARCH_TOOL = []  # ADK 2.0 may rename this; safe fallback.


docs_researcher = Agent(
    name="docs_researcher",
    model="gemini-2.5-flash-lite",
    instruction=DOCS_RESEARCHER_INSTRUCTION,
    tools=[web_fetch],
    output_key="docs_research",
)


github_researcher = Agent(
    name="github_researcher",
    model="gemini-2.5-flash-lite",
    instruction=GITHUB_RESEARCHER_INSTRUCTION,
    tools=[github_get_repo, github_get_readme, github_list_files],
    output_key="github_research",
)


context_researcher = Agent(
    name="context_researcher",
    model="gemini-2.5-flash-lite",
    instruction=CONTEXT_RESEARCHER_INSTRUCTION,
    tools=_SEARCH_TOOL,
    output_key="context_research",
)
