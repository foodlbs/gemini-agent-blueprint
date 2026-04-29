"""Telegram approval tools for the human-in-the-loop gates.

Step 3 ships ``telegram_post_topic_for_approval`` (Topic Gate, two buttons:
Approve / Skip). Step 9 adds ``telegram_post_for_approval`` (Editor's
revision loop, three buttons + ForceReply for revise feedback).

Both block the calling tool until the human responds OR the 24-hour timeout
fires. The async cores (``_post_topic_and_wait``, ``_post_editor_and_wait``)
are factored out so tests can inject mocked verdicts without spinning up a
Telegram client.
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel
from telegram import Bot, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup

from shared.models import Candidate, ChosenRelease, EditorVerdict, TopicVerdict

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 86_400  # 24 hours per DESIGN.md §3 and §9.
GET_UPDATES_POLL_TIMEOUT = 30  # seconds per long-poll iteration.

TOPIC_APPROVE_CALLBACK = "topic:approve"
TOPIC_SKIP_CALLBACK = "topic:skip"

EDITOR_APPROVE_CALLBACK = "editor:approve"
EDITOR_REJECT_CALLBACK = "editor:reject"
EDITOR_REVISE_CALLBACK = "editor:revise"

EDITOR_PREVIEW_LIMIT = 800  # Truncate article preview in the chat message.


def telegram_post_topic_for_approval(
    chosen_release: dict,
    rationale: str,
    top_alternatives: list[dict] | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Post the chosen release to Telegram and block until the human responds.

    The message renders the topic title, source, score, rationale, URL, and
    (collapsed) up to two alternatives. Two inline buttons capture the verdict:
    Approve (continues the pipeline) or Skip (records as human-rejected).

    Args:
        chosen_release: The release Triage selected.
        rationale: Triage's one-paragraph reason for the choice.
        top_alternatives: Up to two next-highest candidates from Triage.
        timeout_seconds: Defaults to 24 hours per DESIGN.md.

    Returns:
        TopicVerdict with verdict ∈ {"approve", "skip", "timeout"} and ``at``
        the timestamp the verdict was captured (UTC).
    """
    chosen = _to_dict(chosen_release)
    alts = [_to_dict(a) for a in (top_alternatives or [])][:2]
    verdict = asyncio.run(
        _post_topic_and_wait(chosen, rationale, alts, timeout_seconds)
    )
    return verdict.model_dump(mode="json")


async def _post_topic_and_wait(
    chosen: dict,
    rationale: str,
    alternatives: list[dict],
    timeout_seconds: int,
) -> TopicVerdict:
    """Send the topic message and long-poll for a callback or timeout."""
    token = _required_env("TELEGRAM_BOT_TOKEN")
    chat_id = _required_env("TELEGRAM_APPROVAL_CHAT_ID")

    bot = Bot(token=token)
    text = _format_topic_message(chosen, rationale, alternatives)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=TOPIC_APPROVE_CALLBACK),
        InlineKeyboardButton("⏭ Skip", callback_data=TOPIC_SKIP_CALLBACK),
    ]])
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
        disable_web_page_preview=False,
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    last_update_id: int | None = None

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return TopicVerdict(verdict="timeout", at=datetime.now(timezone.utc))
        poll_timeout = max(1, int(min(GET_UPDATES_POLL_TIMEOUT, remaining)))
        try:
            updates = await bot.get_updates(
                offset=last_update_id,
                timeout=poll_timeout,
                allowed_updates=["callback_query"],
            )
        except Exception as e:
            logger.warning("get_updates failed: %s", e)
            await asyncio.sleep(1)
            continue

        for update in updates:
            last_update_id = update.update_id + 1
            cq = update.callback_query
            if cq is None or cq.message is None:
                continue
            if cq.message.message_id != sent.message_id:
                continue
            data = (cq.data or "").strip()
            try:
                await cq.answer()
            except Exception as e:
                logger.warning("callback ack failed: %s", e)
            if data == TOPIC_APPROVE_CALLBACK:
                return TopicVerdict(
                    verdict="approve", at=datetime.now(timezone.utc)
                )
            if data == TOPIC_SKIP_CALLBACK:
                return TopicVerdict(
                    verdict="skip", at=datetime.now(timezone.utc)
                )
            # Unknown callback for our message — keep waiting.


def _format_topic_message(
    chosen: dict, rationale: str, alternatives: list[dict]
) -> str:
    """Render the Topic Gate Telegram message in HTML mode.

    Includes title, source, score, rationale, URL, and a collapsed
    alternatives list (up to 2). All user-controlled strings are
    HTML-escaped.
    """
    title = _esc(chosen.get("title", "Untitled"))
    source = _esc(chosen.get("source", "?"))
    score = _esc(chosen.get("score", "?"))
    url = chosen.get("url", "")
    parts = [
        f"<b>📰 {title}</b>",
        f"Source: <code>{source}</code> · Score: <b>{score}</b>",
        "",
        _esc(rationale),
        "",
        f'<a href="{_esc(url)}">{_esc(url)}</a>',
    ]
    if alternatives:
        parts.append("")
        parts.append("<i>Alternatives:</i>")
        for alt in alternatives[:2]:
            t = _esc(alt.get("title", "Untitled"))
            u = _esc(alt.get("url", ""))
            parts.append(f'• <a href="{u}">{t}</a>')
    return "\n".join(parts)


def _to_dict(value: Any) -> dict:
    """Normalize a Pydantic model or dict to a plain dict."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return value
    raise TypeError(
        f"expected BaseModel or dict, got {type(value).__name__}"
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set; required for Telegram approval tools"
        )
    return value


def _esc(text: Any) -> str:
    """HTML-escape (Telegram HTML mode requires &, <, > escaped)."""
    s = "" if text is None else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# --- Editor approval (Step 9) ---------------------------------------------


def telegram_post_for_approval(
    article: str,
    repo_url: Optional[str],
    asset_summary: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    """Post the final draft for human approval and block until verdict.

    Renders a Telegram message with the article preview, repo URL, and
    asset summary plus three inline buttons: Approve / Reject / Revise.
    On Revise, sends a ``ForceReply`` prompt and captures the next text
    message in the chat as ``feedback``.

    Args:
        article: The polished article markdown (rendered as a preview).
        repo_url: GitHub starter repo URL or None.
        asset_summary: One-line asset bundle summary.
        timeout_seconds: 24h per DESIGN.md §9.

    Returns:
        EditorVerdict with verdict ∈ {"approve", "reject", "revise",
        "pending_human"}, ``feedback`` set on revise, ``at`` the UTC
        timestamp the verdict was captured.
    """
    verdict = asyncio.run(
        _post_editor_and_wait(article, repo_url or "", asset_summary, timeout_seconds)
    )
    return verdict.model_dump(mode="json")


async def _post_editor_and_wait(
    article: str,
    repo_url: str,
    asset_summary: str,
    timeout_seconds: int,
) -> EditorVerdict:
    """Send the editor approval message and long-poll for verdict."""
    token = _required_env("TELEGRAM_BOT_TOKEN")
    chat_id = _required_env("TELEGRAM_APPROVAL_CHAT_ID")

    bot = Bot(token=token)
    text = _format_editor_message(article, repo_url, asset_summary)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=EDITOR_APPROVE_CALLBACK),
        InlineKeyboardButton("❌ Reject", callback_data=EDITOR_REJECT_CALLBACK),
        InlineKeyboardButton("✏️ Revise", callback_data=EDITOR_REVISE_CALLBACK),
    ]])
    sent = await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
        reply_markup=keyboard,
    )

    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_seconds
    last_update_id: Optional[int] = None

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return EditorVerdict(verdict="pending_human", at=datetime.now(timezone.utc))
        poll_timeout = max(1, int(min(GET_UPDATES_POLL_TIMEOUT, remaining)))
        try:
            updates = await bot.get_updates(
                offset=last_update_id,
                timeout=poll_timeout,
                allowed_updates=["callback_query", "message"],
            )
        except Exception as e:
            logger.warning("editor get_updates failed: %s", e)
            await asyncio.sleep(1)
            continue

        for update in updates:
            last_update_id = update.update_id + 1
            cq = update.callback_query
            if cq is None or cq.message is None:
                continue
            if cq.message.message_id != sent.message_id:
                continue
            data = (cq.data or "").strip()
            try:
                await cq.answer()
            except Exception as e:
                logger.warning("editor callback ack failed: %s", e)
            if data == EDITOR_APPROVE_CALLBACK:
                return EditorVerdict(
                    verdict="approve", at=datetime.now(timezone.utc)
                )
            if data == EDITOR_REJECT_CALLBACK:
                return EditorVerdict(
                    verdict="reject", at=datetime.now(timezone.utc)
                )
            if data == EDITOR_REVISE_CALLBACK:
                feedback, last_update_id = await _capture_revise_feedback(
                    bot, chat_id, deadline, last_update_id
                )
                if feedback is None:
                    return EditorVerdict(
                        verdict="pending_human",
                        at=datetime.now(timezone.utc),
                    )
                return EditorVerdict(
                    verdict="revise",
                    feedback=feedback,
                    at=datetime.now(timezone.utc),
                )


async def _capture_revise_feedback(
    bot: Bot,
    chat_id: str,
    deadline: float,
    offset: Optional[int],
) -> tuple[Optional[str], Optional[int]]:
    """After a Revise tap, send a ForceReply prompt and wait for text reply.

    Returns ``(feedback_text, last_update_id)`` where ``feedback_text`` is
    None on timeout. The last_update_id is returned so the caller can
    advance its long-poll offset past the captured message.
    """
    await bot.send_message(
        chat_id=chat_id,
        text="What needs revision? Reply to this message with your feedback.",
        reply_markup=ForceReply(),
    )

    loop = asyncio.get_event_loop()
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            return None, offset
        poll_timeout = max(1, int(min(GET_UPDATES_POLL_TIMEOUT, remaining)))
        try:
            updates = await bot.get_updates(
                offset=offset,
                timeout=poll_timeout,
                allowed_updates=["message"],
            )
        except Exception as e:
            logger.warning("revise feedback get_updates failed: %s", e)
            await asyncio.sleep(1)
            continue

        for update in updates:
            offset = update.update_id + 1
            msg = getattr(update, "message", None)
            if msg is None:
                continue
            text = (getattr(msg, "text", None) or "").strip()
            if text:
                return text, offset


def _format_editor_message(
    article: str, repo_url: str, asset_summary: str
) -> str:
    """Render the Editor-stage Telegram message in HTML mode."""
    preview = (article or "").strip()
    if len(preview) > EDITOR_PREVIEW_LIMIT:
        preview = preview[:EDITOR_PREVIEW_LIMIT] + "…"
    parts = [
        "<b>📝 Editor: ready for approval</b>",
        f"<i>Assets:</i> {_esc(asset_summary)}",
    ]
    if repo_url:
        parts.append(
            f'<i>Repo:</i> <a href="{_esc(repo_url)}">{_esc(repo_url)}</a>'
        )
    parts.append("")
    parts.append("<i>Article preview:</i>")
    parts.append(f"<pre>{_esc(preview)}</pre>")
    return "\n".join(parts)
