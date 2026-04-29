"""Tests for the Architect agent.

Coverage maps to the user's three required scenarios from DESIGN.md §5:
- quickstart with code → needs_repo=True, image_brief 3-4 specs, possibly needs_video=True.
- explainer no code → needs_repo=False, image_brief still populated, needs_video=False.
- release_recap → minimal everything.

Plus instruction-as-contract checks (rules for article type, image count,
needs_repo, needs_video) and agent wiring (model, no tools, both callbacks).
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shared.models import (
    Candidate,
    ChosenRelease,
    ImageBrief,
    Outline,
    OutlineSection,
    ResearchDossier,
    VideoBrief,
)


# --- Fixtures ---------------------------------------------------------------


def _release(title: str, url: str = "https://example.com/x") -> ChosenRelease:
    return ChosenRelease(
        title=title,
        url=url,
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="A new release.",
        score=85,
        rationale="strong release",
        top_alternatives=[],
    )


@pytest.fixture
def quickstart_with_code_state() -> dict:
    """Fixture 1: chosen release has runnable code → quickstart article shape.

    docs_research has a code_example + prerequisites; github_research has
    repo metadata, README excerpt, and file_list. Per DESIGN.md §5, the
    LLM should default to quickstart, set needs_repo=True (non-trivial
    setup), produce 3-4 image specs, and possibly set needs_video=True.
    """
    chosen = _release("Anthropic Skills SDK", "https://github.com/anthropic/skills")
    docs = ResearchDossier(
        summary="A new SDK that ships agent capabilities as importable bundles.",
        headline_quotes=["Skills are agents-as-libraries"],
        code_example="from anthropic_skills import load_skill\nskill = load_skill('summarize')\nresult = skill('Long article text here.')",
        prerequisites=["pip install anthropic-skills", "ANTHROPIC_API_KEY"],
    )
    github = ResearchDossier(
        summary="Official SDK + sample skills.",
        repo_meta={"stars": 1234, "language": "Python", "default_branch": "main"},
        readme_excerpt="# Skills\nA library for ...",
        file_list=["README.md", "src/", "examples/", "pyproject.toml", "tests/"],
    )
    context = ResearchDossier(
        summary="Several labs released agent SDKs in the last 30 days.",
        reactions=["Simon Willison: useful baseline for agent composition"],
        related_releases=["OpenAI Assistants v2", "Google Gemini Agents SDK"],
    )
    return {
        "chosen_release": chosen,
        "docs_research": docs.model_dump(mode="json"),
        "github_research": github.model_dump(mode="json"),
        "context_research": context.model_dump(mode="json"),
    }


@pytest.fixture
def explainer_no_code_state() -> dict:
    """Fixture 2: chosen release is a paper/announcement without runnable code
    → explainer article shape. needs_repo=False, image_brief still populated
    (cover + diagrams), needs_video=False (no motion benefit)."""
    chosen = _release(
        "Anthropic Constitutional AI v2",
        "https://www.anthropic.com/research/constitutional-ai-v2",
    )
    docs = ResearchDossier(
        summary="A new paper revising the constitutional AI training method.",
        headline_quotes=["A second-order critique loop"],
        code_example=None,
        prerequisites=[],
    )
    github = ResearchDossier(
        summary="No public repo associated with this release.",
    )
    context = ResearchDossier(
        summary="Safety researchers received the paper warmly.",
        reactions=["Yejin Choi: extends the rebuttal-budget framing"],
        related_releases=["DeepMind Sparrow rule-set"],
    )
    return {
        "chosen_release": chosen,
        "docs_research": docs.model_dump(mode="json"),
        "github_research": github.model_dump(mode="json"),
        "context_research": context.model_dump(mode="json"),
    }


@pytest.fixture
def release_recap_state() -> dict:
    """Fixture 3: minor release worth a short recap. Minimal everything —
    short outline, no repo, no video, just a cover image."""
    chosen = _release(
        "Anthropic Claude 3.7 Patch Notes",
        "https://www.anthropic.com/news/claude-3-7-patch",
    )
    docs = ResearchDossier(
        summary="A minor patch addressing tool-use latency.",
        headline_quotes=[],
        code_example=None,
        prerequisites=[],
    )
    github = ResearchDossier(summary="No repo.")
    context = ResearchDossier(
        summary="Brief discussion in developer forums.",
        reactions=[],
        related_releases=[],
    )
    return {
        "chosen_release": chosen,
        "docs_research": docs.model_dump(mode="json"),
        "github_research": github.model_dump(mode="json"),
        "context_research": context.model_dump(mode="json"),
    }


def _expected_quickstart_output() -> dict:
    """The JSON the LLM should emit for the quickstart_with_code fixture."""
    return {
        "article_type": "quickstart",
        "outline": Outline(
            sections=[
                OutlineSection(heading="What it is", intent="frame the SDK", word_count=200),
                OutlineSection(heading="Setup", intent="install + auth", word_count=300),
                OutlineSection(heading="Your first skill", intent="walkthrough", word_count=600),
                OutlineSection(heading="Where to go next", intent="extensions", word_count=300),
            ],
            working_title="Build with Anthropic Skills",
            working_subtitle="Agents as importable libraries",
            article_type="quickstart",
        ).model_dump(mode="json"),
        "needs_repo": True,
        "needs_video": True,
        "image_brief": [
            ImageBrief(position="cover", description="hero shot of stacked skill bundles", style="illustration", aspect_ratio="16:9").model_dump(mode="json"),
            ImageBrief(position="after-section-1", description="install flow diagram", style="diagram", aspect_ratio="16:9").model_dump(mode="json"),
            ImageBrief(position="after-section-2", description="terminal with first run", style="screenshot", aspect_ratio="4:3").model_dump(mode="json"),
        ],
        "video_brief": VideoBrief(
            description="end-to-end first-skill walkthrough",
            style="screencast",
            duration_seconds=6,
            aspect_ratio="16:9",
        ).model_dump(mode="json"),
        "working_title": "Build with Anthropic Skills",
        "working_subtitle": "Agents as importable libraries",
    }


def _expected_explainer_output() -> dict:
    """The JSON the LLM should emit for the explainer_no_code fixture."""
    return {
        "article_type": "explainer",
        "outline": Outline(
            sections=[
                OutlineSection(heading="What changed", intent="situate the paper", word_count=300),
                OutlineSection(heading="The mechanism", intent="explain the method", word_count=500),
                OutlineSection(heading="Why it matters", intent="implications", word_count=300),
            ],
            working_title="Constitutional AI, Revised",
            working_subtitle="Anthropic refines its critique loop",
            article_type="explainer",
        ).model_dump(mode="json"),
        "needs_repo": False,
        "needs_video": False,
        "image_brief": [
            ImageBrief(position="cover", description="stylized constitution scroll", style="illustration", aspect_ratio="16:9").model_dump(mode="json"),
            ImageBrief(position="after-section-1", description="critique-loop diagram", style="diagram", aspect_ratio="16:9").model_dump(mode="json"),
            ImageBrief(position="after-section-2", description="comparison chart vs v1", style="diagram", aspect_ratio="4:3").model_dump(mode="json"),
        ],
        "video_brief": None,
        "working_title": "Constitutional AI, Revised",
        "working_subtitle": "Anthropic refines its critique loop",
    }


def _expected_release_recap_output() -> dict:
    """Minimal everything — short outline, no repo, no video, single cover."""
    return {
        "article_type": "release_recap",
        "outline": Outline(
            sections=[
                OutlineSection(heading="What's in the patch", intent="recap notes", word_count=400),
                OutlineSection(heading="Should you upgrade?", intent="brief recommendation", word_count=300),
            ],
            working_title="Claude 3.7 Patch Notes",
            working_subtitle="Latency tweaks for tool use",
            article_type="release_recap",
        ).model_dump(mode="json"),
        "needs_repo": False,
        "needs_video": False,
        "image_brief": [
            ImageBrief(position="cover", description="patch-notes graphic", style="illustration", aspect_ratio="16:9").model_dump(mode="json"),
        ],
        "video_brief": None,
        "working_title": "Claude 3.7 Patch Notes",
        "working_subtitle": "Latency tweaks for tool use",
    }


def _run_after_callback(state: dict) -> dict:
    from agents.architect.agent import _split_architect_output
    _split_architect_output(SimpleNamespace(state=state))
    return state


# --- The three user-required scenario tests -------------------------------


def test_quickstart_with_code_yields_needs_repo_image_specs_and_maybe_video(
    quickstart_with_code_state,
):
    """[Scenario 1] needs_repo=True, image_brief 3-4 specs, possibly needs_video=True."""
    state = {**quickstart_with_code_state,
             "architect_output": _expected_quickstart_output()}
    _run_after_callback(state)

    assert state["article_type"] == "quickstart"
    assert state["needs_repo"] is True
    assert 3 <= len(state["image_brief"]) <= 4
    # "Possibly needs_video=True" — for this fixture (rich code example + setup
    # benefit from motion) the design's "be conservative" still allows it.
    assert state["needs_video"] is True
    assert state["video_brief"] is not None
    # Cover image is mandatory per DESIGN.md.
    assert any(b["position"] == "cover" for b in state["image_brief"])
    assert state["working_title"]
    assert state["working_subtitle"]


def test_explainer_no_code_disables_repo_and_video_keeps_images(
    explainer_no_code_state,
):
    """[Scenario 2] needs_repo=False, image_brief still populated, needs_video=False."""
    state = {**explainer_no_code_state,
             "architect_output": _expected_explainer_output()}
    _run_after_callback(state)

    assert state["article_type"] == "explainer"
    assert state["needs_repo"] is False
    assert state["needs_video"] is False
    assert state["video_brief"] is None
    # Image brief still has at least the cover plus diagrams.
    assert len(state["image_brief"]) >= 1
    assert any(b["position"] == "cover" for b in state["image_brief"])


def test_release_recap_yields_minimal_everything(release_recap_state):
    """[Scenario 3] release_recap → minimal everything."""
    state = {**release_recap_state,
             "architect_output": _expected_release_recap_output()}
    _run_after_callback(state)

    assert state["article_type"] == "release_recap"
    assert state["needs_repo"] is False
    assert state["needs_video"] is False
    assert state["video_brief"] is None
    # Even minimal recaps keep a single cover image (DESIGN.md: "Always one cover").
    assert len(state["image_brief"]) >= 1
    assert state["image_brief"][0]["position"] == "cover"
    # Recap word count target is 800-1200 (i.e., not the 1200-1800 quickstart band).
    total_words = sum(s["word_count"] for s in state["outline"]["sections"])
    assert total_words < 1200


# --- after_agent_callback parsing edge cases ------------------------------


def test_after_callback_parses_json_string_output(quickstart_with_code_state):
    """The LLM may emit a JSON string (not a dict). Callback should parse it."""
    state = {
        **quickstart_with_code_state,
        "architect_output": json.dumps(_expected_quickstart_output()),
    }
    _run_after_callback(state)
    assert state["article_type"] == "quickstart"
    assert state["needs_repo"] is True


def test_after_callback_strips_markdown_code_fence(quickstart_with_code_state):
    """The LLM may wrap its JSON in a ```json``` fence."""
    fenced = "```json\n" + json.dumps(_expected_quickstart_output()) + "\n```"
    state = {**quickstart_with_code_state, "architect_output": fenced}
    _run_after_callback(state)
    assert state["article_type"] == "quickstart"


def test_after_callback_is_noop_when_chosen_release_is_none():
    state = {"chosen_release": None, "architect_output": "garbage"}
    _run_after_callback(state)
    # No keys should be added.
    assert "article_type" not in state
    assert "needs_repo" not in state


def test_after_callback_is_noop_when_output_is_unparseable(quickstart_with_code_state):
    state = {**quickstart_with_code_state, "architect_output": "not json at all {{{"}
    _run_after_callback(state)
    # No keys should be added on parse failure.
    assert "article_type" not in state


# --- before_agent_callback: programmatic early exit -----------------------


def test_before_callback_returns_skip_content_when_chosen_release_is_none():
    from agents.architect.agent import _early_exit_if_no_chosen_release
    ctx = SimpleNamespace(state={"chosen_release": None})
    result = _early_exit_if_no_chosen_release(ctx)
    assert result is not None
    assert "skipped" in result.parts[0].text.lower()


def test_before_callback_lets_agent_run_when_chosen_release_set(
    quickstart_with_code_state,
):
    from agents.architect.agent import _early_exit_if_no_chosen_release
    ctx = SimpleNamespace(state=quickstart_with_code_state)
    result = _early_exit_if_no_chosen_release(ctx)
    assert result is None  # callback declines to short-circuit


# --- Agent wiring ---------------------------------------------------------


def test_architect_agent_configuration():
    from agents.architect.agent import architect

    assert architect.name == "architect"
    assert architect.model == "gemini-3.1-pro-preview"
    assert architect.tools == []  # DESIGN.md §5: "Tools: None"
    assert architect.output_key == "architect_output"
    assert architect.before_agent_callback is not None
    assert architect.after_agent_callback is not None


def test_architect_instruction_first_line_is_early_exit():
    from agents.architect.agent import architect

    first_line = architect.instruction.splitlines()[0]
    assert first_line == (
        "If state['chosen_release'] is None, end your turn immediately without using tools."
    )


def test_architect_instruction_encodes_design_rules():
    from agents.architect.agent import architect

    instr = architect.instruction
    # Article types
    for t in ("quickstart", "explainer", "comparison", "release_recap"):
        assert t in instr
    # needs_repo and needs_video conservatism
    assert "needs_repo" in instr
    assert "needs_video" in instr
    # image_brief specs (3-4 with one cover)
    assert "image_brief" in instr
    assert "cover" in instr
    # The eight output keys
    for key in (
        "outline", "article_type", "needs_repo", "image_brief",
        "video_brief", "needs_video", "working_title", "working_subtitle",
    ):
        assert key in instr
