"""scout_split — parse Scout's `scout_raw` JSON output into typed candidates.

Same pattern as `architect_split` (§6.5.2) and `critic_split` (§6.6.3):

  1. LLM emits markdown-fenced JSON to ``state.scout_raw``.
  2. This function strips fences, recovers JSON from prose, and parses.
  3. Validates each entry against ``Candidate``; drops invalid ones.
  4. Caps at 25 entries with the priority order from DESIGN.v2.md §6.1.
  5. Writes the typed list to ``state.candidates``.

Per §6.1's open question: cap-25 priority is enforced both in prompt
AND here in code (belt + suspenders).
"""

import json
import logging
import re
from typing import Any

from google.adk import Context, Event
from pydantic import ValidationError

from shared.models import Candidate

logger = logging.getLogger(__name__)


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_MAX_CANDIDATES = 25
# Match each balanced top-level `{...}` object inside the array. Used
# only as a fallback when bulk json.loads fails — splits the array
# brace-by-brace so one bad candidate doesn't drop all 25.
_OBJECT_RE = re.compile(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", re.DOTALL)


def _per_object_recover(cleaned: str) -> list:
    """When bulk parse fails, salvage individual valid objects from the
    array. Returns parsed dicts; skips any object that won't parse."""
    recovered = []
    for match in _OBJECT_RE.finditer(cleaned):
        try:
            obj = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            recovered.append(obj)
    return recovered

# Priority order per §6.1 — when capping, prefer named-lab posts in this order.
# Lower index = higher priority.
_SOURCE_PRIORITY = {
    s: i for i, s in enumerate([
        "anthropic", "openai", "google", "deepmind", "meta",
        "mistral", "nvidia", "microsoft",
        "arxiv", "huggingface_papers", "github", "huggingface",
        "huggingface_blog", "bair", "hackernews", "other",
    ])
}


def scout_split(node_input, ctx: Context) -> Event:
    """Parse scout_raw → candidates: list[Candidate], capped + priority-sorted."""
    raw = ctx.state.get("scout_raw") or ""

    cleaned = _FENCE_RE.sub("", raw).strip()
    if not cleaned.startswith("["):
        # Sometimes the LLM wraps the array in a 'candidates' object,
        # or surrounds the array with prose. Try to recover the array.
        match = re.search(r"\[\s*\{.*\}\s*\]", cleaned, re.DOTALL)
        if not match:
            logger.warning("scout_split: no JSON array found in scout_raw; "
                           "writing empty candidates")
            ctx.state["candidates"] = []
            return Event(output={"count": 0, "reason": "no_array_found"})
        cleaned = match.group(0)

    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Scout occasionally produces JSON with bad escape sequences in
        # raw_summary strings (literal `\` characters from arxiv abstracts
        # etc.). Rather than dropping ALL 25 candidates, fall back to
        # per-object recovery: split the array by top-level `},{`
        # boundaries and try each candidate independently.
        logger.warning(
            "scout_split: bulk JSON parse failed (%s); trying per-object recovery",
            e,
        )
        items = _per_object_recover(cleaned)
        if not items:
            logger.warning("scout_split: per-object recovery yielded nothing; writing empty candidates")
            ctx.state["candidates"] = []
            return Event(output={"count": 0, "reason": f"json_decode_error: {e}"})
        logger.info("scout_split: per-object recovery rescued %d/%s candidates",
                    len(items), "?")

    if not isinstance(items, list):
        # Some LLMs emit `{"candidates": [...]}` even when prompted for a bare list.
        if isinstance(items, dict) and isinstance(items.get("candidates"), list):
            items = items["candidates"]
        else:
            logger.warning("scout_split: top-level is %s, not list", type(items).__name__)
            ctx.state["candidates"] = []
            return Event(output={"count": 0, "reason": "not_a_list"})

    # Validate each entry. Skip invalid; log how many were dropped.
    valid: list[Candidate] = []
    dropped = 0
    for raw_item in items:
        if not isinstance(raw_item, dict):
            dropped += 1
            continue
        try:
            valid.append(Candidate(**raw_item))
        except ValidationError as e:
            dropped += 1
            logger.debug("scout_split: dropped invalid candidate: %s — %s", raw_item.get("title"), e)

    # De-dupe by URL (defensive — Scout's prompt asks for this but enforcing here).
    seen_urls: set[str] = set()
    deduped: list[Candidate] = []
    for c in valid:
        if c.url not in seen_urls:
            seen_urls.add(c.url)
            deduped.append(c)

    # Cap at 25 with priority sort (per §6.1).
    if len(deduped) > _MAX_CANDIDATES:
        deduped.sort(key=lambda c: _SOURCE_PRIORITY.get(c.source, 99))
        deduped = deduped[:_MAX_CANDIDATES]

    ctx.state["candidates"] = deduped
    # Format as a string Triage's LLM can clearly parse. ADK serializes
    # Event.output into the next LlmAgent's user message, and a string
    # is the most unambiguous form (some output shapes — bare dicts /
    # lists — get wrapped or stringified inconsistently across ADK 2.0
    # betas, leaving the LLM blind to the candidates).
    serialized = json.dumps(
        [c.model_dump(mode="json") for c in deduped], indent=2,
    )
    return Event(output=(
        f"Here are {len(deduped)} candidate releases to evaluate "
        f"(parsed and validated from Scout's output):\n\n{serialized}"
    ))
