from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .engine import MediaEngine


def make_handler(engine: MediaEngine) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, payload: object, status: int = 200) -> None:
            body = json.dumps(
                payload,
                default=lambda value: value.value if hasattr(value, "value") else value.__dict__,
            ).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send({"ok": True, "service": "agentic-media-stack"})
                return
            if self.path == "/plan":
                self._send({"items": engine.plan()})
                return
            self._send({"error": "not found"}, 404)

        def log_message(self, format: str, *args: object) -> None:
            return

    return Handler


def serve(engine: MediaEngine, host: str = "0.0.0.0", port: int = 8080) -> None:
    ThreadingHTTPServer((host, port), make_handler(engine)).serve_forever()
