"""Unit tests for nodes/architect_split.py — JSON parsing + structural validation.

Per DESIGN.v2.md §6.5.2. The split parses architect_llm's JSON blob
into 5 typed state writes (outline, image_briefs, video_brief,
needs_video, needs_repo). Strict on every structural error to catch
prompt drift early — fast-fails on missing JSON, 0 sections, 0 image
briefs, missing hero brief.
"""

import json

import pytest
from unittest.mock import MagicMock

from nodes.architect_split import architect_split


def _ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    return ctx


def _good_blob(needs_video: bool = False, needs_repo: bool = False) -> dict:
    return {
        "outline": {
            "working_title": "Title",
            "working_subtitle": "Subtitle",
            "article_type": "quickstart",
            "sections": [
                {"heading": "Intro", "intent": "set context", "research_items": [], "word_count": 200},
                {"heading": "Body",  "intent": "deliver",     "research_items": [], "word_count": 400},
            ],
        },
        "image_briefs": [
            {"position": "hero", "description": "x", "style": "illustration", "aspect_ratio": "16:9"},
            {"position": "section_1", "description": "y", "style": "diagram", "aspect_ratio": "16:9"},
        ],
        "video_brief": (
            {"description": "z", "style": "cinematic", "duration_seconds": 6, "aspect_ratio": "16:9"}
            if needs_video else None
        ),
        "needs_video": needs_video,
        "needs_repo": needs_repo,
    }


# --- Happy path -----------------------------------------------------------


def test_parses_complete_blob_writes_5_state_keys():
    ctx = _ctx({"_architect_raw": json.dumps(_good_blob())})
    event = architect_split(None, ctx)
    assert ctx.state["outline"].working_title == "Title"
    assert len(ctx.state["image_briefs"]) == 2
    assert ctx.state["video_brief"] is None
    assert ctx.state["needs_video"] is False
    assert ctx.state["needs_repo"] is False
    assert event.output["sections"] == 2
    assert event.output["images"] == 2


def test_parses_blob_with_video_brief_when_needs_video_true():
    ctx = _ctx({"_architect_raw": json.dumps(_good_blob(needs_video=True))})
    architect_split(None, ctx)
    assert ctx.state["needs_video"] is True
    assert ctx.state["video_brief"] is not None
    assert ctx.state["video_brief"].duration_seconds == 6


def test_parses_blob_with_needs_repo_true():
    ctx = _ctx({"_architect_raw": json.dumps(_good_blob(needs_repo=True))})
    architect_split(None, ctx)
    assert ctx.state["needs_repo"] is True


# --- Robustness — markdown fences + prose around the JSON ----------------


def test_strips_markdown_fences():
    blob_str = json.dumps(_good_blob())
    ctx = _ctx({"_architect_raw": f"```json\n{blob_str}\n```"})
    architect_split(None, ctx)
    assert ctx.state["outline"].working_title == "Title"


def test_recovers_json_with_prose_around_it():
    blob_str = json.dumps(_good_blob())
    ctx = _ctx({"_architect_raw": f"Here is your plan:\n{blob_str}\nLet me know if more changes are needed."})
    architect_split(None, ctx)
    assert ctx.state["outline"].working_title == "Title"


# --- Strict structural validation -----------------------------------------


def test_empty_raw_raises():
    ctx = _ctx({"_architect_raw": ""})
    with pytest.raises(ValueError, match="no JSON"):
        architect_split(None, ctx)


def test_invalid_json_raises():
    ctx = _ctx({"_architect_raw": "{not valid json"})
    with pytest.raises(ValueError, match="JSON invalid"):
        architect_split(None, ctx)


def test_zero_sections_raises():
    blob = _good_blob()
    blob["outline"]["sections"] = []
    ctx = _ctx({"_architect_raw": json.dumps(blob)})
    with pytest.raises(ValueError, match="0 sections"):
        architect_split(None, ctx)


def test_zero_image_briefs_raises():
    blob = _good_blob()
    blob["image_briefs"] = []
    ctx = _ctx({"_architect_raw": json.dumps(blob)})
    with pytest.raises(ValueError, match="0 image_briefs"):
        architect_split(None, ctx)


def test_no_hero_image_brief_raises():
    """Drafter relies on the hero marker being above the fold; enforce it."""
    blob = _good_blob()
    blob["image_briefs"] = [
        {"position": "section_1", "description": "x", "style": "illustration", "aspect_ratio": "16:9"},
    ]
    ctx = _ctx({"_architect_raw": json.dumps(blob)})
    with pytest.raises(ValueError, match="hero"):
        architect_split(None, ctx)


# --- Defensive coercions ---------------------------------------------------


def test_more_than_4_image_briefs_truncated_with_warning(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    blob = _good_blob()
    blob["image_briefs"] = [
        {"position": f"slot_{i}", "description": "x", "style": "illustration", "aspect_ratio": "16:9"}
        for i in range(6)
    ]
    blob["image_briefs"][0]["position"] = "hero"  # ensure hero present
    ctx = _ctx({"_architect_raw": json.dumps(blob)})
    architect_split(None, ctx)
    assert len(ctx.state["image_briefs"]) == 4
    assert any("truncating to 4" in r.message for r in caplog.records)


def test_needs_video_true_but_no_video_brief_coerces_needs_video_false(caplog):
    import logging
    caplog.set_level(logging.WARNING)
    blob = _good_blob(needs_video=True)
    blob["video_brief"] = None  # inconsistent with needs_video=true
    ctx = _ctx({"_architect_raw": json.dumps(blob)})
    architect_split(None, ctx)
    assert ctx.state["needs_video"] is False
    assert ctx.state["video_brief"] is None
    assert any("coercing needs_video=False" in r.message for r in caplog.records)
