from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class KnowledgeType(str, Enum):
    DECISION = "decision"
    DISCUSSION = "discussion"
    INCIDENT = "incident"
    MEETING = "meeting"
    NOTE = "note"


class RelationType(str, Enum):
    DEPENDS_ON = "depends_on"
    CONTRADICTS = "contradicts"
    REFINES = "refines"
    CAUSED_BY = "caused_by"
    RELATED_TO = "related_to"


class Source(BaseModel):
    """Pointer to the original artifact the knowledge was extracted from."""

    kind: Literal["github_pr", "github_issue", "slack_thread", "git_commit", "local"]
    url: str | None = None
    ref: str | None = None  # e.g. "owner/repo#123"
    fetched_at: datetime


class RawArtifact(BaseModel):
    """A deterministic dump of source data. Input to the extractor."""

    source: Source
    title: str
    body: str
    author: str | None = None
    created_at: datetime | None = None
    # Free-form extras (comments, labels, diff summary, etc.) passed verbatim
    # to the extractor.
    extras: dict = Field(default_factory=dict)

    def fingerprint(self) -> str:
        """Stable identifier for dedup / idempotency."""
        return f"{self.source.kind}:{self.source.ref or self.source.url}"


class KnowledgeNode(BaseModel):
    """A structured knowledge entity, extracted from one or more artifacts."""

    id: str  # slugified, stable
    type: KnowledgeType
    title: str
    context: str = ""
    decision: str = ""
    why: str = ""
    how: str = ""
    tradeoffs: list[str] = Field(default_factory=list)
    alternatives: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    timestamp: datetime
    sources: list[Source] = Field(default_factory=list)
    # Populated by the linker stage; empty at extraction time.
    relations: list["Relationship"] = Field(default_factory=list)


class Relationship(BaseModel):
    type: RelationType
    target_id: str
    rationale: str | None = None


KnowledgeNode.model_rebuild()
