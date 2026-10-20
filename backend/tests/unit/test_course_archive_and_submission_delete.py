from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import (
    Artifact,
    Assignment,
    ColabSnapshot,
    Enrollment,
    NotebookRun,
    RubricDimensionScore,
    Student,
    StudentComponentOverride,
    Submission,
    SubmissionMember,
)
from app.services import storage
from tests.unit.test_storage import SECRET, FakeSupabaseStorage


@pytest.fixture
def env(tmp_path, monkeypatch, db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def _db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "instructor_token", None)
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, Session=SessionLocal, settings=settings)
    app.dependency_overrides.clear()


def _ok(res, status=200):
    assert res.status_code == status, res.text
    return res.json()


def _course(env, code="AI") -> int:
    return _ok(env.client.post("/api/courses", json={"code": code, "name": "AI Products", "year": 2026, "semester": "A"}))["id"]


def _seed(env, course_id: int) -> SimpleNamespace:
    """An HW1 submission by two students (plus a third enrolled outsider) with
    every kind of dependent row: files, a snapshot, a pinned run, rubric
    scores and a per-submission override."""
    with env.Session() as db:
        students = []
        for nid, name in (("100000001", "Alice"), ("100000002", "Amir"), ("100000003", "Bella")):
            s = Student(national_id=nid, name=name)
            db.add(s)
            db.flush()
            db.add(Enrollment(course_id=course_id, student_id=s.id))
            students.append(s.id)
        assignment = Assignment(course_id=course_id, workcode=1, name="HW1", assignment_type="HW1")
        db.add(assignment)
        db.flush()
        sub = Submission(course_id=course_id, assignment_id=assignment.id, group_identifier="100000001_100000002", manual_grade=90)
        db.add(sub)
        db.flush()
        db.add_all([SubmissionMember(submission_id=sub.id, student_id=sid) for sid in students[:2]])

        def artifact(kind: str, key: str) -> Artifact:
            a = Artifact(submission_id=sub.id, kind=kind, filename=key.rsplit("/", 1)[-1], path=storage.save(key, b"data"))
            db.add(a)
            db.flush()
            return a

        report = artifact("project_report_pdf", f"uploads/{course_id}/{assignment.id}/{sub.id}/report.pdf")
        nb = artifact("snapshot_ipynb", f"snapshots/{sub.id}/snapshot_1.ipynb")
        log = artifact("run_log", f"runs/{sub.id}/run_1.log")
        snap = ColabSnapshot(submission_id=sub.id, url="https://colab.research.google.com/drive/x", status="PUBLIC_FETCHED", artifact_id=nb.id)
        db.add(snap)
        db.flush()
        run = NotebookRun(submission_id=sub.id, snapshot_id=snap.id, status="SUCCESS", log_artifact_id=log.id, is_pinned=True)
        db.add(run)
        db.flush()
        sub.pinned_run_id = run.id
        db.add(RubricDimensionScore(submission_id=sub.id, component="hw2_code", dimension_key="k", raw_score=3, adjusted_score=3))
        db.add(StudentComponentOverride(course_id=course_id, student_id=students[1], submission_id=sub.id, component="hw1", delta=5, reason="late fix"))
        db.commit()
        return SimpleNamespace(
            submission_id=sub.id,
            students=students,
            locations=[report.path, nb.path, log.path],
        )


def _gradebook_hw1(env, course_id: int) -> dict[int, float]:
    rows = _ok(env.client.get(f"/api/courses/{course_id}/gradebook"))["rows"]
    return {r["student_id"]: r["hw1"] for r in rows}


def test_archived_course_is_hidden_and_restorable(env):
    keep = _course(env, "KEEP")
    old = _course(env, "OLD")

    archived = _ok(env.client.post(f"/api/courses/{old}/archive"))
    assert archived["archived_at"] is not None
    assert [c["id"] for c in _ok(env.client.get("/api/courses"))] == [keep]
    everything = _ok(env.client.get("/api/courses", params={"include_archived": "true"}))
    assert {c["id"] for c in everything} == {keep, old}
    # Still reachable directly, nothing deleted.
    assert _ok(env.client.get(f"/api/courses/{old}"))["code"] == "OLD"

    assert _ok(env.client.post(f"/api/courses/{old}/restore"))["archived_at"] is None
    assert {c["id"] for c in _ok(env.client.get("/api/courses"))} == {keep, old}
    assert env.client.post("/api/courses/9999/archive").status_code == 404


def test_delete_submission_removes_rows_and_files(env):
    course_id = _course(env)
    seed = _seed(env, course_id)
    assert all(Path(p).exists() for p in seed.locations)
    assert _gradebook_hw1(env, course_id)[seed.students[0]] == 90

    res = _ok(env.client.delete(f"/api/submissions/{seed.submission_id}"))
    assert res == {"status": "ok", "files_deleted": 3, "files_failed": 0}

    assert not any(Path(p).exists() for p in seed.locations)
    with env.Session() as db:
        for model in (Submission, SubmissionMember, Artifact, ColabSnapshot, NotebookRun, RubricDimensionScore, StudentComponentOverride):
            assert db.scalar(select(func.count()).select_from(model)) == 0, model.__name__
        assert db.scalar(select(func.count()).select_from(Student)) == 3
    assert _gradebook_hw1(env, course_id)[seed.students[0]] == 0
    assert env.client.delete(f"/api/submissions/{seed.submission_id}").status_code == 404


def test_delete_submission_removes_supabase_objects(env, monkeypatch):
    fake = FakeSupabaseStorage()
    monkeypatch.setattr(env.settings, "storage_backend", "supabase")
    monkeypatch.setattr(env.settings, "supabase_project_url", "https://proj.supabase.co")
    monkeypatch.setattr(env.settings, "supabase_secret_key", SECRET)
    monkeypatch.setattr(storage, "_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(storage, "_bucket_ready", set())

    course_id = _course(env)
    seed = _seed(env, course_id)
    assert all(p.startswith("supabase://") for p in seed.locations)
    assert len(fake.objects) == 3

    _ok(env.client.delete(f"/api/submissions/{seed.submission_id}"))
    assert fake.objects == {}


def test_edit_group_members_keeps_gradebook_consistent(env):
    course_id = _course(env)
    seed = _seed(env, course_id)
    alice, amir, bella = seed.students
    assert _gradebook_hw1(env, course_id) == {alice: 90, amir: 95, bella: 0}

    # Amir was grouped by mistake; Bella belongs here instead.
    read = _ok(env.client.put(f"/api/submissions/{seed.submission_id}/members", json={"student_ids": [alice, bella]}))
    assert sorted(read["member_student_ids"]) == [alice, bella]
    assert _gradebook_hw1(env, course_id) == {alice: 90, amir: 0, bella: 90}
    with env.Session() as db:
        # Amir's override was about this submission, so it goes with him.
        assert db.scalar(select(func.count()).select_from(StudentComponentOverride)) == 0


def test_edit_group_members_validation(env):
    course_id = _course(env)
    seed = _seed(env, course_id)
    url = f"/api/submissions/{seed.submission_id}/members"

    assert env.client.put(url, json={"student_ids": []}).status_code == 422
    with env.Session() as db:
        outsider = Student(national_id="999999999", name="Not Enrolled")
        db.add(outsider)
        db.commit()
        outsider_id = outsider.id
    assert env.client.put(url, json={"student_ids": [seed.students[0], outsider_id]}).status_code == 400
    assert env.client.put("/api/submissions/9999/members", json={"student_ids": [seed.students[0]]}).status_code == 404
    with env.Session() as db:
        members = db.scalars(select(SubmissionMember.student_id).where(SubmissionMember.submission_id == seed.submission_id)).all()
    assert sorted(members) == sorted(seed.students[:2])
