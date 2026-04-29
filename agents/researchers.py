"""Three parallel researchers — docs, github, context. See DESIGN.v2.md §6.4."""

from google.adk import Agent

from tools.github_ops import github_get_readme, github_get_repo, github_list_files
from tools.web import web_fetch

# `google_search` is the ADK-built-in tool. Only docs_researcher and
# context_researcher use it.
try:
    from google.adk.tools import google_search
    _SEARCH_TOOL = [google_search]
except ImportError:
    _SEARCH_TOOL = []  # ADK 2.0 might rename this; safe fallback.


# TODO §6.4.1 — fill in DOCS_RESEARCHER_INSTRUCTION (1-paragraph summary +
# headline_quotes + code_example + prerequisites).
docs_researcher = Agent(
    name="docs_researcher",
    model="gemini-3.1-flash",
    instruction="TODO §6.4.1 — fetch official docs/release blog; emit ResearchDossier.",
    tools=[web_fetch, *_SEARCH_TOOL],
    output_key="docs_research",
)


# TODO §6.4.2 — fill in GITHUB_RESEARCHER_INSTRUCTION (URL-detection +
# empty-dossier short-circuit when not a GitHub repo).
github_researcher = Agent(
    name="github_researcher",
    model="gemini-3.1-flash-lite-preview",
    instruction="TODO §6.4.2 — fetch repo metadata + README + file list; emit ResearchDossier.",
    tools=[github_get_repo, github_get_readme, github_list_files],
    output_key="github_research",
)


# TODO §6.4.3 — fill in CONTEXT_RESEARCHER_INSTRUCTION (reactions +
# related_releases + landscape summary).
context_researcher = Agent(
    name="context_researcher",
    model="gemini-3.1-flash",
    instruction="TODO §6.4.3 — fetch reactions + related releases; emit ResearchDossier.",
    tools=[web_fetch, *_SEARCH_TOOL],
    output_key="context_research",
)
