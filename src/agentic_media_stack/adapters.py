from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, Sequence

from .models import Download, MediaCandidate, MediaKind, Verification


class AdapterError(RuntimeError):
    """An adapter failure with a message safe to put in an audit log."""


class MediaAppAdapter(Protocol):
    name: str

    def candidates(self) -> Sequence[MediaCandidate]: ...

    def import_file(self, candidate: MediaCandidate, download: Download) -> Verification: ...

    def verify_import(
        self, candidate: MediaCandidate, download: Download, accepted: Verification
    ) -> Verification: ...

    def rollback(self, record: dict[str, object]) -> bool: ...


class DownloadClientAdapter(Protocol):
    name: str

    def completed_downloads(self) -> Sequence[Download]: ...


class InMemoryMediaApp:
    """A deterministic adapter used by tests and local dry runs."""

    def __init__(
        self, name: str, items: Sequence[MediaCandidate], *, supports_rollback: bool = True
    ):
        self.name = name
        self._items = list(items)
        self.supports_rollback = supports_rollback
        self.imported: list[tuple[str, str]] = []

    def candidates(self) -> Sequence[MediaCandidate]:
        return tuple(self._items)

    def import_file(self, candidate: MediaCandidate, download: Download) -> Verification:
        self.imported.append((candidate.media_id, download.path))
        return Verification(
            True, "media app accepted the import", download.path, candidate.media_id
        )

    def verify_import(
        self, candidate: MediaCandidate, download: Download, accepted: Verification
    ) -> Verification:
        return Verification(
            accepted.ok, "mock read-back verified", download.path, candidate.media_id
        )

    def rollback(self, record: dict[str, object]) -> bool:
        if not self.supports_rollback:
            return False
        pair = (str(record.get("media_id")), str(record.get("path")))
        if pair in self.imported:
            self.imported.remove(pair)
        return True


class JsonMediaApp(InMemoryMediaApp):
    """Read candidate metadata from a deployment-owned JSON fixture."""

    @classmethod
    def from_manifest(cls, path: str, *, name: str = "manifest") -> "JsonMediaApp":
        payload = json.loads(Path(path).read_text())
        items = [
            MediaCandidate(
                app=str(item.get("app", name)),
                kind=MediaKind(str(item.get("kind", "unknown"))),
                media_id=str(item["media_id"]),
                title=str(item["title"]),
                year=item.get("year"),
                season=item.get("season"),
                episode=item.get("episode"),
                file_path=item.get("file_path"),
                parent_id=item.get("parent_id"),
            )
            for item in payload
            if isinstance(item, dict) and item.get("media_id") and item.get("title")
        ]
        return cls(name, items)

    @classmethod
    def from_manifest_grouped(cls, path: str) -> list["JsonMediaApp"]:
        payload = json.loads(Path(path).read_text())
        grouped: dict[str, list[MediaCandidate]] = {}
        for item in payload:
            if not isinstance(item, dict) or not item.get("media_id") or not item.get("title"):
                continue
            app = str(item.get("app", "manifest"))
            grouped.setdefault(app, []).append(
                MediaCandidate(
                    app=app,
                    kind=MediaKind(str(item.get("kind", "unknown"))),
                    media_id=str(item["media_id"]),
                    title=str(item["title"]),
                    year=item.get("year"),
                    season=item.get("season"),
                    episode=item.get("episode"),
                    file_path=item.get("file_path"),
                    parent_id=item.get("parent_id"),
                )
            )
        return [cls(name, items) for name, items in sorted(grouped.items())]


class FolderDownloadClient:
    """Read completed download metadata from a JSON file or a simple folder."""

    name = "folder"

    def __init__(self, root: str, manifest: str | None = None):
        self.root = Path(root)
        self.manifest = Path(manifest) if manifest else None

    def completed_downloads(self) -> Sequence[Download]:
        if self.manifest:
            payload = json.loads(self.manifest.read_text())
            return [Download(**entry) for entry in payload]
        if not self.root.exists():
            return []
        return [
            Download(
                id=path.name,
                name=path.name,
                path=str(path),
                size_bytes=path.stat().st_size,
                completed_at="unknown",
                client=self.name,
                source="filesystem",
            )
            for path in sorted(self.root.rglob("*"))
            if path.is_file()
        ]


class HttpMediaApp:
    """Small JSON adapter for Sonarr/Radarr-compatible endpoints.

    It is intentionally opt-in: constructing it does not make a request. The
    engine can be pointed at a read-only API for discovery and at an import
    endpoint supplied by a deployment when an explicit action is approved.
    """

    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        *,
        candidates_path: str = "/api/v3/series",
        timeout: float = 10.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.candidates_path = candidates_path
        self.timeout = timeout

    def _request(self, path: str, *, method: str = "GET", body: bytes | None = None) -> object:
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"X-Api-Key": self._api_key, "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read())
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise AdapterError(f"{self.name} request failed ({type(exc).__name__})") from exc

    def candidates(self) -> Sequence[MediaCandidate]:
        payload = self._request(self.candidates_path)
        if not isinstance(payload, list):
            return []
        result: list[MediaCandidate] = []
        if "series" in self.candidates_path:
            for series in payload:
                if not isinstance(series, dict) or not series.get("id") or not series.get("title"):
                    continue
                episodes = self._request(f"/api/v3/episode?seriesId={series['id']}")
                if not isinstance(episodes, list):
                    continue
                for episode in episodes:
                    if not isinstance(episode, dict) or episode.get("hasFile"):
                        continue
                    season = episode.get("seasonNumber")
                    number = episode.get("episodeNumber")
                    if season is None or number is None:
                        continue
                    result.append(
                        MediaCandidate(
                            app=self.name,
                            kind=MediaKind.SERIES,
                            media_id=str(episode.get("id") or f"{series['id']}-{season}-{number}"),
                            title=str(series["title"]),
                            season=int(season),
                            episode=int(number),
                            parent_id=str(series["id"]),
                        )
                    )
            return result
        for item in payload:
            if (
                not isinstance(item, dict)
                or not item.get("id")
                or not item.get("title")
                or item.get("hasFile")
            ):
                continue
            result.append(
                MediaCandidate(
                    app=self.name,
                    kind=MediaKind.SERIES if "series" in self.candidates_path else MediaKind.MOVIE,
                    media_id=str(item["id"]),
                    title=str(item["title"]),
                    year=item.get("year"),
                )
            )
        return result

    def import_file(self, candidate: MediaCandidate, download: Download) -> Verification:
        command_name = (
            "DownloadedEpisodesScan" if "series" in self.candidates_path else "DownloadedMoviesScan"
        )
        body = json.dumps({"name": command_name, "path": download.path}).encode()
        try:
            result = self._request("/api/v3/command", method="POST", body=body)
        except AdapterError as exc:
            return Verification(False, str(exc))
        command_id = result.get("id") if isinstance(result, dict) else None
        return Verification(
            True,
            "media app accepted import command",
            download.path,
            str(command_id or candidate.media_id),
        )

    def verify_import(
        self, candidate: MediaCandidate, download: Download, accepted: Verification
    ) -> Verification:
        if not accepted.ok:
            return accepted
        if "series" in self.candidates_path:
            query = urllib.parse.urlencode(
                {
                    "seriesId": candidate.parent_id or candidate.media_id,
                    "seasonNumber": candidate.season,
                    "episodeNumber": candidate.episode,
                }
            )
            endpoint = f"/api/v3/episode?{query}"
        else:
            endpoint = f"/api/v3/movie/{candidate.media_id}"
        try:
            payload = self._request(endpoint)
        except AdapterError as exc:
            return Verification(False, f"import accepted but read-back verification failed: {exc}")
        observed = json.dumps(payload)
        expected_path = candidate.file_path or download.path
        if expected_path in observed:
            return Verification(
                True, "read-back verified imported path", expected_path, candidate.media_id
            )
        return Verification(False, "import command accepted but imported path is not visible yet")

    def rollback(self, record: dict[str, object]) -> bool:
        return False


def sonarr_adapter(base_url: str, api_key: str, *, timeout: float = 10.0) -> HttpMediaApp:
    return HttpMediaApp(
        "sonarr", base_url, api_key, candidates_path="/api/v3/series", timeout=timeout
    )


def radarr_adapter(base_url: str, api_key: str, *, timeout: float = 10.0) -> HttpMediaApp:
    return HttpMediaApp(
        "radarr", base_url, api_key, candidates_path="/api/v3/movie", timeout=timeout
    )


class HttpDownloadClient:
    """Shared safe HTTP plumbing for qBittorrent and SABnzbd adapters."""

    def __init__(self, name: str, base_url: str, *, timeout: float = 10.0):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        form: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> bytes:
        body = urllib.parse.urlencode(form).encode() if form else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Accept": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise AdapterError(f"{self.name} request failed ({type(exc).__name__})") from exc


class QBittorrentDownloadClient(HttpDownloadClient):
    name = "qbittorrent"

    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        timeout: float = 10.0,
    ):
        super().__init__(self.name, base_url, timeout=timeout)
        self.username = username
        self._password = password
        self._cookie: str | None = None

    def _login(self) -> None:
        request = urllib.request.Request(
            self.base_url + "/api/v2/auth/login",
            data=urllib.parse.urlencode(
                {"username": self.username, "password": self._password}
            ).encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                if response.read().strip() != b"Ok.":
                    raise AdapterError("qbittorrent login was rejected")
                self._cookie = response.headers.get("Set-Cookie", "").split(";", 1)[0]
        except AdapterError:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            raise AdapterError(f"qbittorrent login failed ({type(exc).__name__})") from exc

    def completed_downloads(self) -> Sequence[Download]:
        self._login()
        headers = {"Cookie": self._cookie} if self._cookie else {}
        try:
            payload = json.loads(
                self._request("/api/v2/torrents/info?filter=completed", headers=headers)
            )
        except (TypeError, ValueError) as exc:
            raise AdapterError("qbittorrent returned invalid JSON") from exc
        if not isinstance(payload, list):
            return []
        return [
            Download(
                id=str(item.get("hash") or item.get("name")),
                name=str(item.get("name", "")),
                path=str(item.get("content_path") or item.get("save_path") or ""),
                size_bytes=int(item.get("size") or 0),
                completed_at=datetime.fromtimestamp(
                    float(item.get("completion_on") or 0), tz=UTC
                ).isoformat()
                if item.get("completion_on")
                else "unknown",
                client=self.name,
                source="qbittorrent",
            )
            for item in payload
            if isinstance(item, dict) and item.get("name")
        ]


class SabnzbdDownloadClient(HttpDownloadClient):
    name = "sabnzbd"

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0):
        super().__init__(self.name, base_url, timeout=timeout)
        self._api_key = api_key

    def completed_downloads(self) -> Sequence[Download]:
        query = urllib.parse.urlencode(
            {"mode": "history", "output": "json", "apikey": self._api_key, "limit": "100"}
        )
        try:
            payload = json.loads(self._request(f"/api?{query}"))
        except (TypeError, ValueError) as exc:
            raise AdapterError("sabnzbd returned invalid JSON") from exc
        history = payload.get("history", {}) if isinstance(payload, dict) else {}
        slots = history.get("slots", []) if isinstance(history, dict) else []
        return [
            Download(
                id=str(item.get("nzo_id") or item.get("name")),
                name=str(item.get("name", "")),
                path=str(item.get("storage") or ""),
                size_bytes=int(float(item.get("bytes") or 0)),
                completed_at=str(item.get("completed") or "unknown"),
                client=self.name,
                source="sabnzbd",
            )
            for item in slots
            if isinstance(item, dict)
            and str(item.get("status", "")).casefold() == "completed"
            and item.get("name")
        ]


_MEDIA_TOKEN = re.compile(r"[a-z0-9]+")


def normalise_title(value: str) -> tuple[str, ...]:
    return tuple(_MEDIA_TOKEN.findall(value.casefold()))
