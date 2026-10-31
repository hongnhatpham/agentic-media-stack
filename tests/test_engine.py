from pathlib import Path

from agentic_media_stack.adapters import FolderDownloadClient, InMemoryMediaApp, JsonMediaApp
from agentic_media_stack.audit import AuditLog
from agentic_media_stack.engine import MediaEngine
from agentic_media_stack.models import MediaCandidate, MediaKind, PlanAction

FIXTURES = Path(__file__).parent / "fixtures" / "downloads.json"


def make_engine() -> tuple[MediaEngine, InMemoryMediaApp, InMemoryMediaApp]:
    shows = InMemoryMediaApp(
        "sonarr",
        [
            MediaCandidate(
                "sonarr", MediaKind.SERIES, "chi-1", "Chi's Sweet Home", season=1, episode=1
            ),
            MediaCandidate(
                "sonarr", MediaKind.SERIES, "chi-2", "Chi's Sweet Home", season=2, episode=1
            ),
            MediaCandidate(
                "sonarr",
                MediaKind.SERIES,
                "big-girls-4",
                "Do You Like Big Girls",
                season=1,
                episode=4,
            ),
            MediaCandidate(
                "sonarr",
                MediaKind.SERIES,
                "big-girls-5",
                "Do You Like Big Girls",
                season=1,
                episode=5,
            ),
        ],
    )
    movies = InMemoryMediaApp(
        "radarr",
        [MediaCandidate("radarr", MediaKind.MOVIE, "kaguya", "Cosmic Princess Kaguya", year=2024)],
    )
    client = FolderDownloadClient("/unused", str(FIXTURES))
    return MediaEngine([shows, movies], [client], AuditLog()), shows, movies


def test_known_fixture_cases_are_clear_and_provenanced():
    engine, _, _ = make_engine()
    graph = engine.build_graph()
    assert len(graph.downloads) == 5 and len(graph.candidates) == 5
    plan = engine.plan()
    assert len(plan) == 5
    assert all(item.action is PlanAction.IMPORT for item in plan)
    assert {item.match.download.id for item in plan} == {
        "chis-s01",
        "chis-s02",
        "kaguya",
        "big-girls-04",
        "big-girls-05",
    }
    assert all(item.match.provenance.source in {"sonarr", "radarr"} for item in plan)


def test_dry_run_does_not_write_or_delete():
    engine, sonarr, radarr = make_engine()
    result = engine.execute_plan(engine.plan(), dry_run=True)
    assert all(item.ok for item in result)
    assert sonarr.imported == []
    assert radarr.imported == []


def test_execute_records_rollback_without_blocklisting():
    engine, sonarr, _ = make_engine()
    item = next(item for item in engine.plan() if item.match.download.id == "chis-s01")
    result = engine.execute(item, dry_run=False)
    assert result.ok and result.rollback == {
        "app": "sonarr",
        "media_id": "chi-1",
        "path": "/downloads/chi/season1/episode01.mkv",
    }
    assert sonarr.imported == [("chi-1", "/downloads/chi/season1/episode01.mkv")]
    assert all("blocklist" not in event.message.casefold() for event in engine.audit.events)
    assert engine.rollback(result) is True
    assert sonarr.imported == []


def test_audit_redacts_secrets():
    audit = AuditLog()
    event = audit.record("config", "loaded", api_key="secret-value", nested={"password": "pw"})
    assert event.data == {"api_key": "[REDACTED]", "nested": {"password": "[REDACTED]"}}


def test_grouped_manifest_adapters_can_execute():
    apps = JsonMediaApp.from_manifest_grouped(
        str(Path(__file__).parent / "fixtures" / "candidates.json")
    )
    engine = MediaEngine(apps, [FolderDownloadClient("/unused", str(FIXTURES))])
    item = next(item for item in engine.plan() if item.match.download.id == "kaguya")
    result = engine.execute(item, dry_run=False)
    assert result.ok


def test_folder_discovery_reaches_nested_unraid_paths(tmp_path):
    nested = tmp_path / "season" / "episode.mkv"
    nested.parent.mkdir()
    nested.write_bytes(b"media")
    downloads = FolderDownloadClient(str(tmp_path)).completed_downloads()
    assert [download.path for download in downloads] == [str(nested)]
