"""Normalized source metadata shared by collection, evaluation and delivery."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Paper(BaseModel):
    title: str
    abstract: str = ''
    authors: list[str] = Field(default_factory=list)
    url: str = ''
    published_at: datetime | None = None
    seen_at: datetime | None = None
    doi: str | None = None
    arxiv_id: str | None = None
    s2_id: str | None = None
    sources: set[str] = Field(default_factory=set)
    signals: dict[str, float] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator('doi', 'arxiv_id', 's2_id', mode='before')
    @classmethod
    def normalize_ids(cls, value, info):
        from .identity import normalize_arxiv, normalize_doi
        if not value:
            return None
        if info.field_name == 'arxiv_id':
            return normalize_arxiv(str(value))
        if info.field_name == 'doi':
            return normalize_doi(str(value))
        return str(value).strip().lower().removeprefix('s2:')

    @field_validator('published_at', 'seen_at')
    @classmethod
    def utc_dates(cls, value):
        if value is None:
            return value
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @property
    def canonical_id(self) -> str:
        from .identity import canonicalize
        return canonicalize(self)


from typing import Literal
from pydantic import ConfigDict


class FulltextContext(BaseModel):
    text: str
    url: str
    coverage: Literal['partial_html'] = 'partial_html'


class EvidenceSpan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=3,max_length=1500)
    source: Literal['abstract','partial_html']
    url: str


class Evaluation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    topic_id: str | None
    relevance: int = Field(ge=1,le=5,strict=True)
    importance: int = Field(ge=1,le=5,strict=True)
    evidence: int = Field(ge=1,le=5,strict=True)
    fit: int = Field(ge=1,le=5,strict=True)
    reason: str = Field(min_length=1,max_length=600)
    contribution: str = Field(min_length=1,max_length=600)
    fit_reason: str = Field(min_length=1,max_length=600)
    limitation: str = Field(min_length=1,max_length=600)
    reading_question: str = Field(min_length=1,max_length=600)
    problem_concepts: list[str] = Field(max_length=20)
    method_concepts: list[str] = Field(max_length=20)
    problem_description: str = Field(max_length=600)
    contribution_description: str = Field(max_length=600)
    is_adjacent: bool = False
    evidence_spans: list[EvidenceSpan] = Field(min_length=1,max_length=6)
    coverage: Literal['abstract','partial_html'] = 'abstract'
