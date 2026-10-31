from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import AuditEvent


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "[REDACTED]"
                if any(
                    secret in key.casefold()
                    for secret in ("key", "token", "secret", "password", "authorization")
                )
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


class AuditLog:
    def __init__(self, path: str | None = None):
        self.path = Path(path) if path else None
        self.events: list[AuditEvent] = []

    def record(self, event: str, message: str, **data: Any) -> AuditEvent:
        item = AuditEvent(event, message, redact(data), datetime.now(UTC).isoformat())
        self.events.append(item)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(item.as_dict(), sort_keys=True) + "\n")
        return item
