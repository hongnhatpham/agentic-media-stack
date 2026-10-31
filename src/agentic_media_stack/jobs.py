from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from .state import StateStore


class JobManager:
    def __init__(self, state: StateStore, workers: int = 4):
        self.state = state
        self.executor = ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="media-job"
        )
        self.futures: dict[str, Future[Any]] = {}

    def submit(
        self, kind: str, fn: Callable[[str], Any], payload: dict[str, Any] | None = None
    ) -> str:
        job_id = self.state.create_job(kind, payload)
        self.futures[job_id] = self.executor.submit(self._run, job_id, fn)
        return job_id

    def _run(self, job_id: str, fn: Callable[[str], Any]) -> Any:
        self.state.update_job(job_id, status="running", progress=0.05, message="started")
        try:
            result = fn(job_id)
            self.state.update_job(job_id, status="completed", progress=1.0, message="completed")
            return result
        except Exception as exc:
            self.state.update_job(job_id, status="failed", error=str(exc), message="failed")
            self.state.record_audit(
                "job_failed", "background job failed", {"job_id": job_id, "error": str(exc)}
            )
            return None

    def shutdown(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=False)
