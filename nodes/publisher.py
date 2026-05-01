"""publisher — terminal node for the happy path. See DESIGN.v2.md §6.11.

Composes final_markdown (image/video URLs injected), uploads asset bundle
to GCS, writes Memory Bank `covered` fact, sets cycle_outcome="published"."""

import json
import logging
from datetime import datetime, timezone

from google.adk import Context, Event

from shared.markdown_assets import inject_assets
from tools.gcs import upload_to_gcs
from tools.medium import medium_format

logger = logging.getLogger(__name__)


def publisher(node_input, ctx: Context) -> Event:
    """Compose final markdown + asset bundle + Memory Bank fact."""
    from shared.models import ChosenRelease, ImageAsset, StarterRepo, VideoAsset

    # State persistence turns Pydantic models into dicts on rehydration.
    # Coerce back here so the rest of this function uses model attr
    # access without TypeErrors.
    def _coerce(value, model_cls):
        if value is None or isinstance(value, model_cls):
            return value
        if isinstance(value, dict):
            try:
                return model_cls.model_validate(value)
            except Exception as e:
                logger.warning("publisher: %s coercion failed: %s",
                               model_cls.__name__, e)
                return None
        return value

    # chosen_release may be a partial dict (the test fixtures pass title +
    # url + source only). Use a lenient `_get` helper instead of strict
    # model coercion for it.
    def _get(value, attr_name):
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(attr_name)
        return getattr(value, attr_name, None)

    raw_chosen = ctx.state.get("chosen_release")
    draft    = ctx.state.get("draft") or ""
    raw_images = ctx.state.get("image_assets") or []
    images   = [m for m in (_coerce(i, ImageAsset) for i in raw_images) if m is not None]
    video    = _coerce(ctx.state.get("video_asset"), VideoAsset)
    repo     = _coerce(ctx.state.get("starter_repo"), StarterRepo)
    cycle_id = ctx.session.id[:8]

    md = inject_assets(draft, images, video)
    final_md = medium_format(md)
    ctx.state["final_markdown"] = final_md

    # 4. Bundle to GCS. images/video/repo are coerced to models above
    # (model_dump safe); chosen may be a partial dict (use _get).
    bundle = {
        "title":           _get(raw_chosen, "title"),
        "release_url":     _get(raw_chosen, "url"),
        "release_source":  _get(raw_chosen, "source"),
        "published_at":    datetime.now(timezone.utc).isoformat(),
        "markdown":        final_md,
        "image_assets":    [img.model_dump(mode="json") for img in images],
        "video_asset":     video.model_dump(mode="json") if video else None,
        "starter_repo":    repo.model_dump(mode="json")  if repo  else None,
    }
    bundle_bytes = json.dumps(bundle, indent=2).encode("utf-8")
    bundle_url = upload_to_gcs(
        bytes_data=bundle_bytes,
        slug=f"{cycle_id}/article_bundle.json",
        content_type="application/json",
    )
    ctx.state["asset_bundle_url"] = bundle_url

    # 5. Memory Bank "covered" fact (best-effort — failure does NOT fail the cycle)
    try:
        from tools.memory import memory_bank_add_fact
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact=f"Covered: {bundle['title']}",
            metadata={
                "type":           "covered",
                "release_url":    bundle["release_url"],
                "release_source": bundle["release_source"],
                "covered_at":     datetime.now(timezone.utc).isoformat(),
                "bundle_url":     bundle_url,
                "starter_repo":   repo.url if repo else None,
            },
        )
        ctx.state["memory_bank_recorded"] = True
    except ImportError:
        # tools/memory.py not yet implemented (§7.2)
        logger.warning("memory_bank_add_fact unavailable — covered fact not persisted")
        ctx.state["memory_bank_recorded"] = False
    except Exception as e:
        logger.error("publisher: Memory Bank write failed: %s", e)
        ctx.state["memory_bank_recorded"] = False

    ctx.state["cycle_outcome"] = "published"

    # Best-effort final Telegram notification — operator wants to know the
    # cycle landed without watching logs. Never fail the cycle on this.
    try:
        import os
        from html import escape as _h
        chat_id = os.environ.get("TELEGRAM_APPROVAL_CHAT_ID")
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if chat_id and token:
            import requests as _requests
            text_lines = [
                f"✅ <b>Published</b>: {_h(bundle['title'])}",
                f"<i>Source: {_h(str(bundle['release_source']))}</i>",
                "",
                f"Bundle: {_h(bundle_url)}",
            ]
            if repo is not None:
                text_lines.append(f"Repo: {_h(repo.url)}")
            text_lines.append(
                f"Memory Bank: {'recorded' if ctx.state['memory_bank_recorded'] else 'failed (see logs)'}"
            )
            _requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={
                    "chat_id":    chat_id,
                    "text":       "\n".join(text_lines)[:4000],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
    except Exception as e:
        logger.warning("publisher: final Telegram notification failed: %s", e)

    return Event(output={
        "outcome":     "published",
        "title":       bundle["title"],
        "bundle_url":  bundle_url,
        "memory_bank": ctx.state["memory_bank_recorded"],
    })
