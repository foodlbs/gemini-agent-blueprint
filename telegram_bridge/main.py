"""Telegram → RequestInput bridge — Cloud Run service.

See DESIGN.v2.md §7.3.2 + §10.6 + §8.4.

Two endpoints:

  POST /telegram/webhook
      Receives Telegram callback_query OR message events. For
      callback_query: parse callback_data, look up full session_id +
      interrupt_id from Firestore, POST a FunctionResponse to the
      Agent Runtime ReasoningEngine to resume the paused session.
      For force-reply messages: capture the operator's free-text
      feedback and resume with verdict='revise'.

  POST /sweeper/escalate
      Triggered every 15 minutes by Cloud Scheduler. Queries Firestore
      for sessions paused longer than 24h, calls resume_session with
      decision='timeout' so the workflow's terminal nodes set
      cycle_outcome="*_timeout" cleanly. See §8.4.

Auth:
  - Telegram webhook is gated by `X-Telegram-Bot-Api-Secret-Token`
    header (validated against TELEGRAM_WEBHOOK_SECRET env).
  - Sweeper endpoint is gated by Cloud Run's IAM (roles/run.invoker
    bound to the scheduler SA only).
  - Outbound calls to Agent Runtime use OIDC ID tokens (Cloud Run
    metadata server).

Run locally:

    PYTHONPATH=. uv run uvicorn telegram_bridge.main:app --host 0.0.0.0 --port 8080
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests
from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


app = FastAPI(title="ai-release-pipeline-v2 Telegram bridge")


# ---------------------------------------------------------------------------
# Configuration (env-driven)
# ---------------------------------------------------------------------------


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} env var is required")
    return value


def _agent_runtime_endpoint() -> str:
    """Returns full URL of the deployed ReasoningEngine, e.g.
    https://us-west1-aiplatform.googleapis.com/v1/projects/.../reasoningEngines/123."""
    return _required_env("AGENT_RUNTIME_ENDPOINT")


def _firestore_collection() -> str:
    return os.environ.get("FIRESTORE_COLLECTION", "airel_v2_sessions")


# ---------------------------------------------------------------------------
# Lazy clients (mockable from tests via reset_clients())
# ---------------------------------------------------------------------------


_firestore_client: Any = None
_telegram_session: Any = None  # requests.Session


def _firestore() -> Any:
    global _firestore_client
    if _firestore_client is None:
        from google.cloud import firestore as _fs
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        _firestore_client = _fs.Client(project=project, database=database) if project else _fs.Client(database=database)
    return _firestore_client


def reset_clients(firestore_client: Any = None, telegram_session: Any = None) -> None:
    """Override the cached clients (used by tests)."""
    global _firestore_client, _telegram_session
    _firestore_client = firestore_client
    _telegram_session = telegram_session


# ---------------------------------------------------------------------------
# callback_data parsing (must match tools/telegram.py:callback_data)
# ---------------------------------------------------------------------------


class CallbackParts(BaseModel):
    session_prefix: str
    choice: str
    interrupt_prefix: str


def parse_callback_data(data: str) -> CallbackParts:
    parts = data.split("|", 2)
    if len(parts) != 3:
        raise ValueError(f"bad callback_data: {data!r}")
    return CallbackParts(
        session_prefix=parts[0],
        choice=parts[1],
        interrupt_prefix=parts[2],
    )


# ---------------------------------------------------------------------------
# Firestore session lookup
# ---------------------------------------------------------------------------


def lookup_session(session_prefix: str) -> Optional[dict]:
    doc = _firestore().collection(_firestore_collection()).document(session_prefix).get()
    if not doc.exists:
        return None
    data = doc.to_dict() or {}
    return data


def mark_session_terminated(session_prefix: str) -> None:
    _firestore().collection(_firestore_collection()).document(session_prefix).update({
        "terminated": True,
        "terminated_at": datetime.now(timezone.utc),
    })


def stash_pending_revise(session_prefix: str, message_id: int, interrupt_id: str) -> None:
    """Bridge sent a ForceReply prompt; remember the (message_id → interrupt_id)
    mapping so the next inbound message that replies to it can be matched."""
    _firestore().collection(_firestore_collection()).document(session_prefix).update({
        "pending_revise_id":           interrupt_id,
        "pending_revise_message_id":   message_id,
    })


def find_session_by_pending_revise_message_id(message_id: int) -> Optional[dict]:
    """When a force-reply message arrives, look up which paused session
    asked for it. Returns the doc as a dict, or None."""
    coll = _firestore().collection(_firestore_collection())
    matches = list(coll.where("pending_revise_message_id", "==", message_id).limit(1).stream())
    if not matches:
        return None
    doc = matches[0]
    data = doc.to_dict() or {}
    data["_doc_id"] = doc.id  # helper so caller can update / delete
    return data


# ---------------------------------------------------------------------------
# Resume protocol — POST FunctionResponse to Agent Runtime
# ---------------------------------------------------------------------------


def _function_name_for_interrupt(interrupt_id: str) -> str:
    """Maps the interrupt_id prefix to the HITL function-node name.
    See DESIGN.v2.md §8.3."""
    if interrupt_id.startswith("topic-gate-"):
        return "topic_gate_request"
    if interrupt_id.startswith("editor-"):
        return "editor_request"
    raise ValueError(f"unknown interrupt_id prefix: {interrupt_id!r}")


def _mint_oidc_token(audience: str) -> str:
    """Fetches an ID token for ``audience`` (the Agent Runtime hostname)
    using Cloud Run's metadata server (or ADC for local dev)."""
    import google.auth.transport.requests
    from google.oauth2 import id_token
    auth_req = google.auth.transport.requests.Request()
    return id_token.fetch_id_token(auth_req, audience)


def resume_session(
    session_id: str,
    interrupt_id: str,
    decision: str,
    feedback: Optional[str] = None,
    timeout_seconds: int = 30,
) -> dict:
    """POST a FunctionResponse to the Agent Runtime to resume the paused
    workflow. Drains the first few SSE events to confirm the resume
    landed; the workflow continues detached."""
    endpoint = _agent_runtime_endpoint().rstrip("/")
    target_url = f"{endpoint}:streamQuery?alt=sse"

    response_payload: dict[str, Any] = {"decision": decision}
    if feedback is not None:
        response_payload["feedback"] = feedback

    body = {
        "class_method": "stream_query",
        "input": {
            "user_id": "telegram-bridge",
            "session_id": session_id,
            "message": {
                "role": "user",
                "parts": [{
                    "function_response": {
                        "id":   interrupt_id,
                        "name": _function_name_for_interrupt(interrupt_id),
                        "response": response_payload,
                    },
                }],
            },
        },
    }

    # Audience for OIDC: the Vertex regional hostname (per §10.5).
    audience = endpoint.split("/v1/")[0] if "/v1/" in endpoint else endpoint
    headers = {
        "Authorization": f"Bearer {_mint_oidc_token(audience)}",
        "Content-Type":  "application/json",
    }
    with requests.post(target_url, json=body, headers=headers, stream=True, timeout=timeout_seconds) as resp:
        resp.raise_for_status()
        events_drained = 0
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                events_drained += 1
                if events_drained >= 3:
                    break
        return {"resumed": True, "events_drained": events_drained}


def post_telegram(method: str, payload: dict) -> dict:
    """POST sendMessage / answerCallbackQuery / etc. to Telegram Bot API."""
    token = _required_env("TELEGRAM_BOT_TOKEN")
    url = f"https://api.telegram.org/bot{token}/{method}"
    session = _telegram_session or requests
    resp = session.post(url, json=payload, timeout=10)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Endpoint: /telegram/webhook
# ---------------------------------------------------------------------------


@app.post("/telegram/webhook")
def telegram_webhook(
    update: dict,
    x_telegram_bot_api_secret_token: Optional[str] = Header(default=None),
) -> dict:
    expected_secret = _required_env("TELEGRAM_WEBHOOK_SECRET")
    if x_telegram_bot_api_secret_token != expected_secret:
        # Don't log the secret (it would land in Cloud Logging).
        logger.warning("Webhook rejected: missing or invalid secret token header")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid webhook secret")

    if "callback_query" in update:
        return _handle_callback_query(update["callback_query"])

    if "message" in update:
        return _handle_message(update["message"])

    # Other update kinds — ignore.
    return {"ok": True, "ignored": list(update.keys())}


def _handle_callback_query(cbq: dict) -> dict:
    """A button tap. Resolve to (session_id, interrupt_id, choice) and
    either resume immediately (approve/skip/reject) or send a ForceReply
    prompt (revise)."""
    callback_data = cbq.get("data", "")
    cbq_id = cbq.get("id", "")
    chat = cbq.get("message", {}).get("chat", {})
    chat_id = chat.get("id")

    try:
        parts = parse_callback_data(callback_data)
    except ValueError:
        logger.warning("Bad callback_data: %r", callback_data)
        _answer_callback_query(cbq_id, "Invalid button payload.")
        return {"ok": False, "reason": "bad_callback_data"}

    sess = lookup_session(parts.session_prefix)
    if not sess:
        logger.warning("No session for prefix %r", parts.session_prefix)
        _answer_callback_query(cbq_id, "This approval is no longer valid (session expired).")
        return {"ok": False, "reason": "session_expired"}

    full_session_id   = sess["session_id_full"]
    full_interrupt_id = sess["interrupt_id_full"]
    if not full_interrupt_id.startswith(parts.interrupt_prefix):
        logger.warning(
            "interrupt prefix mismatch: button=%r vs current=%r",
            parts.interrupt_prefix, full_interrupt_id,
        )
        _answer_callback_query(cbq_id, "This approval is stale (a newer one supersedes it).")
        return {"ok": False, "reason": "interrupt_prefix_mismatch"}

    if parts.choice == "revise":
        # Operator wants to revise. Send a ForceReply prompt; capture the
        # follow-up message in the next webhook call.
        prompt = post_telegram("sendMessage", {
            "chat_id": chat_id,
            "text":    "Reply to this message with your revision feedback.",
            "reply_markup": {"force_reply": True, "selective": True},
        })
        message_id = (prompt.get("result") or {}).get("message_id", 0)
        stash_pending_revise(parts.session_prefix, message_id, full_interrupt_id)
        _answer_callback_query(cbq_id, "Revise: please reply with feedback.")
        return {"ok": True, "awaiting_force_reply": True}

    # approve / skip / reject — resume immediately.
    try:
        resume_session(
            session_id=full_session_id,
            interrupt_id=full_interrupt_id,
            decision=parts.choice,
        )
        mark_session_terminated(parts.session_prefix)
        _answer_callback_query(cbq_id, f"Recorded: {parts.choice}.")
        return {"ok": True, "decision": parts.choice}
    except Exception as e:
        logger.error("resume_session failed for %s: %s", parts.session_prefix, e)
        _answer_callback_query(cbq_id, "Server error — try again or check logs.")
        raise HTTPException(status_code=500, detail=str(e))


def _handle_message(msg: dict) -> dict:
    """A regular message. Most are noise; the only ones we care about are
    replies to a ForceReply prompt that we sent (revise feedback)."""
    reply_to = msg.get("reply_to_message") or {}
    reply_to_id = reply_to.get("message_id")
    if not reply_to_id:
        return {"ok": True, "ignored": "not_a_reply"}

    sess = find_session_by_pending_revise_message_id(reply_to_id)
    if not sess:
        return {"ok": True, "ignored": "no_pending_revise"}

    feedback = msg.get("text") or ""
    full_session_id   = sess["session_id_full"]
    full_interrupt_id = sess["interrupt_id_full"]

    try:
        resume_session(
            session_id=full_session_id,
            interrupt_id=full_interrupt_id,
            decision="revise",
            feedback=feedback,
        )
        mark_session_terminated(sess["_doc_id"])
        return {"ok": True, "decision": "revise", "feedback_chars": len(feedback)}
    except Exception as e:
        logger.error("resume_session failed (revise) for %s: %s", sess["_doc_id"], e)
        raise HTTPException(status_code=500, detail=str(e))


def _answer_callback_query(callback_query_id: str, text: str) -> None:
    """Acknowledge the button tap so the spinner clears in Telegram."""
    if not callback_query_id:
        return
    try:
        post_telegram("answerCallbackQuery", {
            "callback_query_id": callback_query_id,
            "text":              text,
            "show_alert":        False,
        })
    except Exception as e:
        # Non-fatal — the resume already happened.
        logger.warning("answerCallbackQuery failed: %s", e)


# ---------------------------------------------------------------------------
# Endpoint: /sweeper/escalate
# ---------------------------------------------------------------------------


@app.post("/sweeper/escalate")
def sweeper_escalate() -> dict:
    """Find sessions paused > 24h and resume them with decision='timeout'.

    Triggered by Cloud Scheduler every 15 min. See §8.4.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    coll = _firestore().collection(_firestore_collection())

    # Filter: created_at < cutoff AND terminated == False
    from google.cloud.firestore_v1.base_query import FieldFilter
    query = coll.where(filter=FieldFilter("created_at", "<", cutoff)) \
                .where(filter=FieldFilter("terminated", "==", False)) \
                .limit(50)

    timed_out = 0
    failures = 0
    for doc in query.stream():
        data = doc.to_dict() or {}
        try:
            resume_session(
                session_id=data["session_id_full"],
                interrupt_id=data["interrupt_id_full"],
                decision="timeout",
            )
            mark_session_terminated(doc.id)
            timed_out += 1
        except Exception as e:
            failures += 1
            logger.error("sweeper failed for %s: %s", doc.id, e)

    return {"timed_out": timed_out, "failures": failures}


# ---------------------------------------------------------------------------
# Health check (Cloud Run's startup probe + manual debug)
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "ai-release-pipeline-v2-telegram"}
