from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class ConfigValidation:
    valid: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    config: dict[str, object]


@dataclass(frozen=True)
class Config:
    downloads_root: str = "/downloads"
    manifest: str | None = None
    candidate_manifest: str | None = None
    audit_path: str = "/config/audit.jsonl"
    dry_run: bool = True
    restart_cap: int = 2
    http_timeout: float = 10.0
    download_clients: tuple[str, ...] = ("filesystem",)
    sonarr_url: str | None = None
    sonarr_api_key: str | None = None
    radarr_url: str | None = None
    radarr_api_key: str | None = None
    qbittorrent_url: str | None = None
    qbittorrent_username: str | None = None
    qbittorrent_password: str | None = None
    sabnzbd_url: str | None = None
    sabnzbd_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "Config":
        sonarr_url = os.getenv("SONARR_URL")
        radarr_url = os.getenv("RADARR_URL")
        qbittorrent_url = os.getenv("QBITTORRENT_URL")
        sabnzbd_url = os.getenv("SABNZBD_URL")
        configured_clients = os.getenv("MEDIA_DOWNLOAD_CLIENTS")
        if configured_clients is None:
            default_clients = [
                name
                for name, url in (
                    ("qbittorrent", qbittorrent_url),
                    ("sabnzbd", sabnzbd_url),
                )
                if url
            ] or ["filesystem"]
        else:
            default_clients = [item.strip().casefold() for item in configured_clients.split(",")]
        return cls(
            downloads_root=os.getenv("MEDIA_DOWNLOADS_ROOT", "/downloads"),
            manifest=os.getenv("MEDIA_DOWNLOAD_MANIFEST"),
            candidate_manifest=os.getenv("MEDIA_CANDIDATE_MANIFEST"),
            audit_path=os.getenv("MEDIA_AUDIT_PATH", "/config/audit.jsonl"),
            dry_run=os.getenv("MEDIA_DRY_RUN", "true").casefold() not in {"0", "false", "no"},
            restart_cap=cls._int_env("MEDIA_RESTART_CAP", 2, invalid=-1),
            http_timeout=cls._float_env("MEDIA_HTTP_TIMEOUT", 10.0, invalid=0.0),
            download_clients=tuple(item for item in default_clients if item),
            sonarr_url=sonarr_url,
            sonarr_api_key=os.getenv("SONARR_API_KEY"),
            radarr_url=radarr_url,
            radarr_api_key=os.getenv("RADARR_API_KEY"),
            qbittorrent_url=qbittorrent_url,
            qbittorrent_username=os.getenv("QBITTORRENT_USERNAME"),
            qbittorrent_password=os.getenv("QBITTORRENT_PASSWORD"),
            sabnzbd_url=sabnzbd_url,
            sabnzbd_api_key=os.getenv("SABNZBD_API_KEY"),
        )

    def public_dict(self) -> dict[str, object]:
        return {
            "downloads_root": self.downloads_root,
            "manifest": self.manifest,
            "candidate_manifest": self.candidate_manifest,
            "audit_path": self.audit_path,
            "dry_run": self.dry_run,
            "restart_cap": self.restart_cap,
            "http_timeout": self.http_timeout,
            "download_clients": list(self.download_clients),
            "sonarr_url": self.sonarr_url,
            "sonarr_api_key": "[REDACTED]" if self.sonarr_api_key else None,
            "radarr_url": self.radarr_url,
            "radarr_api_key": "[REDACTED]" if self.radarr_api_key else None,
            "qbittorrent_url": self.qbittorrent_url,
            "qbittorrent_username": self.qbittorrent_username,
            "qbittorrent_password": "[REDACTED]" if self.qbittorrent_password else None,
            "sabnzbd_url": self.sabnzbd_url,
            "sabnzbd_api_key": "[REDACTED]" if self.sabnzbd_api_key else None,
        }

    def validate(self) -> ConfigValidation:
        errors: list[str] = []
        warnings: list[str] = []

        if self.http_timeout <= 0:
            errors.append("MEDIA_HTTP_TIMEOUT must be greater than zero")
        if self.restart_cap < 0:
            errors.append("MEDIA_RESTART_CAP cannot be negative")
        if self.manifest and not Path(self.manifest).is_file():
            errors.append(f"MEDIA_DOWNLOAD_MANIFEST does not exist: {self.manifest}")
        if self.candidate_manifest and not Path(self.candidate_manifest).is_file():
            errors.append(f"MEDIA_CANDIDATE_MANIFEST does not exist: {self.candidate_manifest}")

        for name, url, api_key in (
            ("Sonarr", self.sonarr_url, self.sonarr_api_key),
            ("Radarr", self.radarr_url, self.radarr_api_key),
        ):
            self._validate_url(name, url, errors)
            if url and not api_key:
                errors.append(f"{name} URL is set but its API key is missing")
            if api_key and not url:
                errors.append(f"{name} API key is set but its URL is missing")

        self._validate_url("qBittorrent", self.qbittorrent_url, errors)
        if self.qbittorrent_url and (
            not self.qbittorrent_username or not self.qbittorrent_password
        ):
            errors.append("QBITTORRENT_URL requires QBITTORRENT_USERNAME and QBITTORRENT_PASSWORD")
        self._validate_url("SABnzbd", self.sabnzbd_url, errors)
        if self.sabnzbd_url and not self.sabnzbd_api_key:
            errors.append("SABNZBD_URL requires SABNZBD_API_KEY")

        supported_clients = {"filesystem", "qbittorrent", "sabnzbd"}
        unknown_clients = sorted(set(self.download_clients) - supported_clients)
        if unknown_clients:
            errors.append(
                f"MEDIA_DOWNLOAD_CLIENTS contains unsupported values: {', '.join(unknown_clients)}"
            )
        if not self.download_clients:
            errors.append("MEDIA_DOWNLOAD_CLIENTS must enable at least one client")
        if "qbittorrent" in self.download_clients and not self.qbittorrent_url:
            errors.append("qBittorrent is enabled but QBITTORRENT_URL is missing")
        if "sabnzbd" in self.download_clients and not self.sabnzbd_url:
            errors.append("SABnzbd is enabled but SABNZBD_URL is missing")
        if not self.candidate_manifest and not (self.sonarr_url or self.radarr_url):
            warnings.append(
                "no Sonarr, Radarr, or candidate manifest is configured; plans will be empty"
            )
        if self.dry_run is False:
            warnings.append("MEDIA_DRY_RUN=false permits explicit --execute imports")
        return ConfigValidation(not errors, tuple(errors), tuple(warnings), self.public_dict())

    @staticmethod
    def _validate_url(name: str, value: str | None, errors: list[str]) -> None:
        if not value:
            return
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            errors.append(f"{name} URL must be an absolute http(s) URL")

    @staticmethod
    def _int_env(name: str, default: int, *, invalid: int) -> int:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return int(value)
        except ValueError:
            return invalid

    @staticmethod
    def _float_env(name: str, default: float, *, invalid: float) -> float:
        value = os.getenv(name)
        if value is None:
            return default
        try:
            return float(value)
        except ValueError:
            return invalid
