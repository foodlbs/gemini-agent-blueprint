"""Telegram post helpers — see DESIGN.v2.md §7.3.1.

Exposes two sync functions called by the HITL function nodes
(``topic_gate_request``, ``editor_request``):

  - ``post_topic_approval(chosen, session_id, interrupt_id)``
  - ``post_editor_review(chosen, draft_preview, image_urls,
                         video_url, repo_url, session_id, interrupt_id)``

Both:
  1. Write a session-lookup doc to Firestore (collection
     ``airel_v2_sessions``, keyed by the 8-char session_id prefix). The
     bridge (telegram_bridge/) reads this doc when a button tap arrives
     to resolve the short callback_data prefixes back to full IDs.
  2. POST a Telegram message with an inline-keyboard whose
     callback_data is encoded per §8.2:
     ``f"{session_id[:8]}|{choice}|{interrupt_id[:30]}"`` (≤47 bytes).

Errors propagate. The calling HITL function nodes do NOT wrap in
try/except in v2 — failure to post means the workflow fails fast
(per §12.2 decision 1; retry-with-backoff is a v2.1 candidate).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)


TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
HTTP_TIMEOUT_SECONDS = 10
SESSION_TTL_DAYS = 7
SESSION_PREFIX_LENGTH = 8
INTERRUPT_PREFIX_LENGTH = 30
DRAFT_PREVIEW_MAX_CHARS = 500


# ---------------------------------------------------------------------------
# Lazy Firestore client (lets tests mock without import-time side effects)
# ---------------------------------------------------------------------------


_firestore_client = None


def _firestore():
    """Lazy-initialized Firestore client. Tests override via reset_firestore()."""
    global _firestore_client
    if _firestore_client is None:
        # Imported lazily so tests can mock tools.telegram._firestore wholesale
        # without dragging the full google-cloud-firestore client into the
        # import path.
        from google.cloud import firestore as _firestore_module
        database = os.environ.get("FIRESTORE_DATABASE", "(default)")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT")
        if project:
            _firestore_client = _firestore_module.Client(
                project=project, database=database
            )
        else:
            _firestore_client = _firestore_module.Client(database=database)
    return _firestore_client


def reset_firestore(client: Any = None) -> None:
    """Override / clear the cached Firestore client. Used by tests."""
    global _firestore_client
    _firestore_client = client


# ---------------------------------------------------------------------------
# callback_data encoding (§8.2)
# ---------------------------------------------------------------------------


def callback_data(session_id: str, choice: str, interrupt_id: str) -> str:
    """Encode (session_id, choice, interrupt_id) → ≤47-byte callback_data.

    Format: ``f"{session_id[:8]}|{choice}|{interrupt_id[:30]}"``. Telegram
    caps callback_data at 64 bytes; this leaves headroom for future
    additions to the choice vocabulary.
    """
    return (
        f"{session_id[:SESSION_PREFIX_LENGTH]}"
        f"|{choice}"
        f"|{interrupt_id[:INTERRUPT_PREFIX_LENGTH]}"
    )


# ---------------------------------------------------------------------------
# Session-lookup doc (§7.3.2)
# ---------------------------------------------------------------------------


def _write_session_lookup(
    session_id: str, interrupt_id: str, user_id: str,
) -> None:
    """Persist (session_prefix → full_session_id, full_interrupt_id, user_id)
    to Firestore.

    The bridge reads this doc on every button tap. One doc per session;
    the doc is overwritten when a new pause fires (only one interrupt is
    pending per session at a time — see §7.3.2 + §6.9.1).

    `user_id` is required because Vertex's session service enforces
    per-user ownership — `engine.stream_query(user_id=...)` rejects
    requests where the session doesn't belong to that user. The bridge
    uses this field to resume sessions originally created by the
    scheduler ("scheduler") or smoke tests ("smoke-test-N")."""
    prefix = session_id[:SESSION_PREFIX_LENGTH]
    now = datetime.now(timezone.utc)
    doc_ref = (
        _firestore()
        .collection("airel_v2_sessions")
        .document(prefix)
    )
    doc_ref.set(
        {
            "session_id_full":   session_id,
            "interrupt_id_full": interrupt_id,
            "user_id":           user_id,
            "created_at":        now,
            "expires_at":        now + timedelta(days=SESSION_TTL_DAYS),
            "terminated":        False,
            "pending_revise_id": None,
        },
        merge=True,
    )


# ---------------------------------------------------------------------------
# Telegram POST (§7.3.1)
# ---------------------------------------------------------------------------


def _telegram_post(method: str, payload: dict) -> dict:
    """POST to https://api.telegram.org/bot{TOKEN}/{method} with payload.

    Raises requests.HTTPError on non-2xx, RuntimeError on missing env.
    Returns the parsed JSON response.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var is required")
    url = TELEGRAM_API_BASE.format(token=token) + "/" + method
    response = requests.post(url, json=payload, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Public: post_topic_approval (Topic Gate, §6.3.1)
# ---------------------------------------------------------------------------


def post_topic_approval(
    chosen: dict,
    session_id: str,
    interrupt_id: str,
    user_id: str,
) -> dict:
    """Post Topic Gate Telegram message with 2 buttons (Approve / Skip).

    Side effects:
      1. Writes session-lookup doc to Firestore (including `user_id`).
      2. POSTs sendMessage to Telegram.

    Returns the Telegram API response. Raises on Telegram or Firestore
    error (per §12.2 decision 1: no retry in v2).
    """
    chat_id = _required_env("TELEGRAM_APPROVAL_CHAT_ID")
    _write_session_lookup(session_id, interrupt_id, user_id)

    text = _format_topic_message(chosen)
    keyboard = _two_button_keyboard(
        session_id=session_id,
        interrupt_id=interrupt_id,
        choices=[("✅ Approve", "approve"), ("⏭ Skip", "skip")],
    )
    payload = {
        "chat_id":    chat_id,
        "text":       text,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": keyboard},
        "disable_web_page_preview": True,
    }
    return _telegram_post("sendMessage", payload)


def _format_topic_message(chosen: dict) -> str:
    """HTML-escaped Telegram message body for Topic Gate. ≤4096 chars."""
    title     = html_escape(str(chosen.get("title", "(no title)")))
    source    = html_escape(str(chosen.get("source", "?")))
    score     = chosen.get("score", "?")
    url       = html_escape(str(chosen.get("url", "")))
    rationale = html_escape(str(chosen.get("rationale", "")))
    body = (
        f"<b>{title}</b>\n"
        f"Source: {source}  •  Score: {score}\n"
        f"{url}"
    )
    if rationale:
        body += f"\n\n<i>{rationale}</i>"
    return body[:4000]  # Telegram caps at 4096; leave headroom.


# ---------------------------------------------------------------------------
# Public: post_editor_review (Editor, §6.9.1)
# ---------------------------------------------------------------------------


def post_editor_review(
    chosen: dict,
    draft_preview: str,
    image_urls: list[str],
    video_url: Optional[str],
    repo_url: Optional[str],
    session_id: str,
    interrupt_id: str,
    user_id: str,
) -> dict:
    """Post Editor Telegram review as a .md document attachment + caption.

    Sends the FULL draft markdown as a downloadable file (so the operator
    can read the whole thing in Telegram's preview) with a short HTML
    caption summarizing the release + asset counts, plus the 3-button
    inline keyboard (Approve / Revise / Reject).

    On Revise tap, the bridge handles the ForceReply follow-up
    separately — this function ONLY posts the initial review message.

    Side effects: writes Firestore session-lookup doc, then POSTs
    sendDocument to Telegram. Returns the Telegram API response.
    """
    chat_id = _required_env("TELEGRAM_APPROVAL_CHAT_ID")
    _write_session_lookup(session_id, interrupt_id, user_id)

    caption = _format_editor_caption(
        chosen=chosen,
        image_count=len(image_urls),
        video_url=video_url,
        repo_url=repo_url,
        draft_chars=len(draft_preview or ""),
    )
    keyboard = _three_button_keyboard(
        session_id=session_id,
        interrupt_id=interrupt_id,
        choices=[
            ("✅ Approve", "approve"),
            ("✏️ Revise",  "revise"),
            ("❌ Reject",  "reject"),
        ],
    )
    title_slug = _slugify(str(chosen.get("title", "draft"))) or "draft"
    filename = f"{title_slug}-draft.md"
    document_bytes = (draft_preview or "(empty draft)").encode("utf-8")
    return _telegram_send_document(
        chat_id=chat_id,
        filename=filename,
        document_bytes=document_bytes,
        caption=caption,
        reply_markup={"inline_keyboard": keyboard},
    )


def _slugify(s: str) -> str:
    """ASCII slug for filenames — letters/digits/hyphens only, max 50 chars."""
    import re as _re
    cleaned = _re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return cleaned[:50]


def _telegram_send_document(
    chat_id: str,
    filename: str,
    document_bytes: bytes,
    caption: str,
    reply_markup: dict,
) -> dict:
    """Multipart sendDocument with caption + inline keyboard."""
    import json as _json
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var is required")
    url = TELEGRAM_API_BASE.format(token=token) + "/sendDocument"
    files = {"document": (filename, document_bytes, "text/markdown")}
    data = {
        "chat_id":      chat_id,
        "caption":      caption[:1024],  # Telegram caption limit
        "parse_mode":   "HTML",
        "reply_markup": _json.dumps(reply_markup),
    }
    response = requests.post(url, files=files, data=data, timeout=HTTP_TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def _format_editor_caption(
    chosen: dict,
    image_count: int,
    video_url: Optional[str],
    repo_url: Optional[str],
    draft_chars: int,
) -> str:
    """HTML-formatted caption for the Editor sendDocument call. The full
    draft is the attached .md file; this caption is a short header."""
    title = html_escape(str(chosen.get("title", "(no title)")))
    source = html_escape(str(chosen.get("source", "?")))
    lines = [
        f"<b>{title}</b> — Editor review",
        f"<i>Source: {source}  •  Draft: {draft_chars} chars  •  Images: {image_count}</i>",
    ]
    if video_url:
        lines.append(f"Video: {html_escape(video_url)}")
    if repo_url:
        lines.append(f"Repo: {html_escape(repo_url)}")
    lines.append("")
    lines.append(
        "Open the attached <code>.md</code> file to read the full draft, "
        "then tap <b>Approve</b>, <b>Revise</b>, or <b>Reject</b>."
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inline-keyboard helpers
# ---------------------------------------------------------------------------


def _two_button_keyboard(
    session_id: str,
    interrupt_id: str,
    choices: list[tuple[str, str]],
) -> list[list[dict]]:
    """One row of 2 buttons. ``choices`` is [(label, choice_value), ...]."""
    return [[
        {"text": label, "callback_data": callback_data(session_id, choice, interrupt_id)}
        for label, choice in choices
    ]]


def _three_button_keyboard(
    session_id: str,
    interrupt_id: str,
    choices: list[tuple[str, str]],
) -> list[list[dict]]:
    """Approve on its own row, Revise + Reject on the second row."""
    if len(choices) != 3:
        raise ValueError(f"_three_button_keyboard needs exactly 3 choices, got {len(choices)}")
    approve_label, approve_choice = choices[0]
    revise_label, revise_choice = choices[1]
    reject_label, reject_choice = choices[2]
    return [
        [{"text": approve_label, "callback_data": callback_data(session_id, approve_choice, interrupt_id)}],
        [
            {"text": revise_label, "callback_data": callback_data(session_id, revise_choice, interrupt_id)},
            {"text": reject_label, "callback_data": callback_data(session_id, reject_choice, interrupt_id)},
        ],
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} env var is required")
    return value
