"""Unit tests for nodes/publisher.py — image URL injection + Memory Bank fact.

Per DESIGN.v2.md §6.11.
"""

from unittest.mock import MagicMock, patch

from shared.models import (
    Draft,
    ImageAsset,
    StarterRepo,
    VideoAsset,
)

from nodes.publisher import publisher


def _ctx(state: dict, session_id: str = "abcdef0123-uuid-rest") -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.session.id = session_id
    return ctx


def _chosen() -> dict:
    return {
        "title":     "Anthropic Skills SDK",
        "url":       "https://anthropic.com/skills",
        "source":    "anthropic",
    }


def _img(position: str, url: str = None) -> ImageAsset:
    return ImageAsset(
        position=position,
        url=url or f"https://gcs/{position}.png",
        alt_text=f"alt for {position}",
        aspect_ratio="16:9",
    )


# --- Image marker injection -----------------------------------------------


def test_replaces_image_markers_with_url_keyed_by_position():
    md = "# Title\n<!--IMG:hero-->\n## Section 1\nBody\n<!--IMG:section_1-->\nMore body"
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": md,
        "image_assets": [_img("hero"), _img("section_1")],
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact"):
        publisher(None, ctx)
    final = ctx.state["final_markdown"]
    assert "<!--IMG:hero-->" not in final
    assert "<!--IMG:section_1-->" not in final
    assert "![alt for hero](https://gcs/hero.png)" in final
    assert "![alt for section_1](https://gcs/section_1.png)" in final


def test_drops_image_marker_for_position_without_asset(caplog):
    """Per §6.11 — silent drop + warning log if a position has no asset."""
    import logging
    caplog.set_level(logging.WARNING)
    md = "# Title\n<!--IMG:hero-->\n<!--IMG:section_99-->"  # section_99 has no asset
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": md,
        "image_assets": [_img("hero")],  # only hero
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact"):
        publisher(None, ctx)
    final = ctx.state["final_markdown"]
    assert "<!--IMG:section_99-->" not in final
    assert "![alt for hero]" in final
    assert any("section_99" in r.message for r in caplog.records)


# --- Video marker injection -----------------------------------------------


def test_video_marker_becomes_gif_plus_mp4_link_when_video_present():
    md = "# Title\n<!--IMG:hero-->\n<!--VID:hero-->"
    video = VideoAsset(
        mp4_url="https://gcs/v.mp4",
        gif_url="https://gcs/v.gif",
        poster_url="https://gcs/p.jpg",
        duration_seconds=6,
    )
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": md,
        "image_assets": [_img("hero")],
        "video_asset": video,
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact"):
        publisher(None, ctx)
    final = ctx.state["final_markdown"]
    assert "https://gcs/v.gif" in final
    assert "https://gcs/v.mp4" in final
    assert "<!--VID:hero-->" not in final


def test_video_marker_dropped_when_video_asset_none():
    md = "# Title\n<!--IMG:hero-->\n<!--VID:hero-->"
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": md,
        "image_assets": [_img("hero")],
        "video_asset": None,
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact"):
        publisher(None, ctx)
    assert "<!--VID:" not in ctx.state["final_markdown"]


# --- Bundle + Memory Bank --------------------------------------------------


def test_bundle_uploaded_to_gcs_with_correct_slug():
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": "# T\n<!--IMG:hero-->",
        "image_assets": [_img("hero")],
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json") as mock_upload, \
         patch("tools.memory.memory_bank_add_fact"):
        publisher(None, ctx)
    call = mock_upload.call_args
    # cycle_id is first 8 chars of session_id
    assert "abcdef01/article_bundle.json" in call.kwargs["slug"]
    assert call.kwargs["content_type"] == "application/json"


def test_memory_bank_covered_fact_written_with_correct_metadata():
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": "# T\n<!--IMG:hero-->",
        "image_assets": [_img("hero")],
        "starter_repo": StarterRepo(url="https://github.com/o/r", files_committed=[], sha="abc"),
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact") as mock_add:
        publisher(None, ctx)
    assert mock_add.call_count == 1
    call = mock_add.call_args
    assert call.kwargs["scope"] == "ai_release_pipeline"
    md = call.kwargs["metadata"]
    assert md["type"] == "covered"
    assert md["release_url"] == "https://anthropic.com/skills"
    assert md["release_source"] == "anthropic"
    assert md["bundle_url"] == "https://gcs/bundle.json"
    assert md["starter_repo"] == "https://github.com/o/r"


def test_memory_bank_failure_does_not_fail_cycle():
    """Per §6.11 + §12.3 — Memory Bank write failure: article still
    published, memory_bank_recorded=False, cycle still ends 'published'."""
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": "# T\n<!--IMG:hero-->",
        "image_assets": [_img("hero")],
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact", side_effect=RuntimeError("MB down")):
        event = publisher(None, ctx)
    assert ctx.state["cycle_outcome"] == "published"
    assert ctx.state["memory_bank_recorded"] is False
    assert event.output["outcome"] == "published"


def test_cycle_outcome_set_to_published():
    ctx = _ctx({
        "chosen_release": _chosen(),
        "draft": "# T\n<!--IMG:hero-->",
        "image_assets": [_img("hero")],
    })
    with patch("nodes.publisher.upload_to_gcs", return_value="https://gcs/bundle.json"), \
         patch("tools.memory.memory_bank_add_fact"):
        publisher(None, ctx)
    assert ctx.state["cycle_outcome"] == "published"
    assert ctx.state["final_markdown"] is not None
    assert ctx.state["asset_bundle_url"] == "https://gcs/bundle.json"
