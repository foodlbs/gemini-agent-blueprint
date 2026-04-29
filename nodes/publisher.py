"""publisher — terminal node for the happy path. See DESIGN.v2.md §6.11.

Composes final_markdown (image/video URLs injected), uploads asset bundle
to GCS, writes Memory Bank `covered` fact, sets cycle_outcome="published"."""

import json
import logging
import re
from datetime import datetime, timezone

from google.adk import Context, Event

from tools.gcs import upload_to_gcs
from tools.medium import medium_format

logger = logging.getLogger(__name__)

_IMG_MARKER_RE = re.compile(r"<!--IMG:(?P<pos>[^>]+?)-->")
_VID_MARKER_RE = re.compile(r"<!--VID:[^>]+?-->")


def publisher(node_input, ctx: Context) -> Event:
    """Compose final markdown + asset bundle + Memory Bank fact."""
    chosen   = ctx.state["chosen_release"]
    draft    = ctx.state["draft"]
    images   = ctx.state.get("image_assets", []) or []
    video    = ctx.state.get("video_asset")
    repo     = ctx.state.get("starter_repo")
    cycle_id = ctx.session.id[:8]

    # 1. Inject image URLs by position
    by_position = {img.position: img for img in images}

    def _img_replace(m: re.Match) -> str:
        pos = m.group("pos").strip()
        img = by_position.get(pos)
        if img is None:
            logger.warning("publisher: no image_asset for position %r", pos)
            return ""  # drop the broken marker
        return f"![{img.alt_text}]({img.url})"

    md = _IMG_MARKER_RE.sub(_img_replace, draft.markdown)

    # 2. Inject video at the marker (or drop the marker if no video)
    if video is not None:
        md = _VID_MARKER_RE.sub(
            f"![Demo]({video.gif_url})\n\n*Watch the [full video]({video.mp4_url}).*",
            md, count=1,
        )
    else:
        md = _VID_MARKER_RE.sub("", md)

    # 3. Medium post-process
    final_md = medium_format(md)
    ctx.state["final_markdown"] = final_md

    # 4. Bundle to GCS
    bundle = {
        "title":           chosen.get("title") if isinstance(chosen, dict) else chosen.title,
        "release_url":     chosen.get("url") if isinstance(chosen, dict) else chosen.url,
        "release_source":  chosen.get("source") if isinstance(chosen, dict) else chosen.source,
        "published_at":    datetime.now(timezone.utc).isoformat(),
        "markdown":        final_md,
        "image_assets":    [img.model_dump(mode="json") for img in images],
        "video_asset":     video.model_dump(mode="json") if video else None,
        "starter_repo":    repo.model_dump(mode="json") if repo else None,
    }
    bundle_bytes = json.dumps(bundle, indent=2).encode("utf-8")
    bundle_url = upload_to_gcs(
        payload=bundle_bytes,
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
    return Event(output={
        "outcome":     "published",
        "title":       bundle["title"],
        "bundle_url":  bundle_url,
        "memory_bank": ctx.state["memory_bank_recorded"],
    })
