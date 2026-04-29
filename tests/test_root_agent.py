"""Tests for the top-level ``root_agent`` composition + pipeline-wide
early-exit audit per DESIGN.md "Top-level orchestration" and
"Early-exit pattern".
"""

from google.adk.agents import (
    LlmAgent,
    LoopAgent,
    ParallelAgent,
    SequentialAgent,
)


EXPECTED_PIPELINE_STAGES = [
    "scout",
    "triage",
    "topic_gate",
    "researcher_pool",
    "architect",
    "writer_loop",
    "post_writer_parallel",
    "revision_loop",
]

EARLY_EXIT_LINE = (
    "If state['chosen_release'] is None, end your turn immediately "
    "without using tools."
)


# --- Top-level composition ------------------------------------------------


def test_root_agent_is_sequential_with_eight_named_stages():
    """DESIGN.md "Top-level orchestration": exactly the eight stages, in order."""
    from main import root_agent

    assert isinstance(root_agent, SequentialAgent)
    assert root_agent.name == "ai_release_to_article_pipeline"
    assert [a.name for a in root_agent.sub_agents] == EXPECTED_PIPELINE_STAGES


def test_root_agent_uses_the_module_level_singletons():
    """The root_agent's sub_agents must be the same instances exported by
    each agent module — not duplicates accidentally constructed at import
    time. Identity check guards against accidental rebuilds (which would
    break before/after callbacks attached to the originals)."""
    from agents.researchers.context import context_researcher
    from agents.researchers.docs import docs_researcher
    from agents.researchers.github import github_researcher
    from agents.scout.agent import scout
    from agents.topic_gate.agent import topic_gate
    from agents.triage.agent import triage
    from main import (
        asset_agent,
        post_writer_parallel,
        researcher_pool,
        revision_loop,
        root_agent,
        writer_loop,
    )
    from agents.architect.agent import architect

    # Top-level identity check
    assert root_agent.sub_agents[0] is scout
    assert root_agent.sub_agents[1] is triage
    assert root_agent.sub_agents[2] is topic_gate
    assert root_agent.sub_agents[3] is researcher_pool
    assert root_agent.sub_agents[4] is architect
    assert root_agent.sub_agents[5] is writer_loop
    assert root_agent.sub_agents[6] is post_writer_parallel
    assert root_agent.sub_agents[7] is revision_loop

    # Researcher pool sub-agents (LlmAgent instances aren't hashable —
    # use a list comparison after sorting by name).
    pool_by_name = {a.name: a for a in researcher_pool.sub_agents}
    assert pool_by_name["docs_researcher"] is docs_researcher
    assert pool_by_name["github_researcher"] is github_researcher
    assert pool_by_name["context_researcher"] is context_researcher


def test_pipeline_wrapper_exports_root_agent_for_adk_web():
    """``pipeline/`` is the discovery wrapper for ``adk web``; it must
    re-export the same root_agent instance from main."""
    from main import root_agent as main_root
    from pipeline import root_agent as wrapper_root

    assert wrapper_root is main_root


# --- Early-exit pattern audit --------------------------------------------


def _walk_llm_agents(agent) -> list[LlmAgent]:
    """Recursively collect every LlmAgent inside this subtree."""
    found: list[LlmAgent] = []
    if isinstance(agent, LlmAgent):
        found.append(agent)
    for sub in getattr(agent, "sub_agents", []) or []:
        found.extend(_walk_llm_agents(sub))
    return found


def test_every_agent_from_researcher_pool_onward_has_chosen_release_first_line():
    """[DESIGN.md "Early-exit pattern" + user Step 11 prepend]
    Every LlmAgent inside ``researcher_pool``, ``architect``,
    ``writer_loop``, ``post_writer_parallel``, and ``revision_loop`` must
    have the chosen_release early-exit as the first non-blank line of its
    instruction. Triage/Topic Gate set chosen_release=None on skip; this
    audit guarantees the signal stops every downstream agent.
    """
    from main import (
        architect,
        post_writer_parallel,
        researcher_pool,
        revision_loop,
        writer_loop,
    )

    downstream_subtrees = [
        researcher_pool,
        architect,
        writer_loop,
        post_writer_parallel,
        revision_loop,
    ]
    downstream_agents: list[LlmAgent] = []
    for subtree in downstream_subtrees:
        downstream_agents.extend(_walk_llm_agents(subtree))

    assert downstream_agents, "audit collected zero agents — wiring broken"

    failures: list[str] = []
    for agent in downstream_agents:
        first_line = next(
            (line for line in agent.instruction.splitlines() if line.strip()),
            "",
        )
        if first_line != EARLY_EXIT_LINE:
            failures.append(f"{agent.name}: first non-blank line was {first_line!r}")

    assert not failures, (
        "Agents without the chosen_release early-exit as their first "
        "non-blank instruction line:\n  " + "\n  ".join(failures)
    )


def test_audit_does_not_apply_to_scout_or_triage_or_topic_gate():
    """The early-exit pattern is for agents downstream of the gate. Scout,
    Triage, and Topic Gate are upstream — they MUST NOT have the prepend
    (they do their own decisioning that produces or clears chosen_release).
    """
    from agents.scout.agent import scout
    from agents.topic_gate.agent import topic_gate
    from agents.triage.agent import triage

    for agent in (scout, triage, topic_gate):
        first_line = next(
            (line for line in agent.instruction.splitlines() if line.strip()),
            "",
        )
        assert first_line != EARLY_EXIT_LINE, (
            f"upstream agent {agent.name!r} unexpectedly carries the "
            f"downstream early-exit"
        )


# --- Container shape sanity checks --------------------------------------


def test_researcher_pool_is_parallel_with_three_subagents():
    from main import researcher_pool

    assert isinstance(researcher_pool, ParallelAgent)
    assert len(researcher_pool.sub_agents) == 3


def test_writer_loop_is_loop_max_3_drafter_then_critic():
    from main import writer_loop

    assert isinstance(writer_loop, LoopAgent)
    assert writer_loop.max_iterations == 3
    assert [a.name for a in writer_loop.sub_agents] == ["drafter", "critic"]


def test_post_writer_parallel_is_parallel_assets_and_repo_router():
    from main import post_writer_parallel

    assert isinstance(post_writer_parallel, ParallelAgent)
    sub_names = {a.name for a in post_writer_parallel.sub_agents}
    assert sub_names == {"asset_agent", "repo_router"}


def test_revision_loop_is_loop_max_3_editor_then_revision_writer():
    from main import revision_loop

    assert isinstance(revision_loop, LoopAgent)
    assert revision_loop.max_iterations == 3
    assert [a.name for a in revision_loop.sub_agents] == ["editor", "revision_writer"]
