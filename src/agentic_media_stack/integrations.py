from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Sequence

from .adapters import AdapterError, QBittorrentDownloadClient


class SafeHttp:
    def __init__(self, name: str, base_url: str, *, timeout: float = 10.0):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> Any:
        body = urllib.parse.urlencode(form).encode() if form else None
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Accept": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                if not raw:
                    return None
                return json.loads(raw)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise AdapterError(f"{self.name} request failed ({type(exc).__name__})") from exc


@dataclass(frozen=True)
class IndexerResult:
    id: str
    title: str
    kind: str
    indexer: str
    download_url: str
    size_bytes: int = 0
    seeders: int = 0
    year: int | None = None
    raw: dict[str, Any] | None = None


class ProwlarrIndexer:
    name = "prowlarr"

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0):
        self.http = SafeHttp(self.name, base_url, timeout=timeout)
        self._api_key = api_key

    def search(self, query: str, kind: str = "all") -> Sequence[IndexerResult]:
        payload = self.http.request(
            "/api/v1/search?" + urllib.parse.urlencode({"query": query, "type": "search"}),
            headers={"X-Api-Key": self._api_key},
        )
        if not isinstance(payload, list):
            return []
        results: list[IndexerResult] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            url = item.get("downloadUrl") or item.get("magnetUrl") or item.get("guid")
            title = item.get("title")
            if not url or not title:
                continue
            result_kind = (
                "series"
                if any(token in str(title).casefold() for token in ("s01e", "season", "episode"))
                else "movie"
            )
            if kind not in {"all", result_kind, "anime"}:
                continue
            results.append(
                IndexerResult(
                    id=str(item.get("guid") or item.get("downloadUrl") or title),
                    title=str(title),
                    kind=result_kind,
                    indexer=str(item.get("indexer") or item.get("indexerId") or "prowlarr"),
                    download_url=str(url),
                    size_bytes=int(item.get("size") or 0),
                    seeders=int(item.get("seeders") or 0),
                    year=item.get("year"),
                    raw=item,
                )
            )
        return results


class QBittorrentController(QBittorrentDownloadClient):
    def start_download(
        self, download_url: str, *, category: str = "agentic-media-stack"
    ) -> dict[str, Any]:
        self._login()
        headers = {"Cookie": self._cookie} if self._cookie else {}
        response = self._request(
            "/api/v2/torrents/add",
            method="POST",
            form={"urls": download_url, "category": category},
            headers=headers,
        )
        if response.strip() != b"Ok.":
            raise AdapterError("qbittorrent rejected the download")
        return {"id": f"queued-{abs(hash(download_url))}", "name": download_url, "status": "queued"}

    def active_downloads(self) -> Sequence[dict[str, Any]]:
        self._login()
        headers = {"Cookie": self._cookie} if self._cookie else {}
        try:
            payload = json.loads(self._request("/api/v2/torrents/info?filter=all", headers=headers))
        except (TypeError, ValueError) as exc:
            raise AdapterError("qbittorrent returned invalid JSON") from exc
        if not isinstance(payload, list):
            return []
        return [
            {
                "id": str(item.get("hash") or item.get("name")),
                "name": str(item.get("name", "")),
                "path": str(item.get("content_path") or item.get("save_path") or ""),
                "size_bytes": int(item.get("size") or 0),
                "progress": float(item.get("progress") or 0),
                "status": str(item.get("state") or "unknown"),
                "completed_at": "unknown",
            }
            for item in payload
            if isinstance(item, dict) and item.get("name")
        ]


class JellyfinAdapter:
    name = "jellyfin"

    def __init__(self, base_url: str, api_key: str, *, timeout: float = 10.0):
        self.http = SafeHttp(self.name, base_url, timeout=timeout)
        self._api_key = api_key

    def _headers(self) -> dict[str, str]:
        return {"X-Emby-Token": self._api_key}

    def library_items(self) -> Sequence[dict[str, Any]]:
        payload = self.http.request(
            "/Items?Recursive=true&IncludeItemTypes=Movie,Series&Fields=Path,ProviderIds",
            headers=self._headers(),
        )
        items = payload.get("Items", []) if isinstance(payload, dict) else []
        return [
            {
                "id": str(item.get("Id")),
                "title": str(item.get("Name", "")),
                "kind": "movie" if item.get("Type") == "Movie" else "series",
                "path": str(item.get("Path", "")),
                "jellyfin_id": str(item.get("Id")),
                "verified": bool(item.get("Path")),
                "status": "verified" if item.get("Path") else "unverified",
            }
            for item in items
            if isinstance(item, dict) and item.get("Id") and item.get("Name")
        ]

    def refresh(self) -> bool:
        self.http.request("/Library/Refresh", method="POST", headers=self._headers())
        return True

    def scan(self) -> bool:
        return self.refresh()

    def verify_path(self, path: str) -> bool:
        return any(item.get("path") == path for item in self.library_items())
