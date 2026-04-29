"""Scout — first node in the v2 graph. See DESIGN.v2.md §6.1."""

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
    output_key="candidates",
)
