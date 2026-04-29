"""Pydantic models for the v2 Workflow's typed state.

DESIGN.v2.md §4 is normative — every field, type, and default here matches
the design's `PipelineState` definition. The Workflow declares
``state_schema=PipelineState`` so ADK enforces these types at construction
time and at every ``ctx.state[...]`` write.
"""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


SourceType = Literal[
    # Pre-existing — keep order stable; tests reference these by name.
    "arxiv",
    "github",
    "anthropic",
    "google",
    "openai",
    "huggingface",
    # Lab + community sources added in pollers expansion.
    "deepmind",
    "meta",
    "mistral",
    "nvidia",
    "microsoft",
    "bair",
    "huggingface_papers",
    "huggingface_blog",
    "hackernews",
    # Catch-all for new feeds the operator wires up before extending this Literal.
    "other",
]
ArticleType = Literal["quickstart", "explainer", "comparison", "release_recap"]
ImageStyle = Literal["photoreal", "diagram", "illustration", "screenshot"]
AspectRatio = Literal["16:9", "4:3"]
CriticVerdict = Literal["accept", "revise"]
TopicDecision = Literal["approve", "skip", "timeout"]
EditorDecision = Literal["approve", "reject", "revise", "timeout"]
CycleOutcome = Literal[
    "skipped_by_triage",
    "skipped_by_human_topic",
    "topic_timeout",
    "rejected_by_editor",
    "editor_timeout",
    "published",
]


class Candidate(BaseModel):
    title: str
    url: str
    source: SourceType
    published_at: datetime
    raw_summary: str


class ChosenRelease(Candidate):
    score: int = Field(ge=0, le=100)
    rationale: str
    top_alternatives: list[Candidate] = Field(default_factory=list, max_length=2)


class TopicVerdict(BaseModel):
    verdict: TopicDecision
    at: datetime


class ResearchDossier(BaseModel):
    summary: str
    headline_quotes: list[str] = Field(default_factory=list, max_length=2)
    code_example: Optional[str] = None
    prerequisites: list[str] = Field(default_factory=list)
    repo_meta: Optional[dict] = None
    readme_excerpt: Optional[str] = None
    file_list: list[str] = Field(default_factory=list)
    reactions: list[str] = Field(default_factory=list)
    related_releases: list[str] = Field(default_factory=list)


class OutlineSection(BaseModel):
    heading: str
    intent: str
    research_items: list[str] = Field(default_factory=list)
    word_count: int


class Outline(BaseModel):
    sections: list[OutlineSection]
    working_title: str
    working_subtitle: str
    article_type: ArticleType


class ImageBrief(BaseModel):
    position: str
    description: str
    style: ImageStyle
    aspect_ratio: AspectRatio


class VideoBrief(BaseModel):
    description: str
    style: str
    duration_seconds: int = Field(ge=4, le=8)
    aspect_ratio: AspectRatio = "16:9"


class ImageAsset(BaseModel):
    position: str
    url: str
    alt_text: str
    aspect_ratio: AspectRatio


class VideoAsset(BaseModel):
    mp4_url: str
    gif_url: str
    poster_url: str
    duration_seconds: int


class Draft(BaseModel):
    markdown: str
    iteration: int = 0
    critic_feedback: Optional[str] = None
    critic_verdict: Optional[CriticVerdict] = None


class RevisionFeedback(BaseModel):
    feedback: str
    at: datetime


class EditorVerdict(BaseModel):
    verdict: EditorDecision
    feedback: Optional[str] = None
    at: datetime


class StarterRepo(BaseModel):
    """Result of repo_builder when needs_repo=True. Per §6.8.2 + §4."""
    url: str
    files_committed: list[str]
    sha: str


class PipelineState(BaseModel):
    """Top-level Workflow state schema — every key the v2 graph touches.

    The Workflow declares ``state_schema=PipelineState`` so ADK validates
    every ``ctx.state[...]`` write against the type. Function nodes whose
    parameters name state keys auto-bind from this schema.

    Field order matches DESIGN.v2.md §4. Lifecycle (who writes / who reads)
    is documented in §4's "Field lifecycle table."
    """

    # --- Trigger / scheduling ------------------------------------------------
    last_run_at: Optional[datetime] = None
    """Set by the trigger entry node from the Cloud Scheduler payload."""

    # --- Scout ---------------------------------------------------------------
    candidates: list[Candidate] = Field(default_factory=list)
    """All candidate releases collected by Scout this cycle."""

    # --- Triage --------------------------------------------------------------
    chosen_release: Optional[ChosenRelease] = None
    """The one candidate Triage picked, OR None if Triage skipped."""
    skip_reason: Optional[str] = None
    """Set when chosen_release is None. Free-text explanation."""

    # --- Topic Gate (HITL #1) ------------------------------------------------
    topic_verdict: Optional[TopicVerdict] = None
    """The human's response to the topic-approval Telegram post."""

    # --- Researcher pool -----------------------------------------------------
    docs_research: Optional[ResearchDossier] = None
    github_research: Optional[ResearchDossier] = None
    context_research: Optional[ResearchDossier] = None
    research: Optional[ResearchDossier] = None
    """Merged dossier produced by gather_research from the three above."""

    # --- Architect -----------------------------------------------------------
    outline: Optional[Outline] = None
    image_briefs: list[ImageBrief] = Field(default_factory=list)
    video_brief: Optional[VideoBrief] = None
    needs_video: bool = False
    needs_repo: bool = False

    # --- Writer loop ---------------------------------------------------------
    draft: Optional[Draft] = None
    """Current draft being iterated. Drafter writes; Critic annotates."""
    writer_iterations: int = 0
    """Hard cap counter — route_critic_verdict forces ACCEPT once this hits 3."""

    # --- Asset agent ---------------------------------------------------------
    image_assets: list[ImageAsset] = Field(default_factory=list)
    video_asset: Optional[VideoAsset] = None

    # --- Repo Builder (conditional) -----------------------------------------
    starter_repo: Optional[StarterRepo] = None

    # --- Editor (HITL #2) + Revision Writer loop ----------------------------
    editor_verdict: Optional[EditorVerdict] = None
    human_feedback: Optional[RevisionFeedback] = None
    """Set by record_editor_verdict on revise; consumed by revision_writer."""
    editor_iterations: int = 0
    """Hard cap counter — record_editor_verdict forces approve/reject after 3."""

    # --- Publisher -----------------------------------------------------------
    final_markdown: Optional[str] = None
    """Medium-formatted final draft, written by publisher."""
    asset_bundle_url: Optional[str] = None
    """GCS URL of the bundled assets (markdown + images + video)."""
    memory_bank_recorded: bool = False
    """True after publisher writes the `covered` Memory Bank fact."""

    # --- Cycle outcome (set by exactly one terminal node) -------------------
    cycle_outcome: Optional[CycleOutcome] = None
    """Set by exactly one terminal node. Read by post-cycle reporting."""
