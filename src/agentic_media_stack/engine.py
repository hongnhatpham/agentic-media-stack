from __future__ import annotations

from collections.abc import Sequence

from .adapters import DownloadClientAdapter, MediaAppAdapter
from .audit import AuditLog
from .matching import find_matches
from .models import ImportResult, Match, MediaGraph, PlanAction, PlanItem, Verification
from .planner import build_plan


class MediaEngine:
    def __init__(
        self,
        apps: Sequence[MediaAppAdapter],
        clients: Sequence[DownloadClientAdapter],
        audit: AuditLog | None = None,
    ):
        self.apps = list(apps)
        self.clients = list(clients)
        self.audit = audit or AuditLog()

    def build_graph(self) -> MediaGraph:
        matches: list[Match] = []
        candidates = [candidate for app in self.apps for candidate in app.candidates()]
        downloads_seen = []
        for client in self.clients:
            downloads = client.completed_downloads()
            downloads_seen.extend(downloads)
            self.audit.record(
                "discovery", "read completed downloads", client=client.name, count=len(downloads)
            )
            for download in downloads:
                found = find_matches(download, candidates)
                matches.extend(found)
                self.audit.record(
                    "match",
                    "evaluated download candidates",
                    download_id=download.id,
                    candidates=len(found),
                )
        return MediaGraph(tuple(downloads_seen), tuple(candidates), tuple(matches))

    def discover(self) -> list[Match]:
        return list(self.build_graph().matches)

    def plan(self) -> list[PlanItem]:
        return build_plan(self.discover())

    def execute(self, item: PlanItem, *, dry_run: bool = True) -> ImportResult:
        if item.action != PlanAction.IMPORT or not item.safe_to_execute:
            verification = Verification(False, "item is not an approved safe import")
            self.audit.record("review_required", item.explanation, action=item.action.value)
            return ImportResult(False, item, verification)
        if dry_run:
            self.audit.record("dry_run", item.explanation, media_id=item.match.candidate.media_id)
            return ImportResult(
                True, item, Verification(True, "dry run: no external write performed")
            )
        app = next(app for app in self.apps if app.name == item.match.candidate.app)
        accepted = app.import_file(item.match.candidate, item.match.download)
        verification = app.verify_import(item.match.candidate, item.match.download, accepted)
        rollback = None
        if verification.ok:
            rollback = {
                "app": app.name,
                "media_id": item.match.candidate.media_id,
                "path": item.match.download.path,
            }
            self.audit.record(
                "import",
                "import accepted; verification recorded",
                media_id=item.match.candidate.media_id,
                path=item.match.download.path,
                rollback_available=bool(getattr(app, "supports_rollback", False)),
            )
        else:
            self.audit.record(
                "import_failed", verification.message, media_id=item.match.candidate.media_id
            )
        return ImportResult(verification.ok, item, verification, rollback)

    def execute_plan(self, plan: Sequence[PlanItem], *, dry_run: bool = True) -> list[ImportResult]:
        return [self.execute(item, dry_run=dry_run) for item in plan]

    def rollback(self, result: ImportResult) -> bool:
        if not result.rollback:
            return False
        app = next((app for app in self.apps if app.name == result.rollback.get("app")), None)
        if app is None:
            self.audit.record(
                "rollback_failed", "adapter is no longer configured", app=result.rollback.get("app")
            )
            return False
        supported = bool(getattr(app, "supports_rollback", False))
        ok = supported and app.rollback(result.rollback)
        self.audit.record("rollback", "rollback requested", app=app.name, ok=ok)
        return ok
