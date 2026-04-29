"""Docs researcher — fetches official docs/blog/release notes for the chosen
release and produces a structured dossier under ``state["docs_research"]``.
"""

from google.adk.agents import LlmAgent
from google.adk.tools import google_search

from shared.prompts import DOCS_RESEARCHER_INSTRUCTION
from tools.web import web_fetch


docs_researcher = LlmAgent(
    name="docs_researcher",
    model="gemini-3.1-flash-lite-preview",
    instruction=DOCS_RESEARCHER_INSTRUCTION,
    tools=[web_fetch, google_search],
    output_key="docs_research",
)
