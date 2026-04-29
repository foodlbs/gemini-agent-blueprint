"""Scout — first agent in the pipeline. Polls all configured release sources."""

from google.adk.agents import LlmAgent

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


scout = LlmAgent(
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
