from __future__ import annotations

import argparse
import json
import sys

from .adapters import (
    FolderDownloadClient,
    JsonMediaApp,
    QBittorrentDownloadClient,
    SabnzbdDownloadClient,
    radarr_adapter,
    sonarr_adapter,
)
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
    if config.sonarr_url and config.sonarr_api_key:
        apps.append(
            sonarr_adapter(config.sonarr_url, config.sonarr_api_key, timeout=config.http_timeout)
        )
    if config.radarr_url and config.radarr_api_key:
        apps.append(
            radarr_adapter(config.radarr_url, config.radarr_api_key, timeout=config.http_timeout)
        )
    clients = []
    if "filesystem" in config.download_clients:
        clients.append(FolderDownloadClient(config.downloads_root, config.manifest))
    if "qbittorrent" in config.download_clients and config.qbittorrent_url:
        clients.append(
            QBittorrentDownloadClient(
                config.qbittorrent_url,
                config.qbittorrent_username or "",
                config.qbittorrent_password or "",
                timeout=config.http_timeout,
            )
        )
    if "sabnzbd" in config.download_clients and config.sabnzbd_url and config.sabnzbd_api_key:
        clients.append(
            SabnzbdDownloadClient(
                config.sabnzbd_url, config.sabnzbd_api_key, timeout=config.http_timeout
            )
        )
    return MediaEngine(
        apps,
        clients,
        AuditLog(config.audit_path),
    )


def main() -> int:
    parser = argparse.ArgumentParser(prog="media-stack", description="Safe media import planning")
    parser.add_argument("command", choices=("plan", "serve", "validate-config"))
    parser.add_argument(
        "--execute", action="store_true", help="execute approved imports; default is dry-run"
    )
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    config = Config.from_env()
    if args.command == "validate-config":
        result = config.validate()
        print(
            json.dumps(
                {
                    "valid": result.valid,
                    "errors": list(result.errors),
                    "warnings": list(result.warnings),
                    "config": result.config,
                },
                indent=2,
            )
        )
        return 0 if result.valid else 2
    validation = config.validate()
    if not validation.valid:
        print(
            json.dumps({"valid": False, "errors": list(validation.errors)}, indent=2),
            file=sys.stderr,
        )
        return 2
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
