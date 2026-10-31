import json

from agentic_media_stack.adapters import (
    HttpMediaApp,
    QBittorrentDownloadClient,
    SabnzbdDownloadClient,
)
from agentic_media_stack.cli import _engine
from agentic_media_stack.config import Config
from agentic_media_stack.models import Download


def test_live_environment_is_selected_and_secrets_are_redacted(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "http://sonarr:8989")
    monkeypatch.setenv("SONARR_API_KEY", "sonarr-secret")
    monkeypatch.setenv("QBITTORRENT_URL", "http://qbittorrent:8080")
    monkeypatch.setenv("QBITTORRENT_USERNAME", "hong")
    monkeypatch.setenv("QBITTORRENT_PASSWORD", "qb-secret")
    config = Config.from_env()
    result = config.validate()
    assert result.valid
    assert config.download_clients == ("qbittorrent",)
    encoded = json.dumps(result.config)
    assert "sonarr-secret" not in encoded
    assert "qb-secret" not in encoded
    assert "[REDACTED]" in encoded


def test_validation_rejects_partial_live_credentials(monkeypatch):
    monkeypatch.setenv("RADARR_URL", "radarr:7878")
    monkeypatch.delenv("RADARR_API_KEY", raising=False)
    result = Config.from_env().validate()
    assert not result.valid
    assert "Radarr URL must be an absolute http(s) URL" in result.errors
    assert "Radarr URL is set but its API key is missing" in result.errors


def test_validation_reports_malformed_numeric_environment(monkeypatch):
    monkeypatch.setenv("MEDIA_HTTP_TIMEOUT", "not-a-number")
    monkeypatch.setenv("MEDIA_RESTART_CAP", "not-a-number")
    result = Config.from_env().validate()
    assert not result.valid
    assert "MEDIA_HTTP_TIMEOUT must be greater than zero" in result.errors
    assert "MEDIA_RESTART_CAP cannot be negative" in result.errors


class FakeQBitTorrent(QBittorrentDownloadClient):
    def _login(self):
        self._cookie = "SID=mock"

    def _request(self, path, **kwargs):
        assert "filter=completed" in path
        return json.dumps(
            [
                {
                    "hash": "abc",
                    "name": "Chi's Sweet Home S01E01.mkv",
                    "content_path": "/downloads/chi/episode.mkv",
                    "size": 12,
                    "completion_on": 1793354400,
                }
            ]
        ).encode()


class FakeSabnzbd(SabnzbdDownloadClient):
    def _request(self, path, **kwargs):
        assert "mode=history" in path
        return json.dumps(
            {
                "history": {
                    "slots": [
                        {
                            "nzo_id": "nzo-1",
                            "name": "Cosmic Princess Kaguya",
                            "storage": "/downloads/kaguya.mkv",
                            "bytes": "42",
                            "status": "Completed",
                        }
                    ]
                }
            }
        ).encode()


def test_download_clients_normalise_completed_items_without_logging_credentials():
    qbit = FakeQBitTorrent("http://qb", "hong", "secret")
    sab = FakeSabnzbd("http://sab", "secret")
    assert qbit.completed_downloads()[0].source == "qbittorrent"
    assert sab.completed_downloads()[0].path == "/downloads/kaguya.mkv"


class FakeSonarr(HttpMediaApp):
    def __init__(self):
        super().__init__("sonarr", "http://sonarr", "secret")
        self.commands = []

    def _request(self, path, *, method="GET", body=None):
        if path == "/api/v3/series":
            return [{"id": 3, "title": "Chi's Sweet Home"}]
        if path == "/api/v3/episode?seriesId=3":
            return [
                {"id": 11, "seasonNumber": 1, "episodeNumber": 4, "hasFile": False},
                {"id": 12, "seasonNumber": 1, "episodeNumber": 5, "hasFile": True},
            ]
        if path.startswith("/api/v3/command"):
            self.commands.append(json.loads(body))
            return {"id": 99}
        if path.startswith("/api/v3/episode?"):
            return [{"hasFile": True, "episodeFile": {"path": "/downloads/chi/04.mkv"}}]
        raise AssertionError(path)


def test_sonarr_discovers_missing_episodes_and_verifies_read_back():
    app = FakeSonarr()
    candidates = app.candidates()
    assert [(item.season, item.episode) for item in candidates] == [(1, 4)]
    download = Download("chi-04", "Chi S01E04.mkv", "/downloads/chi/04.mkv", 1, "now")
    accepted = app.import_file(candidates[0], download)
    assert app.commands == [{"name": "DownloadedEpisodesScan", "path": download.path}]
    verified = app.verify_import(candidates[0], download, accepted)
    assert verified.ok


def test_engine_wires_live_adapters_from_environment(monkeypatch):
    monkeypatch.setenv("SONARR_URL", "http://sonarr:8989")
    monkeypatch.setenv("SONARR_API_KEY", "sonarr-secret")
    monkeypatch.setenv("RADARR_URL", "http://radarr:7878")
    monkeypatch.setenv("RADARR_API_KEY", "radarr-secret")
    monkeypatch.setenv("QBITTORRENT_URL", "http://qbittorrent:8080")
    monkeypatch.setenv("QBITTORRENT_USERNAME", "hong")
    monkeypatch.setenv("QBITTORRENT_PASSWORD", "qb-secret")
    engine = _engine(Config.from_env())
    assert [app.name for app in engine.apps] == ["sonarr", "radarr"]
    assert [client.name for client in engine.clients] == ["qbittorrent"]
