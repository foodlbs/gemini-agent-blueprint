"""Tests for telegram_bridge/main.py.

The bridge has Firestore + Telegram + Agent Runtime as external surfaces.
Tests mock all three at the module level via reset_clients()."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Add telegram_bridge/ to sys.path so we can import main directly.
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "telegram_bridge"
))

# Set required env vars BEFORE import so module-level reads succeed.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("AGENT_RUNTIME_ENDPOINT",
    "https://us-west1-aiplatform.googleapis.com/v1/projects/test/locations/us-west1/reasoningEngines/123")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")

import main as bridge  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402


client = TestClient(bridge.app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_firestore():
    """Inject a mock Firestore client; yield the doc/coll mocks for assertions."""
    doc_mock = MagicMock()
    doc_mock.exists = True
    doc_mock.to_dict.return_value = {
        "session_id_full":   "abcdef0123-full-uuid",
        "interrupt_id_full": "topic-gate-abc12345",
        "terminated":        False,
    }

    collection_mock = MagicMock()
    collection_mock.document.return_value.get.return_value = doc_mock
    collection_mock.document.return_value.update = MagicMock()

    client_mock = MagicMock()
    client_mock.collection.return_value = collection_mock

    bridge.reset_clients(firestore_client=client_mock)
    yield {"client": client_mock, "collection": collection_mock, "doc": doc_mock}
    bridge.reset_clients(firestore_client=None)


@pytest.fixture(autouse=True)
def patch_oidc_token():
    """Avoid real OIDC token mints in tests."""
    with patch.object(bridge, "_mint_oidc_token", return_value="fake-id-token"):
        yield


# ---------------------------------------------------------------------------
# callback_data parsing
# ---------------------------------------------------------------------------


def test_parse_callback_data_three_parts():
    parts = bridge.parse_callback_data("abc12345|approve|topic-gate-foo123")
    assert parts.session_prefix == "abc12345"
    assert parts.choice == "approve"
    assert parts.interrupt_prefix == "topic-gate-foo123"


def test_parse_callback_data_rejects_malformed():
    with pytest.raises(ValueError, match="bad callback_data"):
        bridge.parse_callback_data("not-piped")


# ---------------------------------------------------------------------------
# function_name resolution from interrupt_id prefix
# ---------------------------------------------------------------------------


def test_function_name_for_topic_gate():
    assert bridge._function_name_for_interrupt("topic-gate-abc123") == "topic_gate_request"


def test_function_name_for_editor():
    assert bridge._function_name_for_interrupt("editor-abc12345-2") == "editor_request"


def test_function_name_for_unknown_prefix_raises():
    with pytest.raises(ValueError, match="unknown interrupt_id prefix"):
        bridge._function_name_for_interrupt("garbage-prefix-xyz")


# ---------------------------------------------------------------------------
# Webhook auth
# ---------------------------------------------------------------------------


def test_webhook_rejects_missing_secret_header():
    resp = client.post("/telegram/webhook", json={"message": {}})
    assert resp.status_code == 403


def test_webhook_rejects_wrong_secret():
    resp = client.post(
        "/telegram/webhook",
        json={"message": {}},
        headers={"x-telegram-bot-api-secret-token": "wrong-secret"},
    )
    assert resp.status_code == 403


def test_webhook_accepts_correct_secret_for_unknown_update():
    resp = client.post(
        "/telegram/webhook",
        json={"unsupported_kind": {}},
        headers={"x-telegram-bot-api-secret-token": "test-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["ignored"] == ["unsupported_kind"]


# ---------------------------------------------------------------------------
# callback_query handling
# ---------------------------------------------------------------------------


def test_webhook_approve_resumes_session(fake_firestore):
    """Happy path: button tap → lookup → resume_session → mark terminated."""
    with patch.object(bridge, "resume_session", return_value={"resumed": True}) as mock_resume, \
         patch.object(bridge, "post_telegram") as mock_telegram:
        resp = client.post(
            "/telegram/webhook",
            headers={"x-telegram-bot-api-secret-token": "test-secret"},
            json={
                "callback_query": {
                    "id":   "cbq-1",
                    "data": "abcdef01|approve|topic-gate-abc12345",
                    "message": {"chat": {"id": 12345}},
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "approve"
    mock_resume.assert_called_once()
    call = mock_resume.call_args.kwargs
    assert call["session_id"]   == "abcdef0123-full-uuid"
    assert call["interrupt_id"] == "topic-gate-abc12345"
    assert call["decision"]     == "approve"


def test_webhook_callback_with_expired_session(fake_firestore):
    """If Firestore has no doc for the session_prefix, return ok with reason."""
    fake_firestore["doc"].exists = False
    with patch.object(bridge, "post_telegram") as mock_telegram:
        resp = client.post(
            "/telegram/webhook",
            headers={"x-telegram-bot-api-secret-token": "test-secret"},
            json={
                "callback_query": {
                    "id":   "cbq-1",
                    "data": "abcdef01|approve|topic-gate-abc12345",
                    "message": {"chat": {"id": 12345}},
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["reason"] == "session_expired"


def test_webhook_callback_with_interrupt_prefix_mismatch(fake_firestore):
    """Stale buttons (newer pause supersedes) should be rejected gracefully."""
    fake_firestore["doc"].to_dict.return_value = {
        "session_id_full":   "abcdef0123-full-uuid",
        "interrupt_id_full": "topic-gate-XYZ-NEWER",  # current
        "terminated":        False,
    }
    with patch.object(bridge, "post_telegram"):
        resp = client.post(
            "/telegram/webhook",
            headers={"x-telegram-bot-api-secret-token": "test-secret"},
            json={
                "callback_query": {
                    "id":   "cbq-1",
                    "data": "abcdef01|approve|topic-gate-OLD",  # stale prefix
                    "message": {"chat": {"id": 12345}},
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["reason"] == "interrupt_prefix_mismatch"


def test_webhook_revise_sends_force_reply_does_not_resume_yet(fake_firestore):
    """Revise button → ForceReply prompt + Firestore stash; no resume."""
    with patch.object(bridge, "resume_session") as mock_resume, \
         patch.object(bridge, "post_telegram", return_value={"result": {"message_id": 42}}) as mock_tg:
        resp = client.post(
            "/telegram/webhook",
            headers={"x-telegram-bot-api-secret-token": "test-secret"},
            json={
                "callback_query": {
                    "id":   "cbq-r",
                    "data": "abcdef01|revise|topic-gate-abc12345",
                    "message": {"chat": {"id": 12345}},
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["awaiting_force_reply"] is True
    # resume_session NOT called yet — we wait for the operator's reply.
    assert mock_resume.call_count == 0
    # Two Telegram POSTs: ForceReply prompt + answerCallbackQuery ack.
    assert mock_tg.call_count >= 1


def test_webhook_message_replying_to_force_reply_resumes_with_feedback(fake_firestore):
    """A regular message that replies to our ForceReply prompt → resume(revise, feedback)."""
    # Mock the find_session_by_pending_revise_message_id query
    matching_doc = MagicMock()
    matching_doc.id = "abcdef01"
    matching_doc.to_dict.return_value = {
        "session_id_full":   "abcdef0123-full-uuid",
        "interrupt_id_full": "editor-abcdef01-1",
        "pending_revise_message_id": 42,
    }
    fake_firestore["collection"].where.return_value.where.return_value.limit.return_value.stream.return_value = iter([])
    fake_firestore["collection"].where.return_value.limit.return_value.stream.return_value = iter([matching_doc])

    with patch.object(bridge, "resume_session", return_value={"resumed": True}) as mock_resume:
        resp = client.post(
            "/telegram/webhook",
            headers={"x-telegram-bot-api-secret-token": "test-secret"},
            json={
                "message": {
                    "text": "shorten the intro by half",
                    "reply_to_message": {"message_id": 42},
                },
            },
        )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "revise"
    mock_resume.assert_called_once()
    call = mock_resume.call_args.kwargs
    assert call["decision"] == "revise"
    assert call["feedback"] == "shorten the intro by half"


def test_webhook_message_not_replying_is_ignored(fake_firestore):
    resp = client.post(
        "/telegram/webhook",
        headers={"x-telegram-bot-api-secret-token": "test-secret"},
        json={"message": {"text": "Hello bot"}},
    )
    assert resp.status_code == 200
    assert resp.json()["ignored"] == "not_a_reply"


# ---------------------------------------------------------------------------
# Sweeper endpoint
# ---------------------------------------------------------------------------


def test_sweeper_resumes_each_stale_session(fake_firestore):
    stale_doc1 = MagicMock()
    stale_doc1.id = "sess0001"
    stale_doc1.to_dict.return_value = {
        "session_id_full":   "uuid-1",
        "interrupt_id_full": "topic-gate-abc",
        "terminated":        False,
    }
    stale_doc2 = MagicMock()
    stale_doc2.id = "sess0002"
    stale_doc2.to_dict.return_value = {
        "session_id_full":   "uuid-2",
        "interrupt_id_full": "editor-uuid2-0",
        "terminated":        False,
    }
    fake_firestore["collection"].where.return_value.where.return_value.limit.return_value.stream.return_value = (
        iter([stale_doc1, stale_doc2])
    )
    with patch.object(bridge, "resume_session", return_value={"resumed": True}) as mock_resume:
        resp = client.post("/sweeper/escalate")
    assert resp.status_code == 200
    assert resp.json()["timed_out"] == 2
    assert mock_resume.call_count == 2
    for call in mock_resume.call_args_list:
        assert call.kwargs["decision"] == "timeout"


def test_sweeper_continues_on_per_session_failure(fake_firestore):
    """First session fails to resume; second succeeds. Both attempted."""
    stale_doc1 = MagicMock()
    stale_doc1.id = "sess0001"
    stale_doc1.to_dict.return_value = {"session_id_full": "u1", "interrupt_id_full": "topic-gate-x"}
    stale_doc2 = MagicMock()
    stale_doc2.id = "sess0002"
    stale_doc2.to_dict.return_value = {"session_id_full": "u2", "interrupt_id_full": "editor-u2-0"}
    fake_firestore["collection"].where.return_value.where.return_value.limit.return_value.stream.return_value = (
        iter([stale_doc1, stale_doc2])
    )
    with patch.object(
        bridge, "resume_session",
        side_effect=[RuntimeError("first sess failed"), {"resumed": True}],
    ) as mock_resume:
        resp = client.post("/sweeper/escalate")
    assert resp.status_code == 200
    assert resp.json()["timed_out"] == 1
    assert resp.json()["failures"] == 1
    assert mock_resume.call_count == 2


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


def test_health_endpoint():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
