"""Context researcher — finds 3-5 paraphrased reactions/comparisons/related
releases from the last 30 days. Writes ``state["context_research"]``.
"""

from google.adk.agents import LlmAgent
from google.adk.tools import google_search

from shared.prompts import CONTEXT_RESEARCHER_INSTRUCTION


context_researcher = LlmAgent(
    name="context_researcher",
    model="gemini-3.1-flash-lite-preview",
    instruction=CONTEXT_RESEARCHER_INSTRUCTION,
    tools=[google_search],
    output_key="context_research",
)
