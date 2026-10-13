"""Database-backed job queue (replaces Celery + Redis).

The API enqueues by inserting a `jobs` row; the worker on the instructor's
machine (`python -m app.tasks.worker`) claims rows with an atomic
queued -> running update, so it works the same on SQLite and on Supabase
Postgres, and needs no broker reachable from the hosted API.
"""

from __future__ import annotations

import json
import socket
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.entities import Job

MAX_ATTEMPTS = 3

TASKS: dict[str, Callable[..., Any]] = {}


def job(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a function as a queueable job. It stays directly callable."""

    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        fn.job_name = name  # type: ignore[attr-defined]
        TASKS[name] = fn
        return fn

    return register


def enqueue(db: Session, task: Callable[..., Any], *args: Any) -> str:
    """Queue `task(*args)`. Commits, so the worker can see the job (and any
    rows the caller created for it) immediately. Returns the job id."""
    name = getattr(task, "job_name", None)
    if name is None:
        raise ValueError(f"{task!r} is not registered with @job")
    row = Job(name=name, args_json=json.dumps(list(args)))
    db.add(row)
    db.commit()
    return str(row.id)


def worker_id() -> str:
    return socket.gethostname()[:128]


def claim_next(db: Session, worker: str) -> Job | None:
    """Claim the oldest queued job. The conditional UPDATE makes the claim
    atomic: if another worker got there first, try the next one."""
    for _ in range(10):
        candidate = db.scalar(select(Job.id).where(Job.status == "queued").order_by(Job.id).limit(1))
        if candidate is None:
            return None
        claimed = db.execute(
            update(Job)
            .where(Job.id == candidate, Job.status == "queued")
            .values(status="running", started_at=datetime.utcnow(), worker=worker, attempts=Job.attempts + 1)
        )
        db.commit()
        if claimed.rowcount == 1:
            return db.get(Job, candidate)
    return None


def run_job(db: Session, row: Job) -> None:
    fn = TASKS.get(row.name)
    try:
        if fn is None:
            raise LookupError(f"No job registered as {row.name!r}")
        result = fn(*json.loads(row.args_json or "[]"))
        row.status = "succeeded"
        row.result_json = json.dumps(result, default=str)
    except Exception:  # noqa: BLE001  (record any failure on the job row)
        db.rollback()
        row = db.get(Job, row.id)
        row.status = "failed"
        row.error = traceback.format_exc()[-8000:]
    row.finished_at = datetime.utcnow()
    db.commit()


def requeue_stale(db: Session, older_than: timedelta) -> int:
    """Jobs left 'running' by a worker that died: retry, or fail after
    MAX_ATTEMPTS."""
    cutoff = datetime.utcnow() - older_than
    stale = db.scalars(select(Job).where(Job.status == "running", Job.started_at < cutoff)).all()
    for row in stale:
        if row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
            row.error = "Worker stopped while running this job (retries exhausted)"
            row.finished_at = datetime.utcnow()
        else:
            row.status = "queued"
    db.commit()
    return len(stale)
