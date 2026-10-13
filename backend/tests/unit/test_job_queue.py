from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Course, Job
from app.tasks import queue


@queue.job("tests.add")
def _add(a: int, b: int) -> dict:
    return {"sum": a + b}


@queue.job("tests.boom")
def _boom() -> None:
    raise RuntimeError("kaboom")


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False)


def test_enqueue_claim_and_run(session_factory):
    with session_factory() as db:
        job_id = int(queue.enqueue(db, _add, 2, 3))
        row = queue.claim_next(db, "worker-a")
        assert row.id == job_id and row.status == "running" and row.attempts == 1 and row.worker == "worker-a"
        queue.run_job(db, row)
    with session_factory() as db:
        row = db.get(Job, job_id)
        assert row.status == "succeeded"
        assert json.loads(row.result_json) == {"sum": 5}
        assert row.finished_at is not None
        assert queue.claim_next(db, "worker-a") is None


def test_failures_are_recorded_and_the_worker_session_survives(session_factory):
    with session_factory() as db:
        failing = int(queue.enqueue(db, _boom))
        ok = int(queue.enqueue(db, _add, 1, 1))
        queue.run_job(db, queue.claim_next(db, "w"))
        queue.run_job(db, queue.claim_next(db, "w"))
    with session_factory() as db:
        failed = db.get(Job, failing)
        assert failed.status == "failed" and "RuntimeError: kaboom" in failed.error
        assert db.get(Job, ok).status == "succeeded"


def test_unregistered_task_is_rejected(session_factory):
    with session_factory() as db, pytest.raises(ValueError):
        queue.enqueue(db, lambda: None)


def test_concurrent_workers_claim_each_job_exactly_once(session_factory):
    with session_factory() as db:
        ids = [int(queue.enqueue(db, _add, i, i)) for i in range(20)]

    claimed: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()
    start = threading.Barrier(4)

    def worker(name: str) -> None:
        try:
            start.wait()
            with session_factory() as db:
                while (row := queue.claim_next(db, name)) is not None:
                    with lock:
                        claimed.append(row.id)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert sorted(claimed) == ids  # every job once, none twice


def test_stale_running_jobs_are_retried_then_failed(session_factory):
    with session_factory() as db:
        retry = int(queue.enqueue(db, _add, 1, 2))
        give_up = int(queue.enqueue(db, _add, 3, 4))
        long_ago = datetime.utcnow() - timedelta(hours=2)
        db.get(Job, retry).status, db.get(Job, retry).started_at, db.get(Job, retry).attempts = "running", long_ago, 1
        row = db.get(Job, give_up)
        row.status, row.started_at, row.attempts = "running", long_ago, queue.MAX_ATTEMPTS
        db.commit()
        assert queue.requeue_stale(db, timedelta(minutes=60)) == 2
    with session_factory() as db:
        assert db.get(Job, retry).status == "queued"
        assert db.get(Job, give_up).status == "failed"


def test_api_enqueues_and_reports_job_status(session_factory, monkeypatch, tmp_path):
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "instructor_token", None)

    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    try:
        with session_factory() as db:
            course = Course(code="AI", name="AI", year=2026, semester="A")
            db.add(course)
            db.commit()
            course_id = course.id
        with TestClient(app) as client:
            res = client.post(f"/api/courses/{course_id}/exports/student-reports")
            assert res.status_code == 200 and res.json()["status"] == "queued"
            task_id = res.json()["task_id"]
            assert client.get(f"/api/tasks/{task_id}").json()["state"] == "PENDING"

            with session_factory() as db:
                row = db.scalar(select(Job).where(Job.id == int(task_id)))
                assert row.name == "app.tasks.jobs.export_student_reports"
                assert json.loads(row.args_json) == [course_id]
                row.status, row.result_json = "succeeded", json.dumps({"status": "ok", "report_count": 0})
                db.commit()
            body = client.get(f"/api/tasks/{task_id}").json()
            assert body["state"] == "SUCCESS" and body["payload"]["report_count"] == 0
            assert client.get("/api/tasks/999999").status_code == 404
    finally:
        app.dependency_overrides.clear()
