"""Scout — first node in the v2 graph. See DESIGN.v2.md §6.1."""

from google.adk import Agent

from tools.pollers import (
    poll_anthropic_news,
    poll_arxiv,
    poll_github_trending,
    poll_hackernews_ai,
    poll_hf_models,
    poll_hf_papers,
    poll_rss,
)

# TODO §6.1 — fill in the real prompt (carry over SCOUT_INSTRUCTION from
# shared/prompts.py with the "call EVERY polling tool" mandate + cap-25
# priority order).
scout = Agent(
    name="scout",
    model="gemini-3.1-flash-lite-preview",
    instruction="TODO §6.1 — call all 7 pollers; write merged candidates list.",
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
