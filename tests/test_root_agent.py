"""Test that the root_agent Workflow has rerun_on_resume=False so
resume from RequestInput pauses doesn't re-execute upstream nodes.

See docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md
for the symptoms this prevents (duplicate editor messages, runaway
writer_iterations, missing editor_verdict)."""

from agent import root_agent


def test_root_agent_disables_rerun_on_resume():
    """The default `Workflow(rerun_on_resume=True)` causes editor_request
    resumes to re-execute the writer loop + asset stage, producing
    duplicate Telegram messages and clobbering record_editor_verdict's
    state writes. We must explicitly disable it."""
    assert root_agent.rerun_on_resume is False, (
        "root_agent.rerun_on_resume must be False — see "
        "docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md"
    )
