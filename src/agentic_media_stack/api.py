from __future__ import annotations

import json
import mimetypes
from dataclasses import asdict, is_dataclass
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .service import MediaService

STATIC_DIR = Path(__file__).parent / "static"


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if hasattr(value, "value"):
        return value.value
    return value


def make_handler(service: MediaService) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(
            self, payload: object, status: int = 200, headers: dict[str, str] | None = None
        ) -> None:
            body = json.dumps(jsonable(payload), sort_keys=True).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._send({"error": message}, status)

        def _body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1_000_000:
                raise ValueError("request body is too large")
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError("request body must be a JSON object")
            return value

        def _authorized(self) -> bool:
            if not service.auth_required:
                return True
            authorization = self.headers.get("Authorization", "")
            if authorization.casefold().startswith("bearer "):
                token = authorization[7:].strip()
                if service.state.validate_session(token):
                    return True
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            session = cookie.get("media_session")
            return bool(session and service.state.validate_session(session.value))

        def _static(self, path: str) -> None:
            safe_name = "index.html" if path in {"", "/"} else path.removeprefix("/")
            static_root = STATIC_DIR.resolve()
            target = (static_root / safe_name).resolve()
            if static_root not in target.parents or not target.is_file():
                self._error(404, "not found")
                return
            body = target.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(target.name)[0] or "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/app.js", "/styles.css"}:
                self._static(parsed.path)
                return
            if parsed.path == "/health":
                self._send({"ok": True, "service": "agentic-media-stack"})
                return
            if not self._authorized():
                self._error(401, "authentication required")
                return
            try:
                if parsed.path == "/api/status":
                    self._send(service.status())
                elif parsed.path == "/api/dashboard":
                    self._send(service.dashboard())
                elif parsed.path == "/api/config":
                    self._send(service.config.public_dict())
                elif parsed.path == "/api/requests":
                    self._send({"items": service.state.list_requests()})
                elif parsed.path == "/api/downloads":
                    self._send({"items": service.sync_downloads()})
                elif parsed.path == "/api/jobs":
                    self._send({"items": service.state.list_jobs()})
                elif parsed.path == "/api/plan":
                    self._send({"items": service.plan()})
                elif parsed.path == "/api/library":
                    self._send({"items": service.library()})
                elif parsed.path == "/api/audit":
                    limit = int(parse_qs(parsed.query).get("limit", [100])[0])
                    self._send({"items": service.state.list_audit(limit)})
                elif parsed.path == "/api/undo":
                    self._send({"items": service.state.list_undo()})
                elif parsed.path.startswith("/api/requests/") and parsed.path.endswith(
                    "/candidates"
                ):
                    request_id = parsed.path.split("/")[3]
                    self._send({"items": service.candidates(request_id)})
                elif parsed.path.startswith("/api/jobs/"):
                    self._send(service.state.get_job(parsed.path.split("/")[3]) or {}, 200)
                else:
                    self._error(404, "not found")
            except (KeyError, ValueError) as exc:
                self._error(404, str(exc))
            except Exception as exc:
                self._error(500, str(exc))

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/api/auth/login":
                try:
                    token = str(self._body().get("token", ""))
                    session = service.login(token)
                    if not session:
                        self._error(401, "invalid token")
                        return
                    self._send(
                        {"ok": True},
                        headers={
                            "Set-Cookie": (
                                f"media_session={session}; HttpOnly; SameSite=Strict; Path=/"
                            )
                        },
                    )
                except ValueError as exc:
                    self._error(400, str(exc))
                return
            if not self._authorized():
                self._error(401, "authentication required")
                return
            try:
                body = self._body()
                if parsed.path == "/api/requests":
                    kind = str(body.get("kind", "movie"))
                    title = str(body.get("title", "")).strip()
                    if kind not in {"movie", "series", "anime"} or not title:
                        raise ValueError("kind and title are required")
                    self._send(service.create_request(kind, title, body.get("year")), 202)
                elif parsed.path.startswith("/api/requests/") and parsed.path.endswith("/select"):
                    parts = parsed.path.split("/")
                    result = service.select_candidate(parts[3], str(body["candidate_id"]))
                    self._send(result, 202)
                elif parsed.path == "/api/actions/import":
                    result = service.execute_import(
                        str(body["download_id"]), str(body["candidate_id"])
                    )
                    self._send(result)
                elif parsed.path == "/api/actions/undo":
                    self._send({"ok": service.undo(str(body["undo_id"]))})
                elif parsed.path == "/api/actions/repair":
                    self._send({"job_id": service.repair(str(body["download_id"]))}, 202)
                elif parsed.path.startswith("/api/jobs/") and parsed.path.endswith("/retry"):
                    self._send({"job_id": service.retry(parsed.path.split("/")[3])}, 202)
                elif parsed.path == "/api/library/refresh":
                    self._send({"job_id": service.refresh_library()}, 202)
                elif parsed.path == "/api/library/scan":
                    self._send({"job_id": service.refresh_library(scan=True)}, 202)
                elif parsed.path == "/api/backup":
                    destination = str(body.get("destination", ""))
                    if not destination:
                        raise ValueError("destination is required")
                    service.state.backup(destination)
                    self._send({"ok": True})
                else:
                    self._error(404, "not found")
            except PermissionError as exc:
                self._error(409, str(exc))
            except (KeyError, ValueError) as exc:
                self._error(400, str(exc))
            except Exception as exc:
                self._error(500, str(exc))

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def serve(service: MediaService, host: str = "0.0.0.0", port: int = 8080) -> None:
    ThreadingHTTPServer((host, port), make_handler(service)).serve_forever()
