from enum import StrEnum
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator


class SourceState(StrEnum):
    enabled = "enabled"
    missing_credentials = "missing_credentials"
    unavailable = "unavailable"
    rate_limited = "rate_limited"
    quota_exhausted = "quota_exhausted"
    error = "error"


class SourceStatus(BaseModel):
    source: str
    status: SourceState
    reason: str = ""
    missing_credentials: list[str] = Field(default_factory=list)


class SearchResult(BaseModel):
    source: str
    query: str
    title: str
    url: str
    snippet: str = ""
    published_at: str | None = None
    author: str | None = None
    metadata: dict = Field(default_factory=dict)
    provenance: list[dict] = Field(default_factory=list)
    retrieved_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    citation_id: str = ""

    @field_validator("title", "snippet")
    @classmethod
    def bound_text(cls, value, info):
        return value[:1000 if info.field_name == "title" else 8000]


class AdapterError(Exception):
    def __init__(self, state: SourceState, reason: str):
        self.state = state
        self.reason = reason
        super().__init__(reason)
