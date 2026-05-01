"""Shared helper for injecting image + video URLs into draft markdown.

Used by both `nodes/hitl.editor_request` (so the operator's editor
review .md attachment renders images inline) and `nodes/publisher`
(for the published bundle).
"""

from __future__ import annotations

import logging
import re
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

_IMG_MARKER_RE = re.compile(r"<!--IMG:(?P<pos>[^>]+?)-->")
_VID_MARKER_RE = re.compile(r"<!--VID:[^>]+?-->")


def inject_assets(
    markdown: str,
    image_assets: Iterable,
    video_asset: Optional[object],
) -> str:
    """Replace `<!--IMG:position-->` and `<!--VID:hero-->` markers in
    `markdown` with rendered image/video markdown.

    image_assets: iterable of ImageAsset (or dicts with .position/.url/.alt_text)
    video_asset:  VideoAsset or None
    """
    by_position = {}
    for img in image_assets or []:
        if hasattr(img, "position"):
            by_position[img.position] = img
        elif isinstance(img, dict) and "position" in img:
            by_position[img["position"]] = img

    def _img_replace(m: re.Match) -> str:
        pos = m.group("pos").strip()
        img = by_position.get(pos)
        if img is None:
            logger.warning("inject_assets: no image_asset for position %r — dropping marker", pos)
            return ""
        url = img.url if hasattr(img, "url") else img.get("url", "")
        alt = (img.alt_text if hasattr(img, "alt_text")
               else img.get("alt_text", "")) or "image"
        if not url:
            return ""
        return f"![{alt}]({url})"

    md = _IMG_MARKER_RE.sub(_img_replace, markdown or "")

    if video_asset is not None:
        gif_url = (video_asset.gif_url if hasattr(video_asset, "gif_url")
                   else (video_asset.get("gif_url", "") if isinstance(video_asset, dict) else ""))
        mp4_url = (video_asset.mp4_url if hasattr(video_asset, "mp4_url")
                   else (video_asset.get("mp4_url", "") if isinstance(video_asset, dict) else ""))
        md = _VID_MARKER_RE.sub(
            f"![Demo]({gif_url})\n\n*Watch the [full video]({mp4_url}).*",
            md, count=1,
        )
    else:
        md = _VID_MARKER_RE.sub("", md)
    return md
