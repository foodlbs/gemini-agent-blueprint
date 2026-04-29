"""Architect — produces the JSON blob parsed by nodes/architect_split.py.
See DESIGN.v2.md §6.5.1."""

from google.adk import Agent

# TODO §6.5.1 — fill in ARCHITECT_INSTRUCTION mandating the exact JSON
# shape architect_split parses (outline + image_briefs + video_brief +
# needs_video + needs_repo).
architect_llm = Agent(
    name="architect_llm",
    model="gemini-3.1-pro",
    instruction=(
        "TODO §6.5.1 — produce a single JSON object with keys: "
        "outline, image_briefs, video_brief, needs_video, needs_repo. "
        "No prose, no markdown fences."
    ),
    output_key="_architect_raw",
)
