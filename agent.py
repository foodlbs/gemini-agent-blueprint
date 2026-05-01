"""v2 root_agent — the canonical Workflow. See DESIGN.v2.md §5.

This file is the single source of truth for control flow. Every node
mentioned here gets a §6.x subsection in DESIGN.v2.md documenting its
inputs, outputs, failure modes, and tests.

Wiring rules:
  - LlmAgents do work; they do NOT decide which node runs next.
  - Routing happens in `nodes/routing.py` function nodes that set
    `ctx.route = "BRANCH"`. The dict-edge form `{"BRANCH": next_node}`
    selects the destination.
  - Fan-out (parallel execution) is a tuple as the dict-edge value:
    `{"approve": (a, b, c)}` triggers all three.
  - Terminal nodes have no outgoing edges; the workflow ends after they
    set `cycle_outcome`.
"""

from google.adk import Workflow

from agents.architect import architect_llm
from agents.repo_builder import repo_builder
from agents.researchers import (
    context_researcher,
    docs_researcher,
    github_researcher,
)
from agents.revision_writer import revision_writer
from agents.scout import scout
from agents.triage import triage
from agents.writer import critic_llm, drafter

from nodes.aggregation import gather_assets, gather_research
from nodes.architect_split import architect_split
from nodes.critic_split import critic_split
from nodes.hitl import editor_request, topic_gate_request
from nodes.image_assets import image_asset_node
from nodes.publisher import publisher
from nodes.records import (
    record_editor_rejection,
    record_editor_timeout,
    record_editor_verdict,
    record_human_topic_skip,
    record_topic_timeout,
    record_topic_verdict,
    record_triage_skip,
)
from nodes.routing import (
    route_after_triage,
    route_critic_verdict,
    route_editor_verdict,
    route_needs_repo,
    route_topic_verdict,
)
from nodes.scout_split import scout_split
from nodes.video_asset import video_asset_or_skip

from shared.models import PipelineState


root_agent = Workflow(
    name="ai_release_pipeline_v2",
    state_schema=PipelineState,
    rerun_on_resume=False,            # See docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md
    edges=[
        # --- 1. Scout → scout_split → Triage → route on chosen_release ---
        # scout_split parses Scout's scout_raw (markdown-fenced JSON) into
        # the typed `candidates` list. Same pattern as architect_split +
        # critic_split — strict on parse, defensive on truncation.
        ("START", scout, scout_split, triage, route_after_triage, {
            "SKIP":     record_triage_skip,
            "CONTINUE": topic_gate_request,
        }),

        # --- 2. Topic Gate (HITL #1) — fan-out to research on approve ----
        (topic_gate_request, record_topic_verdict, route_topic_verdict, {
            "approve":  (docs_researcher, github_researcher, context_researcher),
            "skip":     record_human_topic_skip,
            "timeout":  record_topic_timeout,
        }),

        # --- 3. Research join → Architect → Writer loop ------------------
        (docs_researcher,    gather_research),
        (github_researcher,  gather_research),
        (context_researcher, gather_research),
        (gather_research, architect_llm, architect_split, drafter,
                                       critic_llm, critic_split,
                                       route_critic_verdict, {
            "REVISE": drafter,
            "ACCEPT": image_asset_node,
        }),

        # --- 4. Asset chain → repo router → editor ------------------------
        # Image generation is now a function node (no LLM) — Imagen's
        # raw PNG bytes used to balloon the LlmAgent context past the
        # 1M-token cap on the second call. Sequential chain ensures the
        # gather_assets barrier sees fully-populated state.
        (image_asset_node, video_asset_or_skip, gather_assets),
        (gather_assets, route_needs_repo, {
            "WITH_REPO":    repo_builder,
            "WITHOUT_REPO": editor_request,
        }),
        (repo_builder, editor_request),

        # --- 5. Editor (HITL #2) — approve / revise loop / reject -------
        (editor_request, record_editor_verdict, route_editor_verdict, {
            "approve":  publisher,
            "reject":   record_editor_rejection,
            "revise":   revision_writer,
            "timeout":  record_editor_timeout,
        }),
        (revision_writer, editor_request),  # loop back into HITL
    ],
)
