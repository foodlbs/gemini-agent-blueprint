"""Writer loop — drafter + critic. See DESIGN.v2.md §6.6.

`drafter` writes/rewrites the article markdown. `critic_llm` reviews
against the 8-item rubric and emits a JSON verdict (parsed by
nodes/critic_split.py)."""

from google.adk import Agent


# TODO §6.6.1 — fill in DRAFTER_INSTRUCTION:
#   - Iteration 0: write from scratch using outline + research.
#   - Iteration 1+: rewrite previous draft per critic_feedback.
#   - Mandate <!--IMG:position--> and <!--VID:hero--> placeholders.
drafter = Agent(
    name="drafter",
    model="gemini-3.1-pro",
    instruction=(
        "TODO §6.6.1 — generate or rewrite the article markdown matching "
        "outline; insert image/video placeholders at section boundaries."
    ),
    output_key="draft",
)


# TODO §6.6.2 — fill in CRITIC_INSTRUCTION (8-item rubric: word count,
# section headings, image/video placeholder presence, title mention,
# fact grounding, etc.).
critic_llm = Agent(
    name="critic_llm",
    model="gemini-3.1-flash",
    instruction=(
        "TODO §6.6.2 — score draft against 8-item rubric; emit "
        "single-line JSON {verdict: accept|revise, feedback: str}."
    ),
    output_key="_critic_raw",
)
