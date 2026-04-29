"""Telegram smoke test: post a Topic-Gate-style message with both buttons.

Reads TELEGRAM_BOT_TOKEN and TELEGRAM_APPROVAL_CHAT_ID from env. Calls
``telegram_post_topic_for_approval`` with a fake ChosenRelease fixture.
The function blocks until verdict OR timeout — for smoke purposes we
override the timeout to a short value (15 seconds) so the script exits
without waiting on a human tap.

Usage:
    uv run python tests/smoke/telegram_smoke.py

Exit code 0 = message posted successfully (timeout reached, that's expected).
Exit code 1 = posting failed (auth, rate limit, chat ID wrong, etc.).
"""

import os
import sys
from datetime import datetime, timezone

# Ensure we can import the project modules from a script run path.
_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.models import ChosenRelease  # noqa: E402
from tools.telegram_approval import telegram_post_topic_for_approval  # noqa: E402


def main() -> int:
    if not os.environ.get("TELEGRAM_BOT_TOKEN") or not os.environ.get(
        "TELEGRAM_APPROVAL_CHAT_ID"
    ):
        print("SKIP: TELEGRAM_BOT_TOKEN or TELEGRAM_APPROVAL_CHAT_ID not set")
        return 0

    fixture = ChosenRelease(
        title="[smoke test] AI release pipeline self-check",
        url="https://example.com/smoke-test",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="This is an automated smoke test from the AI release pipeline.",
        score=85,
        rationale="Smoke-test fixture; tap Skip to clear.",
        top_alternatives=[],
    )

    print("Posting smoke message to Telegram (15s timeout, will not block)...")
    verdict = telegram_post_topic_for_approval(
        chosen_release=fixture,
        rationale=fixture.rationale,
        top_alternatives=[],
        timeout_seconds=15,  # short so we don't wait on a human tap
    )
    print(f"Verdict received: {verdict.verdict} at {verdict.at.isoformat()}")
    if verdict.verdict == "timeout":
        print("OK: posted successfully; you can manually tap Skip to clear.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
