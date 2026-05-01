"""Unit tests for tools/telegram.py — see DESIGN.v2.md §7.3.1.

Both post helpers do two side effects:
  1. Write a session-lookup doc to Firestore.
  2. POST sendMessage to Telegram Bot API.

We mock both boundaries (Firestore client + ``requests.post``) so tests
run offline.
"""

from unittest.mock import MagicMock, patch

import pytest

from tools import telegram
from tools.telegram import (
    DRAFT_PREVIEW_MAX_CHARS,
    callback_data,
    post_editor_review,
    post_topic_approval,
    reset_firestore,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _telegram_env(monkeypatch):
    """Provide bot token + chat ID + project for every test."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_APPROVAL_CHAT_ID", "12345")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    yield


@pytest.fixture
def mock_firestore():
    """Inject a mock Firestore client; return the doc mock for assertions."""
    doc_mock = MagicMock()
    collection_mock = MagicMock()
    collection_mock.document.return_value = doc_mock
    client_mock = MagicMock()
    client_mock.collection.return_value = collection_mock
    reset_firestore(client_mock)
    yield doc_mock
    reset_firestore(None)


@pytest.fixture
def chosen() -> dict:
    return {
        "title":     "Anthropic Skills SDK",
        "url":       "https://anthropic.com/skills",
        "source":    "anthropic",
        "score":     90,
        "rationale": "Major lab + new SDK + working code → high score.",
        "raw_summary": "A new SDK for Claude.",
    }


# ---------------------------------------------------------------------------
# callback_data encoding (§8.2)
# ---------------------------------------------------------------------------


def test_callback_data_within_64_byte_telegram_cap():
    """Telegram caps callback_data at 64 bytes. Assert worst case is under."""
    long_session  = "x" * 100  # would-be UUID, only first 8 chars used
    long_interrupt = "topic-gate-" + "y" * 200  # only first 30 chars used
    cd = callback_data(long_session, "approve", long_interrupt)
    assert len(cd.encode("utf-8")) <= 64
    # Spec from §8.2: ≤47 bytes when used with our ID lengths.
    assert len(cd.encode("utf-8")) <= 47


def test_callback_data_format_components_round_trip():
    cd = callback_data("12345678abc", "skip", "topic-gate-foo123")
    sess_pref, choice, intr_pref = cd.split("|", 2)
    assert sess_pref == "12345678"  # 8 chars
    assert choice == "skip"
    assert intr_pref == "topic-gate-foo123"  # ≤30 chars, not truncated since shorter


def test_callback_data_truncates_long_interrupt_id():
    long_iid = "x" * 100
    cd = callback_data("sess0000", "approve", long_iid)
    _, _, intr_pref = cd.split("|", 2)
    assert len(intr_pref) == 30


# ---------------------------------------------------------------------------
# post_topic_approval — happy path
# ---------------------------------------------------------------------------


def test_post_topic_approval_writes_firestore_lookup_first(mock_firestore, chosen):
    """Lookup MUST be written before the Telegram POST so the bridge has it
    available when the operator taps a button (§7.3.2)."""
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True, "result": {}}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_topic_approval(
            chosen=chosen,
            session_id="abcdef0123-full-session-id",
            interrupt_id="topic-gate-abcdef123456", user_id="test-user")

    # Firestore was called with the 8-char prefix as the doc id
    args, _ = mock_firestore.set.call_args
    doc_data = args[0]
    assert doc_data["session_id_full"]   == "abcdef0123-full-session-id"
    assert doc_data["interrupt_id_full"] == "topic-gate-abcdef123456"
    assert doc_data["terminated"] is False


def test_post_topic_approval_calls_telegram_with_two_button_keyboard(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_topic_approval(
            chosen=chosen,
            session_id="sess1234567890",
            interrupt_id="topic-gate-xyz", user_id="test-user")

    assert mock_requests.post.call_count == 1
    call = mock_requests.post.call_args
    payload = call.kwargs["json"]
    assert payload["chat_id"] == "12345"
    assert payload["parse_mode"] == "HTML"
    keyboard = payload["reply_markup"]["inline_keyboard"]
    # 2 buttons in 1 row
    assert len(keyboard) == 1
    assert len(keyboard[0]) == 2
    labels = [btn["text"] for btn in keyboard[0]]
    assert any("Approve" in l for l in labels)
    assert any("Skip"    in l for l in labels)


def test_post_topic_approval_message_contains_required_fields(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_topic_approval(
            chosen=chosen, session_id="s", interrupt_id="i", user_id="test-user")
    text = mock_requests.post.call_args.kwargs["json"]["text"]
    assert chosen["title"] in text
    assert chosen["url"]   in text
    assert chosen["source"] in text
    assert str(chosen["score"]) in text
    assert chosen["rationale"] in text


def test_post_topic_approval_html_escapes_user_content(mock_firestore):
    """HTML chars in title MUST be escaped — the chosen_release source is
    untrusted (came from polling external sites)."""
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_topic_approval(
            chosen={"title": "<script>alert(1)</script>", "url": "https://x", "source": "arxiv", "score": 80},
            session_id="s", interrupt_id="i", user_id="test-user",
        )
    text = mock_requests.post.call_args.kwargs["json"]["text"]
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_post_topic_approval_callback_data_under_cap_for_long_url(mock_firestore):
    long_url = "https://example.com/" + "x" * 300
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_topic_approval(
            chosen={"title": "T", "url": long_url, "source": "arxiv", "score": 80},
            session_id="abcdef01-session-uuid-rest",
            interrupt_id="topic-gate-" + "y" * 100, user_id="test-user")
    keyboard = mock_requests.post.call_args.kwargs["json"]["reply_markup"]["inline_keyboard"]
    for row in keyboard:
        for btn in row:
            assert len(btn["callback_data"].encode("utf-8")) <= 64


def test_post_topic_approval_raises_when_bot_token_missing(monkeypatch, mock_firestore, chosen):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN")
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        post_topic_approval(chosen=chosen, session_id="s", interrupt_id="i", user_id="test-user")


def test_post_topic_approval_raises_when_chat_id_missing(monkeypatch, mock_firestore, chosen):
    monkeypatch.delenv("TELEGRAM_APPROVAL_CHAT_ID")
    with pytest.raises(RuntimeError, match="TELEGRAM_APPROVAL_CHAT_ID"):
        post_topic_approval(chosen=chosen, session_id="s", interrupt_id="i", user_id="test-user")


# ---------------------------------------------------------------------------
# post_editor_review — happy path + conditional fields
# ---------------------------------------------------------------------------


def test_post_editor_review_writes_firestore_lookup(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_editor_review(
            chosen=chosen,
            draft_preview="# Draft preview\nHello world",
            image_urls=["https://example.com/img1.png"],
            video_url=None, repo_url=None,
            session_id="abcdef0123-full-uuid",
            interrupt_id="editor-abcdef01-0", user_id="test-user")
    args, _ = mock_firestore.set.call_args
    assert args[0]["session_id_full"]   == "abcdef0123-full-uuid"
    assert args[0]["interrupt_id_full"] == "editor-abcdef01-0"


def _editor_call_payload(mock_requests):
    """post_editor_review now uses sendDocument (multipart). Extract the
    decoded reply_markup + caption from the call's `data` kwarg."""
    import json as _json
    data = mock_requests.post.call_args.kwargs["data"]
    return {
        "caption":      data["caption"],
        "reply_markup": _json.loads(data["reply_markup"]),
        "files":        mock_requests.post.call_args.kwargs.get("files", {}),
    }


def test_post_editor_review_three_button_keyboard(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_editor_review(
            chosen=chosen,
            draft_preview="hello", image_urls=[],
            video_url=None, repo_url=None,
            session_id="s", interrupt_id="i", user_id="test-user")
    payload = _editor_call_payload(mock_requests)
    keyboard = payload["reply_markup"]["inline_keyboard"]
    flat = [btn for row in keyboard for btn in row]
    assert len(flat) == 3
    labels = [btn["text"] for btn in flat]
    assert any("Approve" in l for l in labels)
    assert any("Revise"  in l for l in labels)
    assert any("Reject"  in l for l in labels)


def test_post_editor_review_omits_video_line_when_none(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_editor_review(
            chosen=chosen,
            draft_preview="x", image_urls=["https://example.com/i.png"],
            video_url=None, repo_url="https://github.com/o/r",
            session_id="s", interrupt_id="i", user_id="test-user")
    caption = _editor_call_payload(mock_requests)["caption"]
    assert "Video:" not in caption
    assert "Repo:"  in caption


def test_post_editor_review_omits_repo_line_when_none(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_editor_review(
            chosen=chosen,
            draft_preview="x", image_urls=[],
            video_url="https://example.com/v.mp4", repo_url=None,
            session_id="s", interrupt_id="i", user_id="test-user")
    caption = _editor_call_payload(mock_requests)["caption"]
    assert "Video:" in caption
    assert "Repo:"  not in caption


def test_post_editor_review_attaches_full_draft_as_md_document(mock_firestore, chosen):
    """The full draft is now sent as a downloadable .md file — no
    truncation. The caption is short."""
    long_preview = "x" * 5000
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_editor_review(
            chosen=chosen,
            draft_preview=long_preview, image_urls=[],
            video_url=None, repo_url=None,
            session_id="s", interrupt_id="i", user_id="test-user")
    payload = _editor_call_payload(mock_requests)
    # The full draft bytes are in the multipart 'document' tuple.
    filename, content_bytes, mime = payload["files"]["document"]
    assert filename.endswith(".md")
    assert mime == "text/markdown"
    assert len(content_bytes) == 5000
    # Caption is short (Telegram's 1024-char limit) and references the file.
    assert len(payload["caption"]) <= 1024
    assert "Editor review" in payload["caption"]


def test_post_editor_review_callback_data_includes_iteration_in_interrupt(mock_firestore, chosen):
    """interrupt_id format ``editor-<sess>-<iter>`` per §6.9.1 — this test
    documents that the callback_data carries the iteration discriminator."""
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.json.return_value = {"ok": True}
        mock_requests.post.return_value.raise_for_status.return_value = None
        post_editor_review(
            chosen=chosen,
            draft_preview="x", image_urls=[],
            video_url=None, repo_url=None,
            session_id="s", interrupt_id="editor-abc12345-2", user_id="test-user")
    keyboard = _editor_call_payload(mock_requests)["reply_markup"]["inline_keyboard"]
    flat = [btn for row in keyboard for btn in row]
    for btn in flat:
        # Iteration suffix must survive the 30-char prefix truncation.
        assert "editor-abc12345-2" in btn["callback_data"]


# ---------------------------------------------------------------------------
# Error propagation (§12.2 — no retry in v2)
# ---------------------------------------------------------------------------


def test_post_topic_approval_propagates_telegram_5xx(mock_firestore, chosen):
    with patch("tools.telegram.requests") as mock_requests:
        mock_requests.post.return_value.raise_for_status.side_effect = (
            __import__("requests").HTTPError("503 Service Unavailable")
        )
        with pytest.raises(__import__("requests").HTTPError):
            post_topic_approval(chosen=chosen, session_id="s", interrupt_id="i", user_id="test-user")


def test_post_topic_approval_propagates_firestore_error(chosen):
    """If Firestore write fails, the function fails fast and Telegram is
    NOT called (lookup must be present before the bridge can resolve)."""
    failing_client = MagicMock()
    failing_client.collection.return_value.document.return_value.set.side_effect = (
        RuntimeError("firestore unavailable")
    )
    reset_firestore(failing_client)
    try:
        with patch("tools.telegram.requests") as mock_requests:
            with pytest.raises(RuntimeError, match="firestore unavailable"):
                post_topic_approval(chosen=chosen, session_id="s", interrupt_id="i", user_id="test-user")
            # Telegram MUST NOT be called if Firestore failed first.
            assert mock_requests.post.call_count == 0
    finally:
        reset_firestore(None)
