from agentic_media_stack.config import Config
from agentic_media_stack.service import build_service


def test_local_mock_request_download_progress_flow(tmp_path):
    service = build_service(
        Config(
            state_path=str(tmp_path / "state.db"),
            audit_path=str(tmp_path / "audit.jsonl"),
            mock_mode=True,
        )
    )
    try:
        request = service.create_request("movie", "Cosmic Princess Kaguya", 2024)
        service.jobs.futures[request["job_id"]].result(timeout=2)
        candidates = service.candidates(request["id"])
        assert candidates and candidates[0]["title"] == "Cosmic Princess Kaguya"
        download_job = service.select_candidate(request["id"], candidates[0]["id"])["job_id"]
        service.jobs.futures[download_job].result(timeout=2)
        first = service.sync_downloads()
        second = service.sync_downloads()
        assert first[0]["progress"] == 0.5
        assert second[0]["status"] == "completed"
    finally:
        service.jobs.shutdown()
