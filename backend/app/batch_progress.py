"""Tracks currently running background batch jobs, one per source.

Used by both /api/jobs/fetch and /api/evaluate — same shape (a sequential,
paced loop over job ids, one failure never aborting the batch), same need for
a frontend to poll live "N of M" progress. Scoped by source rather than
global: two LinkedIn fetches must never run at once (that's the whole reason
this exists — two threads hammering the same undocumented endpoint is how a
few hundred parallel requests turns into a few dozen "concurrent enough"
ones), but a Greenhouse batch and a Lever batch are different hosts and have
always been allowed to run side by side. Fetch and evaluate each get their own
instance, so a running fetch never blocks a concurrent evaluate.

Single-user, single-process app: an in-memory, lock-guarded dict beats a
database table for state nobody needs to keep past a page reload.
"""

from __future__ import annotations

import threading


class BatchProgress:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_source: dict[str, dict] = {}

    def is_running(self, source: str) -> bool:
        with self._lock:
            run = self._by_source.get(source)
            return bool(run and run["running"])

    def start(self, source: str, total: int) -> None:
        with self._lock:
            self._by_source[source] = {
                "running": True,
                "total": total,
                "done_ids": [],
                "report": None,
                "error": None,
            }

    def mark_done(self, source: str, job_id: str) -> None:
        with self._lock:
            run = self._by_source.get(source)
            if run is not None:
                run["done_ids"].append(job_id)

    def finish(self, source: str, report: dict) -> None:
        with self._lock:
            run = self._by_source.get(source)
            if run is not None:
                run["running"] = False
                run["report"] = report

    def fail(self, source: str, error: str) -> None:
        with self._lock:
            run = self._by_source.get(source)
            if run is not None:
                run["running"] = False
                run["error"] = error

    def snapshot(self, source: str) -> dict:
        with self._lock:
            run = self._by_source.get(source)
            if run is None:
                return {"running": False, "total": 0, "done_ids": [], "report": None, "error": None}
            return {**run, "done_ids": list(run["done_ids"])}


fetch_progress = BatchProgress()
evaluate_progress = BatchProgress()
# Bullet Bank tag suggestions; one run at a time, keyed "bullets".
tagger_progress = BatchProgress()
