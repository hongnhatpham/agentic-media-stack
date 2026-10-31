from __future__ import annotations

import argparse
import json

from .adapters import FolderDownloadClient, JsonMediaApp
from .audit import AuditLog
from .config import Config
from .engine import MediaEngine


def _engine(config: Config) -> MediaEngine:
    # A manifest adapter is local and read-only. Live adapters are registered
    # by a deployment entry point.
    apps = (
        JsonMediaApp.from_manifest_grouped(config.candidate_manifest)
        if config.candidate_manifest
        else []
    )
    return MediaEngine(
        apps,
        [FolderDownloadClient(config.downloads_root, config.manifest)],
        AuditLog(config.audit_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="media-stack", description="Safe media import planning")
    parser.add_argument("command", choices=("plan", "serve"))
    parser.add_argument(
        "--execute", action="store_true", help="execute approved imports; default is dry-run"
    )
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    config = Config.from_env()
    engine = _engine(config)
    if args.command == "plan":
        plan = engine.plan()
        payload: object = plan
        if args.execute and not config.dry_run:
            payload = {"plan": plan, "results": engine.execute_plan(plan, dry_run=False)}
        print(json.dumps(payload, default=_json_default, indent=2))
        return 0
    from .api import serve

    serve(engine, port=args.port)
    return 0


def _json_default(value: object) -> object:
    if hasattr(value, "value"):
        return value.value
    return value.__dict__
