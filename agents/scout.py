"""Scout — first node in the v2 graph. See DESIGN.v2.md §6.1.

Scout's LLM output is markdown-flavored JSON (LLMs love markdown fences
around JSON blocks). ADK's ``output_key`` mechanism stores the raw text
verbatim, so a downstream ``scout_split`` function node parses the JSON
and writes the typed ``list[Candidate]`` to ``state['candidates']``.

Same pattern as architect_split (§6.5.2) and critic_split (§6.6.3) —
consistent across every LlmAgent that emits structured data.
"""

from google.adk import Agent
from google.genai import types as genai_types

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


# Without this, Gemini 2.5 sometimes emits Python pseudocode like
# `default_api.poll_arxiv(since=...)` instead of native JSON function
# calls — a "compositional" multi-tool mode ADK doesn't parse.
#
# VALIDATED mode + allowed_function_names whitelist forces every
# function call to use one of our 7 poller names (rejecting hallucinated
# `default_api` / `run_tool_code` etc.) while still allowing Scout to
# emit a final text response once polling is done.
#
# max_output_tokens is bumped because 25 candidates with arxiv abstracts
# easily blow past the 8K default. The Triage instruction also tells
# Scout to trim raw_summary to keep output compact; this is the safety
# net for when it doesn't.
_FORCE_TOOLS_CONFIG = genai_types.GenerateContentConfig(
    max_output_tokens=24000,
    tool_config=genai_types.ToolConfig(
        function_calling_config=genai_types.FunctionCallingConfig(
            mode=genai_types.FunctionCallingConfigMode.VALIDATED,
            allowed_function_names=[
                "poll_arxiv",
                "poll_github_trending",
                "poll_rss",
                "poll_hf_models",
                "poll_hf_papers",
                "poll_hackernews_ai",
                "poll_anthropic_news",
            ],
        ),
    ),
)


scout = Agent(
    name="scout",
    # 2.5-pro: flash-lite hallucinates built-in code-execution tools
    # (`run_code`, `default_api.X`) even with VALIDATED + allowlist;
    # flash respects the whitelist but the per-minute quota in us-west1
    # is too tight for testing (3 LLM calls per cycle saturates fast).
    # Pro has a separate quota pool and more reliable tool calling.
    model="gemini-2.5-pro",
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
    generate_content_config=_FORCE_TOOLS_CONFIG,
    # Raw text — `nodes/scout_split.py` parses + validates downstream.
    output_key="scout_raw",
)
