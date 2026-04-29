"""Pydantic models for ADK session state. State keys named in DESIGN.md map to fields here."""

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
    verdict: Literal["approve", "skip", "timeout"]
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
    verdict: Literal["approve", "reject", "revise", "pending_human"]
    feedback: Optional[str] = None
    at: datetime
