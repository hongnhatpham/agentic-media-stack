from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MediaKind(StrEnum):
    MOVIE = "movie"
    SERIES = "series"
    EPISODE = "episode"
    UNKNOWN = "unknown"


class PlanAction(StrEnum):
    IMPORT = "import"
    REVIEW = "review"
    SKIP = "skip"


@dataclass(frozen=True)
class Download:
    id: str
    name: str
    path: str
    size_bytes: int
    completed_at: str
    client: str = "unknown"
    source: str = "unknown"


@dataclass(frozen=True)
class MediaCandidate:
    app: str
    kind: MediaKind
    media_id: str
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    file_path: str | None = None


@dataclass(frozen=True)
class Provenance:
    download_id: str
    source: str
    client: str
    observed_path: str
    completed_at: str


@dataclass(frozen=True)
class Match:
    download: Download
    candidate: MediaCandidate
    provenance: Provenance
    score: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class MediaGraph:
    """The shared view joining completed downloads to app candidates."""

    downloads: tuple[Download, ...]
    candidates: tuple[MediaCandidate, ...]
    matches: tuple[Match, ...]


@dataclass(frozen=True)
class Verification:
    ok: bool
    message: str
    observed_path: str | None = None
    media_id: str | None = None


@dataclass(frozen=True)
class PlanItem:
    action: PlanAction
    match: Match
    explanation: str
    safe_to_execute: bool


@dataclass(frozen=True)
class ImportResult:
    ok: bool
    item: PlanItem
    verification: Verification
    rollback: dict[str, Any] | None = None


@dataclass
class AuditEvent:
    event: str
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp,
        }
