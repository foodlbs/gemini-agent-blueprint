"""Tests for the Asset Agent: GCS upload, Imagen/Veo, ffmpeg post-processing,
and the two ``LlmAgent`` wirings + the ``ParallelAgent`` composition.

Coverage maps to the user's required scenarios from DESIGN.md §7:
- "Fixture brief + real GCS bucket → cover image, URL reachable" — provided
  as an integration test that skips unless ``GCS_ASSETS_BUCKET`` and
  credentials are present, plus mocked tests that always run.
- "Video with needs_video True → one short video" — verified via
  ``generate_video`` mock test (returns bytes within the 8-second cap).
- "Video with needs_video False → no Veo call" — verified via the video
  agent's first-line early-exit instruction (instruction-as-contract).
"""

import os
import urllib.request
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from tools import gcs, imagen, veo, video_processing


def _tool_name(t) -> str:
    return getattr(t, "__name__", None) or getattr(t, "name", "") or t.__class__.__name__


# --- tools/gcs.py ----------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch):
    """Each test starts with no cached singletons."""
    gcs.reset_client(None)
    imagen.reset_client(None)
    veo.reset_client(None)
    yield
    gcs.reset_client(None)
    imagen.reset_client(None)
    veo.reset_client(None)


def test_upload_to_gcs_returns_public_url_for_bucket(monkeypatch):
    monkeypatch.setenv("GCS_ASSETS_BUCKET", "test-bucket")
    fake_blob = MagicMock()
    fake_bucket = MagicMock()
    fake_bucket.blob.return_value = fake_blob
    fake_client = MagicMock()
    fake_client.bucket.return_value = fake_bucket
    gcs.reset_client(fake_client)

    url = gcs.upload_to_gcs(b"data", "image/png", "image-cover.png")

    assert url == "https://storage.googleapis.com/test-bucket/image-cover.png"
    fake_client.bucket.assert_called_once_with("test-bucket")
    fake_bucket.blob.assert_called_once_with("image-cover.png")
    fake_blob.upload_from_string.assert_called_once_with(
        b"data", content_type="image/png", timeout=gcs.UPLOAD_TIMEOUT_SECONDS
    )


def test_upload_to_gcs_raises_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("GCS_ASSETS_BUCKET", raising=False)
    with pytest.raises(RuntimeError, match="GCS_ASSETS_BUCKET"):
        gcs.upload_to_gcs(b"data", "image/png", "x.png")


@pytest.mark.skipif(
    not os.environ.get("GCS_ASSETS_BUCKET"),
    reason="needs GCS_ASSETS_BUCKET env var and GCP credentials",
)
def test_upload_to_gcs_real_bucket_returns_reachable_url():
    """[User-required scenario 1, integration tier] Upload to a real bucket
    and confirm the URL is publicly reachable.

    Skipped when ``GCS_ASSETS_BUCKET`` isn't set (i.e., in CI without
    credentials). On a developer machine with the bucket provisioned via
    ``deploy/gcs_bucket.tf``, this exercises the full path.
    """
    payload = b"asset-agent-integration-test"
    url = gcs.upload_to_gcs(payload, "text/plain", "_test/integration.txt")
    with urllib.request.urlopen(url, timeout=15) as resp:
        body = resp.read()
    assert body == payload


# --- tools/imagen.py -------------------------------------------------------


def test_generate_image_calls_vertex_with_aspect_ratio_and_count(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    fake_image = SimpleNamespace(image=SimpleNamespace(image_bytes=b"PNG_BYTES"))
    fake_response = SimpleNamespace(generated_images=[fake_image])
    fake_client = MagicMock()
    fake_client.models.generate_images.return_value = fake_response
    imagen.reset_client(fake_client)

    result = imagen.generate_image(
        prompt="hero shot of stacked skill bundles",
        aspect_ratio="16:9",
        style="illustration",
    )

    assert result == b"PNG_BYTES"
    call = fake_client.models.generate_images.call_args
    assert call.kwargs["model"] == imagen.DEFAULT_MODEL
    assert "stacked skill bundles" in call.kwargs["prompt"]
    # Style hint appended to prompt
    assert "editorial illustration" in call.kwargs["prompt"]
    cfg = call.kwargs["config"]
    assert cfg.aspect_ratio == "16:9"
    assert cfg.number_of_images == 1


def test_generate_image_raises_when_model_returns_no_images(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    fake_client = MagicMock()
    fake_client.models.generate_images.return_value = SimpleNamespace(generated_images=[])
    imagen.reset_client(fake_client)

    with pytest.raises(RuntimeError, match="no images"):
        imagen.generate_image("anything", "16:9", "photoreal")


# --- tools/veo.py ----------------------------------------------------------


def _ready_operation(video_bytes: bytes = b"MP4_BYTES"):
    """Build a mock long-running operation that's already done."""
    op = MagicMock()
    op.done = True
    op.error = None
    op.response = SimpleNamespace(
        generated_videos=[
            SimpleNamespace(video=SimpleNamespace(video_bytes=video_bytes))
        ]
    )
    return op


def test_generate_video_returns_mp4_bytes(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    fake_client = MagicMock()
    fake_client.models.generate_videos.return_value = _ready_operation(b"MP4_BYTES")
    veo.reset_client(fake_client)

    result = veo.generate_video("demo", duration_seconds=6, aspect_ratio="16:9")
    assert result == b"MP4_BYTES"

    call = fake_client.models.generate_videos.call_args
    assert call.kwargs["model"] == veo.DEFAULT_MODEL
    cfg = call.kwargs["config"]
    assert cfg.duration_seconds == 6
    assert cfg.aspect_ratio == "16:9"


def test_generate_video_clamps_duration_to_8_seconds(monkeypatch):
    """[Indirect coverage of "needs_video True → one short test video"]
    Even if the brief asks for 12s, Veo Fast is capped at 8s per DESIGN.md §7b."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    fake_client = MagicMock()
    fake_client.models.generate_videos.return_value = _ready_operation()
    veo.reset_client(fake_client)

    veo.generate_video("demo", duration_seconds=12, aspect_ratio="16:9")
    cfg = fake_client.models.generate_videos.call_args.kwargs["config"]
    assert cfg.duration_seconds == veo.MAX_DURATION_SECONDS == 8


def test_generate_video_raises_when_no_videos_returned(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    fake_op = MagicMock()
    fake_op.done = True
    fake_op.error = None
    fake_op.response = SimpleNamespace(generated_videos=[])
    fake_client = MagicMock()
    fake_client.models.generate_videos.return_value = fake_op
    veo.reset_client(fake_client)

    with pytest.raises(RuntimeError, match="no videos"):
        veo.generate_video("demo")


def test_generate_video_polls_until_done(monkeypatch):
    """The operation may not be done on first inspection — verify polling."""
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setattr(veo.time, "sleep", lambda s: None)  # don't actually wait

    pending_op = MagicMock()
    pending_op.done = False
    ready_op = _ready_operation()

    fake_client = MagicMock()
    fake_client.models.generate_videos.return_value = pending_op
    fake_client.operations.get.return_value = ready_op
    veo.reset_client(fake_client)

    result = veo.generate_video("demo", duration_seconds=6)
    assert result == b"MP4_BYTES"
    fake_client.operations.get.assert_called()


# --- tools/video_processing.py --------------------------------------------


def test_convert_to_gif_invokes_ffmpeg_pipeline(monkeypatch):
    """Mock the ``ffmpeg.input(...)`` chain. When ``run`` is called, write
    expected bytes to the chain's captured output path; the function reads
    them back and returns them."""
    captured = {}

    class FakeChain:
        def __init__(self, in_path):
            captured["input"] = in_path
            self.out_path = None

        def filter(self, name, *args, **kwargs):
            captured.setdefault("filters", []).append((name, args, kwargs))
            return self

        def output(self, path, **kwargs):
            self.out_path = path
            captured["output"] = path
            return self

        def overwrite_output(self):
            return self

        def run(self, **kwargs):
            with open(self.out_path, "wb") as f:
                f.write(b"FAKE_GIF_BYTES")

    monkeypatch.setattr(
        video_processing.ffmpeg, "input",
        lambda path, **kw: FakeChain(path),
    )

    result = video_processing.convert_to_gif(b"FAKE_MP4")
    assert result == b"FAKE_GIF_BYTES"
    assert captured["input"].endswith(".mp4")
    assert captured["output"].endswith(".gif")
    # fps + scale filters are applied
    filter_names = {f[0] for f in captured.get("filters", [])}
    assert "fps" in filter_names
    assert "scale" in filter_names


def test_extract_first_frame_invokes_ffmpeg_pipeline(monkeypatch):
    captured = {}

    class FakeChain:
        def __init__(self, in_path):
            captured["input"] = in_path
            self.out_path = None

        def output(self, path, **kwargs):
            self.out_path = path
            captured["output"] = path
            captured["output_kwargs"] = kwargs
            return self

        def overwrite_output(self):
            return self

        def run(self, **kwargs):
            with open(self.out_path, "wb") as f:
                f.write(b"FAKE_JPG_BYTES")

    monkeypatch.setattr(
        video_processing.ffmpeg, "input",
        lambda path, **kw: FakeChain(path),
    )

    result = video_processing.extract_first_frame(b"FAKE_MP4")
    assert result == b"FAKE_JPG_BYTES"
    assert captured["output"].endswith(".jpg")
    # Only one frame, JPEG codec
    assert captured["output_kwargs"].get("vframes") == 1
    assert captured["output_kwargs"].get("vcodec") == "mjpeg"


def test_video_processing_cleans_up_temp_files(monkeypatch):
    """convert_to_gif must remove its input/output temp files even on success."""
    paths_seen = []

    class FakeChain:
        def __init__(self, in_path):
            paths_seen.append(in_path)
            self.out_path = None
        def filter(self, *a, **kw):
            return self
        def output(self, path, **kwargs):
            self.out_path = path
            paths_seen.append(path)
            return self
        def overwrite_output(self):
            return self
        def run(self, **kw):
            with open(self.out_path, "wb") as f:
                f.write(b"GIF")

    monkeypatch.setattr(
        video_processing.ffmpeg, "input",
        lambda path, **kw: FakeChain(path),
    )

    video_processing.convert_to_gif(b"MP4")
    for p in paths_seen:
        assert not os.path.exists(p), f"temp file {p} not cleaned up"


# --- agents/asset/image.py -------------------------------------------------


def test_image_asset_agent_wiring():
    from agents.asset.image import image_asset_agent
    assert image_asset_agent.name == "image_asset_agent"
    assert image_asset_agent.model == "gemini-3.1-flash-lite-preview"
    assert image_asset_agent.output_key == "image_assets"
    names = {_tool_name(t) for t in image_asset_agent.tools}
    assert names == {"generate_image", "upload_to_gcs"}


def test_image_asset_agent_first_line_is_chosen_release_early_exit():
    from agents.asset.image import image_asset_agent
    first = image_asset_agent.instruction.splitlines()[0]
    assert first == "If state['chosen_release'] is None, end your turn immediately without using tools."


# --- agents/asset/video.py -------------------------------------------------


def test_video_asset_agent_wiring():
    from agents.asset.video import video_asset_agent
    assert video_asset_agent.name == "video_asset_agent"
    assert video_asset_agent.model == "gemini-3.1-flash-lite-preview"
    assert video_asset_agent.output_key == "video_asset"
    names = {_tool_name(t) for t in video_asset_agent.tools}
    assert names == {
        "generate_video", "convert_to_gif", "extract_first_frame", "upload_to_gcs"
    }


def test_video_asset_agent_first_line_is_chosen_release_early_exit():
    """[Step 11] The pipeline-wide early-exit prepend per DESIGN.md
    "Early-exit pattern" applies to the video agent: line 1 is the
    chosen_release check, line 3 is DESIGN.md §7b's needs_video check
    (kept verbatim as a second guard)."""
    from agents.asset.video import video_asset_agent
    lines = [
        line for line in video_asset_agent.instruction.splitlines() if line.strip()
    ]
    assert lines[0] == (
        "If state['chosen_release'] is None, end your turn immediately "
        "without using tools."
    )
    assert lines[1] == (
        "If state['needs_video'] is False or state['video_brief'] is None, "
        "end your turn immediately."
    )


# --- ParallelAgent composition --------------------------------------------


def test_asset_agent_runs_image_and_video_in_parallel():
    from main import asset_agent
    from agents.asset.image import image_asset_agent
    from agents.asset.video import video_asset_agent

    assert asset_agent.name == "asset_agent"
    sub_names = {a.name for a in asset_agent.sub_agents}
    assert sub_names == {"image_asset_agent", "video_asset_agent"}
    assert image_asset_agent in asset_agent.sub_agents
    assert video_asset_agent in asset_agent.sub_agents


def test_asset_agent_sub_agents_write_disjoint_state_keys():
    """Disjoint output_keys mean the ParallelAgent's state merge is conflict-free."""
    from main import asset_agent
    keys = {getattr(a, "output_key", None) for a in asset_agent.sub_agents}
    assert keys == {"image_assets", "video_asset"}
