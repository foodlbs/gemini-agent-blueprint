"""Unit tests for nodes/critic_split.py — JSON parsing + objective marker check.

Per DESIGN.v2.md §6.6.3. The split parses the LLM's verdict AND
performs an objective string-search for placeholder markers — if the
LLM said 'accept' but markers are missing, critic_split overrides to
'revise'. This is the belt-and-suspenders defense for the Bug B2 class.
"""

from unittest.mock import MagicMock

from shared.models import Draft, ImageBrief

from nodes.critic_split import critic_split


def _ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    return ctx


def _draft(markdown: str = "Body") -> Draft:
    return Draft(markdown=markdown, iteration=0)


def _briefs(positions: list[str]) -> list[ImageBrief]:
    return [
        ImageBrief(position=p, description="x", style="illustration", aspect_ratio="16:9")
        for p in positions
    ]


# --- JSON parsing ---------------------------------------------------------


def test_parses_clean_accept_verdict():
    md = "Title\n<!--IMG:hero-->\n## Section 1\nBody"
    ctx = _ctx({
        "_critic_raw": '{"verdict": "accept", "feedback": ""}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "accept"
    assert ctx.state["draft"].critic_verdict == "accept"
    assert ctx.state["writer_iterations"] == 1


def test_parses_revise_verdict_with_feedback():
    md = "Title\n<!--IMG:hero-->\n## Section 1\nBody"
    ctx = _ctx({
        "_critic_raw": '{"verdict": "revise", "feedback": "tighten intro"}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "revise"
    assert "tighten intro" in ctx.state["draft"].critic_feedback


def test_strips_markdown_fences_around_json():
    md = "<!--IMG:hero-->"
    ctx = _ctx({
        "_critic_raw": '```json\n{"verdict": "accept", "feedback": ""}\n```',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "accept"


def test_recovers_json_when_prose_around_it():
    md = "<!--IMG:hero-->"
    ctx = _ctx({
        "_critic_raw": 'Here is my verdict: {"verdict": "accept", "feedback": ""} — done.',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "accept"


def test_unparseable_json_coerced_to_revise():
    md = "<!--IMG:hero-->"
    ctx = _ctx({
        "_critic_raw": "not json at all",
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    # Default to revise when we can't parse the LLM's verdict
    assert event.output["verdict"] == "revise"


def test_unknown_verdict_value_coerced_to_revise():
    md = "<!--IMG:hero-->"
    ctx = _ctx({
        "_critic_raw": '{"verdict": "yikes", "feedback": ""}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "revise"


# --- Objective marker check (overrides LLM accept) -----------------------


def test_image_marker_count_mismatch_overrides_accept_to_revise():
    """LLM said accept but draft has 2 markers when there are 3 briefs.
    The critic_split MUST override to revise. Bug B2 belt + suspenders."""
    md = "<!--IMG:hero--><!--IMG:section_1-->"  # 2 markers
    ctx = _ctx({
        "_critic_raw": '{"verdict": "accept", "feedback": ""}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero", "section_1", "section_2"]),  # 3 briefs
        "needs_video": False,
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "revise"
    assert "image markers" in ctx.state["draft"].critic_feedback


def test_video_marker_present_when_needs_video_false_overrides_accept():
    """Reverse case: needs_video=False but VID marker is in the draft.
    LLM said accept; critic_split overrides to revise."""
    md = "<!--IMG:hero--><!--VID:hero-->"
    ctx = _ctx({
        "_critic_raw": '{"verdict": "accept", "feedback": ""}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,  # but VID marker IS in draft
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "revise"
    assert "video marker" in ctx.state["draft"].critic_feedback


def test_video_marker_missing_when_needs_video_true_overrides_accept():
    """Forward case: needs_video=True but no VID marker. Override to revise."""
    md = "<!--IMG:hero-->"  # no VID marker
    ctx = _ctx({
        "_critic_raw": '{"verdict": "accept", "feedback": ""}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": True,  # marker required but missing
        "writer_iterations": 0,
    })
    event = critic_split(None, ctx)
    assert event.output["verdict"] == "revise"


def test_iteration_counter_increments_each_call():
    md = "<!--IMG:hero-->"
    ctx = _ctx({
        "_critic_raw": '{"verdict": "accept", "feedback": ""}',
        "draft": _draft(md),
        "image_briefs": _briefs(["hero"]),
        "needs_video": False,
        "writer_iterations": 2,
    })
    critic_split(None, ctx)
    assert ctx.state["writer_iterations"] == 3
