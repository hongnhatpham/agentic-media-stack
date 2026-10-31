from __future__ import annotations

import hmac
from typing import Any

from .adapters import (
    FolderDownloadClient,
    JsonMediaApp,
    MediaAppAdapter,
    radarr_adapter,
    sonarr_adapter,
)
from .audit import AuditLog
from .config import Config
from .engine import MediaEngine
from .integrations import JellyfinAdapter, ProwlarrIndexer, QBittorrentController
from .jobs import JobManager
from .mock import MockIndexer, MockJellyfin, MockQBitTorrent
from .models import ImportResult, PlanItem
from .state import StateStore


class DurableAuditLog(AuditLog):
    def __init__(self, path: str, state: StateStore):
        super().__init__(path)
        self.state = state

    def record(self, event: str, message: str, **data: Any):
        item = super().record(event, message, **data)
        self.state.record_audit(event, message, item.data)
        return item


class MediaService:
    def __init__(
        self,
        config: Config,
        state: StateStore,
        engine: MediaEngine,
        *,
        indexer: Any = None,
        qbit: Any = None,
        jellyfin: Any = None,
    ):
        self.config = config
        self.state = state
        self.engine = engine
        self.indexer = indexer
        self.qbit = qbit
        self.jellyfin = jellyfin
        self.jobs = JobManager(state)

    @property
    def auth_required(self) -> bool:
        return bool(self.config.auth_token)

    def login(self, token: str) -> str | None:
        if not self.config.auth_token or hmac.compare_digest(token, self.config.auth_token):
            return self.state.create_session(token)
        return None

    def status(self) -> dict[str, Any]:
        validation = self.config.validate()
        return {
            "ok": validation.valid,
            "dry_run": self.config.dry_run,
            "auth_required": self.auth_required,
            "adapters": {
                "media_apps": [app.name for app in self.engine.apps],
                "download_clients": [client.name for client in self.engine.clients],
                "indexer": getattr(self.indexer, "name", None),
                "jellyfin": getattr(self.jellyfin, "name", None),
            },
            "counts": {
                "requests": len(self.state.list_requests()),
                "downloads": len(self.state.list_downloads()),
                "jobs": len(self.state.list_jobs()),
                "library": len(self.state.list_library()),
                "review": sum(
                    1 for request in self.state.list_requests() if request["status"] == "review"
                ),
            },
            "warnings": list(validation.warnings),
        }

    def dashboard(self) -> dict[str, Any]:
        return {
            "status": self.status(),
            "requests": self.state.list_requests()[:20],
            "downloads": self.state.list_downloads()[:20],
            "jobs": self.state.list_jobs(20),
            "library": self.state.list_library()[:20],
            "audit": self.state.list_audit(30),
        }

    def create_request(self, kind: str, title: str, year: int | None = None) -> dict[str, Any]:
        request = self.state.create_request(kind, title, year)
        job_id = self.jobs.submit(
            "search",
            lambda job: self._search_job(job, request["id"], title, kind),
            {"request_id": request["id"], "title": title, "kind": kind},
        )
        request["job_id"] = job_id
        return request

    def _search_job(
        self, job_id: str, request_id: str, title: str, kind: str
    ) -> list[dict[str, Any]]:
        if not self.indexer:
            raise RuntimeError("no indexer is configured")
        self.state.update_job(job_id, progress=0.2, message="searching configured indexer")
        results = self.indexer.search(title, kind)
        candidates = [
            {
                "id": result.id,
                "title": result.title,
                "kind": result.kind,
                "year": result.year,
                "indexer": result.indexer,
                "download_url": result.download_url,
                "size_bytes": result.size_bytes,
                "seeders": result.seeders,
                "raw": result.raw or {},
            }
            for result in results
        ]
        self.state.replace_candidates(request_id, candidates)
        self.state.update_request(request_id, "review" if candidates else "failed")
        self.state.record_audit(
            "search",
            "indexer search completed",
            {"request_id": request_id, "count": len(candidates)},
        )
        return candidates

    def candidates(self, request_id: str) -> list[dict[str, Any]]:
        return self.state.list_candidates(request_id)

    def select_candidate(self, request_id: str, candidate_id: str) -> dict[str, Any]:
        candidate = self.state.get_candidate(candidate_id)
        if not candidate or candidate["request_id"] != request_id:
            raise KeyError("candidate does not belong to request")
        self.state.update_request(request_id, "downloading", candidate_id=candidate_id)
        job_id = self.jobs.submit(
            "download",
            lambda job: self._download_job(job, request_id, candidate),
            {"request_id": request_id, "candidate_id": candidate_id},
        )
        return {"request_id": request_id, "candidate_id": candidate_id, "job_id": job_id}

    def _download_job(
        self, job_id: str, request_id: str, candidate: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.qbit:
            raise RuntimeError("qBittorrent is not configured")
        self.state.update_job(job_id, progress=0.2, message="sending release to qBittorrent")
        queued = self.qbit.start_download(candidate["download_url"])
        download = self.state.create_download(
            {
                "id": queued["id"],
                "request_id": request_id,
                "candidate_id": candidate["id"],
                "client": self.qbit.name,
                "name": queued.get("name", candidate["title"]),
                "status": queued.get("status", "queued"),
            }
        )
        self.state.record_audit(
            "download_started", "release sent to qBittorrent", {"download_id": download["id"]}
        )
        return download

    def sync_downloads(self) -> list[dict[str, Any]]:
        if not self.qbit or not hasattr(self.qbit, "active_downloads"):
            return self.state.list_downloads()
        for item in self.qbit.active_downloads():
            existing = self.state.get_download(item["id"])
            if existing:
                self.state.update_download(item["id"], **item)
            else:
                self.state.create_download({"client": self.qbit.name, **item})
        return self.state.list_downloads()

    def plan(self) -> list[PlanItem]:
        return self.engine.plan()

    def execute_import(self, download_id: str, candidate_id: str) -> ImportResult:
        if self.config.dry_run:
            raise PermissionError(
                "dry-run is enabled; set MEDIA_DRY_RUN=false before executing imports"
            )
        item = next(
            (
                item
                for item in self.engine.plan()
                if item.match.download.id == download_id
                and item.match.candidate.media_id == candidate_id
            ),
            None,
        )
        if item is None:
            raise KeyError("no safe plan item matches that download and candidate")
        result = self.engine.execute(item, dry_run=False)
        if result.ok and result.rollback:
            undo_id = self.state.create_undo(
                result.rollback["app"], result.rollback["media_id"], result.rollback["path"]
            )
            download = self.state.get_download(download_id)
            if download:
                self.state.update_download(download_id, status="imported", progress=1.0)
                if download.get("request_id"):
                    self.state.update_request(download["request_id"], "imported")
            self.state.record_audit(
                "undo_available",
                "verified import can be undone when adapter supports it",
                {"undo_id": undo_id},
            )
            if self.jellyfin:
                self.refresh_library()
        return result

    def undo(self, undo_id: str) -> bool:
        record = self.state.get_undo(undo_id)
        if not record:
            raise KeyError("undo record not found")
        app = next((item for item in self.engine.apps if item.name == record["app"]), None)
        if not app:
            raise RuntimeError("adapter for undo record is not configured")
        ok = bool(getattr(app, "supports_rollback", False)) and app.rollback(record)
        self.state.update_undo(undo_id, "undone" if ok else "unsupported")
        self.state.record_audit("undo", "undo requested", {"undo_id": undo_id, "ok": ok})
        return ok

    def repair(self, download_id: str) -> str:
        return self.jobs.submit(
            "repair", lambda job: self._repair_job(job, download_id), {"download_id": download_id}
        )

    def _repair_job(self, job_id: str, download_id: str) -> dict[str, Any]:
        self.state.update_job(job_id, progress=0.3, message="rebuilding media graph")
        items = [item for item in self.engine.plan() if item.match.download.id == download_id]
        self.state.record_audit(
            "repair", "repair plan rebuilt", {"download_id": download_id, "matches": len(items)}
        )
        return {"download_id": download_id, "matches": len(items)}

    def retry(self, job_id: str) -> str:
        job = self.state.get_job(job_id)
        if not job:
            raise KeyError("job not found")
        payload = job["payload"]
        if job["kind"] == "search":
            return self.jobs.submit(
                "search",
                lambda new: self._search_job(
                    new, payload["request_id"], payload["title"], payload["kind"]
                ),
                payload,
            )
        if job["kind"] == "download":
            candidate = self.state.get_candidate(payload["candidate_id"])
            if not candidate:
                raise KeyError("candidate not found")
            return self.jobs.submit(
                "download",
                lambda new: self._download_job(new, payload["request_id"], candidate),
                payload,
            )
        if job["kind"] == "repair":
            return self.repair(payload["download_id"])
        raise ValueError("job type cannot be retried")

    def library(self) -> list[dict[str, Any]]:
        return self.state.list_library()

    def refresh_library(self, *, scan: bool = False) -> str:
        kind = "jellyfin-scan" if scan else "jellyfin-refresh"
        return self.jobs.submit(kind, lambda job: self._jellyfin_job(job, scan=scan))

    def _jellyfin_job(self, job_id: str, *, scan: bool = False) -> dict[str, Any]:
        if not self.jellyfin:
            raise RuntimeError("Jellyfin is not configured")
        if scan and hasattr(self.jellyfin, "scan"):
            self.jellyfin.scan()
        else:
            self.jellyfin.refresh()
        self.state.update_job(job_id, progress=0.5, message="reading Jellyfin library")
        items = list(self.jellyfin.library_items())
        for item in items:
            self.state.upsert_library(item)
        self.state.record_audit(
            "jellyfin_scan" if scan else "jellyfin_refresh",
            "Jellyfin library refreshed and verified",
            {"count": len(items)},
        )
        return {"count": len(items)}


def build_service(config: Config) -> MediaService:
    state = StateStore(config.state_path)
    audit = DurableAuditLog(config.audit_path, state)
    apps: list[MediaAppAdapter] = []
    if config.candidate_manifest:
        apps.extend(JsonMediaApp.from_manifest_grouped(config.candidate_manifest))
    if config.sonarr_url and config.sonarr_api_key:
        apps.append(
            sonarr_adapter(config.sonarr_url, config.sonarr_api_key, timeout=config.http_timeout)
        )
    if config.radarr_url and config.radarr_api_key:
        apps.append(
            radarr_adapter(config.radarr_url, config.radarr_api_key, timeout=config.http_timeout)
        )
    clients: list[Any] = []
    if "filesystem" in config.download_clients:
        clients.append(FolderDownloadClient(config.downloads_root, config.manifest))
    if "qbittorrent" in config.download_clients and config.qbittorrent_url:
        clients.append(
            QBittorrentController(
                config.qbittorrent_url,
                config.qbittorrent_username or "",
                config.qbittorrent_password or "",
                timeout=config.http_timeout,
            )
        )
    if "sabnzbd" in config.download_clients and config.sabnzbd_url and config.sabnzbd_api_key:
        from .adapters import SabnzbdDownloadClient

        clients.append(
            SabnzbdDownloadClient(
                config.sabnzbd_url, config.sabnzbd_api_key, timeout=config.http_timeout
            )
        )
    indexer = (
        ProwlarrIndexer(config.indexer_url, config.indexer_api_key, timeout=config.http_timeout)
        if config.indexer_url and config.indexer_api_key
        else None
    )
    qbit = next(
        (client for client in clients if getattr(client, "name", "") == "qbittorrent"), None
    )
    jellyfin = (
        JellyfinAdapter(config.jellyfin_url, config.jellyfin_api_key, timeout=config.http_timeout)
        if config.jellyfin_url and config.jellyfin_api_key
        else None
    )
    if config.mock_mode:
        indexer, qbit, jellyfin = MockIndexer(), MockQBitTorrent(), MockJellyfin()
        clients = [qbit]
    engine = MediaEngine(apps, clients, audit)
    service = MediaService(config, state, engine, indexer=indexer, qbit=qbit, jellyfin=jellyfin)
    if config.mock_mode:
        service.qbit = qbit
    return service
