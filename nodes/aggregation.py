"""Pure barrier nodes — gather_research + gather_assets.
See DESIGN.v2.md §6.4.4 + §6.7.3.

These trigger AFTER all upstream parallel branches complete. They merge
state by structure (not by meaning — the LLM agents downstream merge by
meaning)."""

import logging

from google.adk import Context, Event

from shared.models import ResearchDossier

logger = logging.getLogger(__name__)


def _empty_dossier() -> ResearchDossier:
    return ResearchDossier(summary="")


def gather_research(node_input, ctx: Context) -> Event:
    """§6.4.4 — merge docs + github + context dossiers into `research`."""
    docs    = ctx.state.get("docs_research")    or _empty_dossier()
    gh      = ctx.state.get("github_research")  or _empty_dossier()
    context = ctx.state.get("context_research") or _empty_dossier()

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


def gather_assets(node_input, ctx: Context) -> Event:
    """§6.7.3 — pure barrier; logs invariant violations but doesn't raise."""
    image_assets = ctx.state.get("image_assets", [])
    image_briefs = ctx.state.get("image_briefs", [])
    video_asset  = ctx.state.get("video_asset")
    needs_video  = ctx.state.get("needs_video", False)

    if len(image_assets) != len(image_briefs):
        logger.error(
            "gather_assets: %d image_assets but %d image_briefs",
            len(image_assets), len(image_briefs),
        )

    return Event(output={
        "image_count": len(image_assets),
        "video_present": video_asset is not None,
        "needs_video":   needs_video,
    })
