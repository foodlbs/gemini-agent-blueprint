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
from agents.assets import image_asset_agent
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
from nodes.video_asset import video_asset_or_skip

from shared.models import PipelineState


root_agent = Workflow(
    name="ai_release_pipeline_v2",
    state_schema=PipelineState,
    edges=[
        # --- 1. Scout → Triage → route on chosen_release -----------------
        ("START", scout, triage, route_after_triage, {
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
            "ACCEPT": (image_asset_agent, video_asset_or_skip),
        }),

        # --- 4. Asset join → repo router → editor ------------------------
        (image_asset_agent,    gather_assets),
        (video_asset_or_skip,  gather_assets),
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
