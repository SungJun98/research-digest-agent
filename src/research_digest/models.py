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
