"""Top-level wiring for the AI release pipeline.

Composes the eight-stage SequentialAgent root per DESIGN.md "Top-level
orchestration":

    scout → triage → topic_gate → researcher_pool → architect →
    writer_loop → post_writer_parallel → revision_loop

Per DESIGN.md "Early-exit pattern", every agent from ``researcher_pool``
onward (including those nested in ``ParallelAgent`` and ``LoopAgent``
containers) has the chosen_release early-exit as its first instruction
line. Triage and Topic Gate set ``chosen_release`` to None on skip; that
single signal then propagates through the rest of the pipeline.
"""

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent

from agents.architect.agent import architect
from agents.asset.image import image_asset_agent
from agents.asset.video import video_asset_agent
from agents.editor.agent import editor
from agents.repo_builder.agent import repo_builder
from agents.researchers.context import context_researcher
from agents.researchers.docs import docs_researcher
from agents.researchers.github import github_researcher
from agents.revision_writer.agent import revision_writer
from agents.scout.agent import scout
from agents.topic_gate.agent import topic_gate
from agents.triage.agent import triage
from agents.writer.critic import critic
from agents.writer.drafter import drafter


researcher_pool = ParallelAgent(
    name="researcher_pool",
    sub_agents=[docs_researcher, github_researcher, context_researcher],
)


writer_loop = LoopAgent(
    name="writer_loop",
    max_iterations=3,
    sub_agents=[drafter, critic],
)


asset_agent = ParallelAgent(
    name="asset_agent",
    sub_agents=[image_asset_agent, video_asset_agent],
)


repo_router = LlmAgent(
    name="repo_router",
    model="gemini-3.1-flash-lite-preview",
    instruction=(
        "If state['chosen_release'] is None, end your turn immediately "
        "without using tools.\n\n"
        "Look at state['needs_repo']. If True, transfer to the repo_builder "
        "sub-agent. If False or missing, do nothing and end your turn."
    ),
    sub_agents=[repo_builder],
)


post_writer_parallel = ParallelAgent(
    name="post_writer_parallel",
    sub_agents=[asset_agent, repo_router],
)


revision_loop = LoopAgent(
    name="revision_loop",
    max_iterations=3,
    sub_agents=[editor, revision_writer],
)


# Top-level pipeline: eight stages run sequentially. Triage and Topic Gate
# set chosen_release=None on skip; downstream agents detect that and bail
# without doing work, so the SequentialAgent doesn't need conditional logic.
root_agent = SequentialAgent(
    name="ai_release_to_article_pipeline",
    sub_agents=[
        scout,
        triage,
        topic_gate,            # human gate #1
        researcher_pool,
        architect,
        writer_loop,
        post_writer_parallel,
        revision_loop,         # human gate #2 (looped)
    ],
)
