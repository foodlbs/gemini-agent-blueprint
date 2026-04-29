"""Revision Writer — rewrites draft per human_feedback. See DESIGN.v2.md §6.10.

Loops back to nodes/hitl.py:editor_request, NOT to critic_llm — once the
human is involved, the structural rubric is bypassed."""

from google.adk import Agent


# TODO §6.10 — fill in REVISION_WRITER_INSTRUCTION:
#   - Read draft.markdown + human_feedback.feedback.
#   - Apply feedback while preserving section headings, image/video markers,
#     and ±20% word count budget.
#   - Empty feedback → "improve clarity and concision throughout."
revision_writer = Agent(
    name="revision_writer",
    model="gemini-3.1-pro",
    instruction=(
        "TODO §6.10 — rewrite draft.markdown per human_feedback; "
        "preserve <!--IMG:--> and <!--VID:--> markers; emit Draft."
    ),
    output_key="draft",
)
