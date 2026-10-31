from __future__ import annotations

from typing import Any, Sequence

from .integrations import IndexerResult
from .models import Download


class MockIndexer:
    name = "local-mock-indexer"

    def search(self, query: str, kind: str = "all") -> Sequence[IndexerResult]:
        lowered = query.casefold()
        matches = [
            ("Chi's Sweet Home", "series", 2024, 6, "chi-sweet-home-s01.torrent"),
            ("Cosmic Princess Kaguya", "movie", 2024, 18, "cosmic-princess-kaguya.torrent"),
            ("Do You Like Big Girls S01E04", "series", None, 4, "big-girls-s01e04.torrent"),
            ("Do You Like Big Girls S01E05", "series", None, 3, "big-girls-s01e05.torrent"),
        ]
        results = []
        for title, result_kind, year, seeders, suffix in matches:
            if lowered not in title.casefold() or kind not in {"all", result_kind, "anime"}:
                continue
            results.append(
                IndexerResult(
                    id=f"mock-{suffix}",
                    title=title,
                    kind=result_kind,
                    indexer=self.name,
                    download_url=f"mock://{suffix}",
                    size_bytes=1024 * 1024 * 800,
                    seeders=seeders,
                    year=year,
                    raw={"source": "mock"},
                )
            )
        return results


class MockQBitTorrent:
    name = "mock-qbittorrent"

    def __init__(self):
        self.items: dict[str, dict[str, Any]] = {}

    def start_download(
        self, download_url: str, *, category: str = "agentic-media-stack"
    ) -> dict[str, Any]:
        item_id = f"mock-{len(self.items) + 1}"
        name = download_url.removeprefix("mock://")
        self.items[item_id] = {
            "id": item_id,
            "name": name,
            "path": f"/downloads/mock/{name}",
            "size_bytes": 800 * 1024 * 1024,
            "progress": 0.0,
            "status": "downloading",
            "completed_at": "unknown",
        }
        return {"id": item_id, "name": name, "status": "queued"}

    def active_downloads(self) -> Sequence[dict[str, Any]]:
        for item in self.items.values():
            item["progress"] = min(1.0, float(item["progress"]) + 0.5)
            if item["progress"] >= 1.0:
                item["status"] = "completed"
        return tuple(self.items.values())

    def completed_downloads(self) -> Sequence[Download]:
        return tuple(
            Download(
                id=item["id"],
                name=item["name"],
                path=item["path"],
                size_bytes=item["size_bytes"],
                completed_at=item["completed_at"],
                client=self.name,
                source="mock",
            )
            for item in self.active_downloads()
            if item["status"] == "completed"
        )


class MockJellyfin:
    name = "mock-jellyfin"

    def __init__(self):
        self.items: list[dict[str, Any]] = []

    def refresh(self) -> bool:
        return True

    def scan(self) -> bool:
        return self.refresh()

    def library_items(self) -> Sequence[dict[str, Any]]:
        return tuple(self.items)

    def verify_path(self, path: str) -> bool:
        return any(item.get("path") == path for item in self.items)
