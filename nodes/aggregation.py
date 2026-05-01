"""Pure barrier nodes — gather_research + gather_assets.
See DESIGN.v2.md §6.4.4 + §6.7.3.

These trigger AFTER all upstream parallel branches complete. They merge
state by structure (not by meaning — the LLM agents downstream merge by
meaning)."""

import json
import logging
import re

from google.adk import Context, Event

from nodes._join_node import JoinFunctionNode
from shared.models import ResearchDossier

logger = logging.getLogger(__name__)


def _empty_dossier() -> ResearchDossier:
    return ResearchDossier(summary="")


# Strip ``` fences and any leading prose so json.loads has a clean
# payload. Researchers sometimes wrap their JSON in markdown fences.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def _parse_dossier(raw: object, source_label: str) -> ResearchDossier:
    """Best-effort: turn whatever the researcher LlmAgent emitted into a
    valid ResearchDossier. Returns an empty dossier on any parse error so
    a single bad researcher doesn't break the merge."""
    if raw is None:
        return _empty_dossier()
    if isinstance(raw, ResearchDossier):
        return raw
    if isinstance(raw, dict):
        try:
            return ResearchDossier.model_validate(raw)
        except Exception as e:
            logger.warning("gather_research: %s dict failed validation: %s",
                           source_label, e)
            return _empty_dossier()
    if isinstance(raw, str):
        text = _FENCE_RE.sub("", raw).strip()
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            logger.warning(
                "gather_research: %s JSON parse failed (%s); raw[:120]=%r",
                source_label, e, text[:120],
            )
            return _empty_dossier()
        if not isinstance(payload, dict):
            logger.warning("gather_research: %s payload is %s, want dict",
                           source_label, type(payload).__name__)
            return _empty_dossier()
        try:
            return ResearchDossier.model_validate(payload)
        except Exception as e:
            logger.warning("gather_research: %s validation failed: %s",
                           source_label, e)
            return _empty_dossier()
    logger.warning("gather_research: %s is %s, treating as empty",
                   source_label, type(raw).__name__)
    return _empty_dossier()


def _gather_research_impl(node_input, ctx: Context) -> Event:
    """§6.4.4 — counter-gated join: parse + merge docs/github/context
    dossiers into `research` once all 3 researchers have triggered.

    See docs/superpowers/specs/2026-05-01-fan-in-join-design.md for why
    this is gated (3 unconditional incoming edges → ADK re-triggers per
    predecessor → without the gate the entire writer chain cascades 3x).
    """
    n = ctx.state.get("gather_research_call_count", 0) + 1
    ctx.state["gather_research_call_count"] = n
    if n < 3:
        return Event()  # WAITING — predecessors can re-trigger.

    docs    = _parse_dossier(ctx.state.get("docs_research"),    "docs")
    gh      = _parse_dossier(ctx.state.get("github_research"),  "github")
    context = _parse_dossier(ctx.state.get("context_research"), "context")

    merged = ResearchDossier(
        # docs_researcher owns these
        summary          = docs.summary or context.summary or gh.summary,
        headline_quotes  = docs.headline_quotes,
        code_example     = docs.code_example,
        prerequisites    = docs.prerequisites,
        # github_researcher owns these
        repo_meta        = gh.repo_meta,
        readme_excerpt   = gh.readme_excerpt,
        file_list        = gh.file_list,
        # context_researcher owns these
        reactions        = context.reactions,
        related_releases = context.related_releases,
    )
    ctx.state["research"] = merged
    return Event(output={"sections_filled": [
        k for k, v in merged.model_dump().items() if v not in (None, [], "")
    ]})


gather_research = JoinFunctionNode(
    func=_gather_research_impl,
    name="gather_research",
)


def gather_assets(node_input, ctx: Context) -> Event:
    """§6.7.3 — barrier between (image_asset_node, video_asset_or_skip) and
    the rest of the workflow. image_asset_node writes the typed
    `image_assets` list directly; this node just validates the count
    against image_briefs."""
    image_assets = ctx.state.get("image_assets") or []
    image_briefs = ctx.state.get("image_briefs") or []
    video_asset  = ctx.state.get("video_asset")
    needs_video  = ctx.state.get("needs_video", False)

    if len(image_assets) != len(image_briefs):
        logger.error(
            "gather_assets: %d image_assets but %d image_briefs",
            len(image_assets), len(image_briefs),
        )

    return Event(output={
        "image_count":   len(image_assets),
        "video_present": video_asset is not None,
        "needs_video":   needs_video,
    })
