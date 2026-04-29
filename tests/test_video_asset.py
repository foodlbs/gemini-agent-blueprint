"""Unit tests for nodes/video_asset.py — the v2 Bug B2 regression suite.

Per DESIGN.v2.md §6.7.2. This module replaced v1's video_asset_agent
LlmAgent because that agent ignored its prompt-based early-exit guard
and called Veo against skipped releases.

The function-node implementation enforces the guard in CODE — no LLM
in the call path means there's no "ignore the prompt" failure mode
left.
"""

from unittest.mock import MagicMock, patch

from shared.models import VideoBrief

from nodes.video_asset import video_asset_or_skip


def _ctx(state: dict, session_id: str = "abcdef0123-uuid-rest") -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    ctx.session.id = session_id
    return ctx


# --- Skip path (no LLM, no Veo, no GCS) ------------------------------------


def test_skip_when_needs_video_is_false():
    """The most important test: needs_video=False → ZERO downstream calls."""
    ctx = _ctx({"needs_video": False, "video_brief": None})
    with patch("nodes.video_asset.generate_video") as mock_veo, \
         patch("nodes.video_asset.upload_to_gcs") as mock_gcs:
        event = video_asset_or_skip(None, ctx)

    assert event.output["skipped"] is True
    assert event.output["reason"] == "needs_video=False"
    assert ctx.state["video_asset"] is None
    assert mock_veo.call_count == 0
    assert mock_gcs.call_count == 0


def test_skip_when_needs_video_key_missing():
    """Per Pydantic default in PipelineState — needs_video defaults to False."""
    ctx = _ctx({})
    with patch("nodes.video_asset.generate_video") as mock_veo:
        event = video_asset_or_skip(None, ctx)
    assert event.output["skipped"] is True
    assert mock_veo.call_count == 0


def test_skip_when_needs_video_true_but_video_brief_none(caplog):
    """Defensive — architect_split should have coerced needs_video=False if
    no brief; but if state is inconsistent, skip + log."""
    import logging
    caplog.set_level(logging.WARNING)
    ctx = _ctx({"needs_video": True, "video_brief": None})
    with patch("nodes.video_asset.generate_video") as mock_veo:
        event = video_asset_or_skip(None, ctx)
    assert event.output["skipped"] is True
    assert mock_veo.call_count == 0
    assert any("video_brief is None" in r.message for r in caplog.records)


# --- Bug B2 regression — defense in depth ----------------------------------


def test_does_not_call_veo_when_needs_video_false_even_if_video_brief_present():
    """Bug B2 regression: the guard checks needs_video FIRST, so even a
    leftover video_brief from an inconsistent state can't trigger Veo."""
    brief = VideoBrief(description="x", style="y", duration_seconds=6, aspect_ratio="16:9")
    ctx = _ctx({"needs_video": False, "video_brief": brief})
    with patch("nodes.video_asset.generate_video") as mock_veo, \
         patch("nodes.video_asset.upload_to_gcs") as mock_gcs:
        event = video_asset_or_skip(None, ctx)
    assert mock_veo.call_count == 0, (
        "Bug B2 regression — Veo MUST NOT be called when needs_video=False, "
        "regardless of video_brief presence"
    )
    assert mock_gcs.call_count == 0
    assert ctx.state["video_asset"] is None


# --- Happy path ------------------------------------------------------------


def test_full_path_when_needs_video_true():
    brief = VideoBrief(
        description="A 6-second cinematic intro",
        style="cinematic",
        duration_seconds=6,
        aspect_ratio="16:9",
    )
    ctx = _ctx({"needs_video": True, "video_brief": brief})

    with patch("nodes.video_asset.generate_video", return_value=b"FAKE_MP4_BYTES") as mock_veo, \
         patch("nodes.video_asset.upload_to_gcs", return_value="https://gcs/v2/abcdef01/video.mp4") as mock_gcs:
        event = video_asset_or_skip(None, ctx)

    assert event.output["skipped"] is False
    assert event.output["duration_seconds"] == 6
    assert mock_veo.call_count == 1
    # v2 ships MP4-only per §7.7 Q8 — only ONE upload (the MP4); no
    # convert_to_gif / extract_first_frame derivations.
    assert mock_gcs.call_count == 1
    asset = ctx.state["video_asset"]
    assert asset.mp4_url == "https://gcs/v2/abcdef01/video.mp4"
    # gif_url and poster_url default to the MP4 URL in v2 (no derivation).
    assert asset.gif_url == asset.mp4_url
    assert asset.poster_url == asset.mp4_url
    assert asset.duration_seconds == 6


# --- Failure modes ---------------------------------------------------------


def test_veo_error_does_not_kill_cycle(caplog):
    """Per §6.7.2 — Veo failure leaves video_asset=None, returns event,
    pipeline continues."""
    import logging
    caplog.set_level(logging.WARNING)
    brief = VideoBrief(description="x", style="y", duration_seconds=6, aspect_ratio="16:9")
    ctx = _ctx({"needs_video": True, "video_brief": brief})

    with patch("nodes.video_asset.generate_video", side_effect=RuntimeError("Veo 404")):
        event = video_asset_or_skip(None, ctx)

    assert event.output["skipped"] is True
    assert "veo_error" in event.output["reason"]
    assert ctx.state["video_asset"] is None
    assert any("Veo generation failed" in r.message for r in caplog.records)


def test_veo_calls_use_brief_parameters():
    """Verify the brief's description / duration / aspect_ratio are passed through."""
    brief = VideoBrief(
        description="Purple cube rotating",
        style="3d",
        duration_seconds=8,
        aspect_ratio="4:3",
    )
    ctx = _ctx({"needs_video": True, "video_brief": brief})
    with patch("nodes.video_asset.generate_video", return_value=b"BYTES") as mock_veo, \
         patch("nodes.video_asset.upload_to_gcs", return_value="url"):
        video_asset_or_skip(None, ctx)
    call = mock_veo.call_args
    assert call.kwargs["prompt"] == "Purple cube rotating"
    assert call.kwargs["duration_seconds"] == 8
    assert call.kwargs["aspect_ratio"] == "4:3"
