"""Scout — first node in the v2 graph. See DESIGN.v2.md §6.1.

Scout's LLM output is markdown-flavored JSON (LLMs love markdown fences
around JSON blocks). ADK's ``output_key`` mechanism stores the raw text
verbatim, so a downstream ``scout_split`` function node parses the JSON
and writes the typed ``list[Candidate]`` to ``state['candidates']``.

Same pattern as architect_split (§6.5.2) and critic_split (§6.6.3) —
consistent across every LlmAgent that emits structured data.
"""

from google.adk import Agent

from shared.prompts import SCOUT_INSTRUCTION
from tools.pollers import (
    poll_anthropic_news,
    poll_arxiv,
    poll_github_trending,
    poll_hackernews_ai,
    poll_hf_models,
    poll_hf_papers,
    poll_rss,
)


scout = Agent(
    name="scout",
    model="gemini-3.1-flash-lite-preview",
    instruction=SCOUT_INSTRUCTION,
    tools=[
        poll_arxiv,
        poll_github_trending,
        poll_rss,
        poll_hf_models,
        poll_hf_papers,
        poll_hackernews_ai,
        poll_anthropic_news,
    ],
    # Raw text — `nodes/scout_split.py` parses + validates downstream.
    output_key="scout_raw",
)
