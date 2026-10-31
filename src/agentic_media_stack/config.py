from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    downloads_root: str = "/downloads"
    manifest: str | None = None
    candidate_manifest: str | None = None
    audit_path: str = "/config/audit.jsonl"
    dry_run: bool = True
    restart_cap: int = 2

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            downloads_root=os.getenv("MEDIA_DOWNLOADS_ROOT", "/downloads"),
            manifest=os.getenv("MEDIA_DOWNLOAD_MANIFEST"),
            candidate_manifest=os.getenv("MEDIA_CANDIDATE_MANIFEST"),
            audit_path=os.getenv("MEDIA_AUDIT_PATH", "/config/audit.jsonl"),
            dry_run=os.getenv("MEDIA_DRY_RUN", "true").casefold() not in {"0", "false", "no"},
            restart_cap=int(os.getenv("MEDIA_RESTART_CAP", "2")),
        )
