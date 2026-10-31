from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(UTC).isoformat()


class StateStore:
    """Small SQLite store for durable application state and audit history."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self.migrate()

    def migrate(self) -> None:
        with self._lock, self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );
                INSERT INTO schema_version(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    year INTEGER,
                    status TEXT NOT NULL,
                    selected_candidate_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS candidates (
                    id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    year INTEGER,
                    indexer TEXT NOT NULL,
                    download_url TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    seeders INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'available',
                    raw_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(request_id) REFERENCES requests(id)
                );
                CREATE TABLE IF NOT EXISTS downloads (
                    id TEXT PRIMARY KEY,
                    request_id TEXT,
                    candidate_id TEXT,
                    client TEXT NOT NULL,
                    name TEXT NOT NULL,
                    path TEXT NOT NULL DEFAULT '',
                    size_bytes INTEGER NOT NULL DEFAULT 0,
                    progress REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    error TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS library (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    path TEXT NOT NULL,
                    jellyfin_id TEXT,
                    verified INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event TEXT NOT NULL,
                    message TEXT NOT NULL,
                    data_json TEXT NOT NULL DEFAULT '{}',
                    timestamp TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS undo_records (
                    id TEXT PRIMARY KEY,
                    app TEXT NOT NULL,
                    media_id TEXT NOT NULL,
                    path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'available',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS candidates_request_idx ON candidates(request_id);
                CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status, updated_at);
                CREATE INDEX IF NOT EXISTS audit_timestamp_idx ON audit(timestamp);
                """
            )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _row(self, query: str, args: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(query, args).fetchone()
        return dict(row) if row else None

    def _rows(self, query: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    def _write(self, query: str, args: tuple[Any, ...] = ()) -> None:
        with self._lock, self._connection:
            self._connection.execute(query, args)

    def record_audit(self, event: str, message: str, data: dict[str, Any] | None = None) -> None:
        self._write(
            "INSERT INTO audit(event, message, data_json, timestamp) VALUES (?, ?, ?, ?)",
            (event, message, json.dumps(data or {}, sort_keys=True), now()),
        )

    def list_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT id, event, message, data_json, timestamp FROM audit ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        for row in rows:
            row["data"] = json.loads(row.pop("data_json"))
        return rows

    def create_request(self, kind: str, title: str, year: int | None = None) -> dict[str, Any]:
        request_id = secrets.token_urlsafe(10)
        timestamp = now()
        self._write(
            "INSERT INTO requests(id, kind, title, year, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (request_id, kind, title, year, "searching", timestamp, timestamp),
        )
        return self.get_request(request_id) or {}

    def get_request(self, request_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM requests WHERE id = ?", (request_id,))

    def list_requests(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM requests ORDER BY updated_at DESC")

    def update_request(
        self, request_id: str, status: str, *, candidate_id: str | None = None
    ) -> None:
        self._write(
            "UPDATE requests SET status = ?, selected_candidate_id = "
            "COALESCE(?, selected_candidate_id), updated_at = ? WHERE id = ?",
            (status, candidate_id, now(), request_id),
        )

    def replace_candidates(self, request_id: str, candidates: list[dict[str, Any]]) -> None:
        with self._lock, self._connection:
            self._connection.execute("DELETE FROM candidates WHERE request_id = ?", (request_id,))
            timestamp = now()
            self._connection.executemany(
                "INSERT INTO candidates(id, request_id, title, kind, year, indexer, "
                "download_url, size_bytes, seeders, status, raw_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item["id"],
                        request_id,
                        item["title"],
                        item["kind"],
                        item.get("year"),
                        item["indexer"],
                        item["download_url"],
                        item.get("size_bytes", 0),
                        item.get("seeders", 0),
                        item.get("status", "available"),
                        json.dumps(item.get("raw", {}), sort_keys=True),
                        timestamp,
                    )
                    for item in candidates
                ],
            )

    def list_candidates(self, request_id: str) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT * FROM candidates WHERE request_id = ? ORDER BY seeders DESC, size_bytes DESC",
            (request_id,),
        )
        for row in rows:
            row["raw"] = json.loads(row.pop("raw_json"))
        return rows

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM candidates WHERE id = ?", (candidate_id,))
        if row:
            row["raw"] = json.loads(row.pop("raw_json"))
        return row

    def create_download(self, data: dict[str, Any]) -> dict[str, Any]:
        self._write(
            "INSERT OR REPLACE INTO downloads(id, request_id, candidate_id, client, name, path, "
            "size_bytes, progress, status, error, completed_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data.get("request_id"),
                data.get("candidate_id"),
                data["client"],
                data["name"],
                data.get("path", ""),
                data.get("size_bytes", 0),
                data.get("progress", 0),
                data.get("status", "queued"),
                data.get("error"),
                data.get("completed_at"),
                now(),
            ),
        )
        return self.get_download(data["id"]) or {}

    def update_download(self, download_id: str, **changes: Any) -> None:
        allowed = {"path", "size_bytes", "progress", "status", "error", "completed_at", "name"}
        changes = {key: value for key, value in changes.items() if key in allowed}
        if not changes:
            return
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self._write(
            f"UPDATE downloads SET {assignments}, updated_at = ? WHERE id = ?",
            (*changes.values(), now(), download_id),
        )

    def get_download(self, download_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM downloads WHERE id = ?", (download_id,))

    def list_downloads(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM downloads ORDER BY updated_at DESC")

    def create_job(self, kind: str, payload: dict[str, Any] | None = None) -> str:
        job_id = secrets.token_urlsafe(10)
        timestamp = now()
        self._write(
            "INSERT INTO jobs(id, kind, status, payload_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                job_id,
                kind,
                "queued",
                json.dumps(payload or {}, sort_keys=True),
                timestamp,
                timestamp,
            ),
        )
        return job_id

    def update_job(self, job_id: str, **changes: Any) -> None:
        allowed = {"status", "progress", "message", "error", "payload_json"}
        changes = {key: value for key, value in changes.items() if key in allowed}
        if not changes:
            return
        assignments = ", ".join(f"{key} = ?" for key in changes)
        self._write(
            f"UPDATE jobs SET {assignments}, updated_at = ? WHERE id = ?",
            (*changes.values(), now(), job_id),
        )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self._row("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if row:
            row["payload"] = json.loads(row.pop("payload_json"))
        return row

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT ?", (max(1, min(limit, 200)),)
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json"))
        return rows

    def upsert_library(self, data: dict[str, Any]) -> None:
        self._write(
            "INSERT OR REPLACE INTO library(id, kind, title, path, jellyfin_id, verified, status, "
            "updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["id"],
                data["kind"],
                data["title"],
                data["path"],
                data.get("jellyfin_id"),
                int(data.get("verified", False)),
                data.get("status", "verified"),
                now(),
            ),
        )

    def list_library(self) -> list[dict[str, Any]]:
        rows = self._rows("SELECT * FROM library ORDER BY updated_at DESC")
        for row in rows:
            row["verified"] = bool(row["verified"])
        return rows

    def create_undo(self, app: str, media_id: str, path: str) -> str:
        record_id = secrets.token_urlsafe(10)
        timestamp = now()
        self._write(
            "INSERT INTO undo_records(id, app, media_id, path, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (record_id, app, media_id, path, "available", timestamp, timestamp),
        )
        return record_id

    def get_undo(self, record_id: str) -> dict[str, Any] | None:
        return self._row("SELECT * FROM undo_records WHERE id = ?", (record_id,))

    def list_undo(self) -> list[dict[str, Any]]:
        return self._rows("SELECT * FROM undo_records ORDER BY created_at DESC")

    def update_undo(self, record_id: str, status: str) -> None:
        self._write(
            "UPDATE undo_records SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), record_id),
        )

    def create_session(self, token: str, hours: int = 24) -> str:
        session = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(hours=hours)
        token_hash = hashlib.sha256(session.encode()).hexdigest()
        self._write(
            "INSERT INTO sessions(token_hash, created_at, expires_at) VALUES (?, ?, ?)",
            (token_hash, now(), expires.isoformat()),
        )
        return session

    def validate_session(self, session: str) -> bool:
        token_hash = hashlib.sha256(session.encode()).hexdigest()
        row = self._row("SELECT expires_at FROM sessions WHERE token_hash = ?", (token_hash,))
        if not row:
            return False
        return datetime.fromisoformat(row["expires_at"]) > datetime.now(UTC)

    def backup(self, destination: str) -> None:
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as backup_connection, self._lock:
            self._connection.backup(backup_connection)
