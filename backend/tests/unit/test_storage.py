from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Artifact, ColabSnapshot, Course, Submission
from app.services import llm_peer_review, snapshot_service, storage
from app.services.zip_ingest import ingest_submission_zip
from app.tasks import jobs

SECRET = "sb_secret_test"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


class FakeSupabaseStorage:
    """The slice of the Supabase Storage HTTP API that app.services.storage uses."""

    def __init__(self) -> None:
        self.buckets: dict[str, bool] = {}
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        assert request.headers["apikey"] == SECRET
        assert request.headers["authorization"] == f"Bearer {SECRET}"
        path = request.url.path.removeprefix("/storage/v1")
        if m := re.fullmatch(r"/bucket/([^/]+)", path):
            if request.method == "GET":
                return httpx.Response(200 if m[1] in self.buckets else 400, json={})
        if path == "/bucket" and request.method == "POST":
            body = json.loads(request.content)
            self.buckets[body["id"]] = body["public"]
            return httpx.Response(200, json={"name": body["id"]})
        if m := re.fullmatch(r"/object/upload/sign/([^/]+)/(.+)", path):
            return httpx.Response(200, json={"url": f"/object/upload/sign/{m[1]}/{m[2]}?token=up"})
        if (m := re.fullmatch(r"/object/([^/]+)", path)) and request.method == "DELETE":
            for key in json.loads(request.content)["prefixes"]:
                self.objects.pop((m[1], key), None)
            return httpx.Response(200, json=[])
        if m := re.fullmatch(r"/object/sign/([^/]+)/(.+)", path):
            return httpx.Response(200, json={"signedURL": f"/object/sign/{m[1]}/{m[2]}?token=t0k"})
        if m := re.fullmatch(r"/object/info/authenticated/([^/]+)/(.+)", path):
            return httpx.Response(200 if (m[1], m[2]) in self.objects else 400, json={})
        if m := re.fullmatch(r"/object/authenticated/([^/]+)/(.+)", path):
            obj = self.objects.get((m[1], m[2]))
            return httpx.Response(200, content=obj[0]) if obj else httpx.Response(400, json={"error": "not_found"})
        if (m := re.fullmatch(r"/object/([^/]+)/(.+)", path)) and request.method == "POST":
            if m[1] not in self.buckets:
                return httpx.Response(400, json={"error": "Bucket not found"})
            if (m[1], m[2]) in self.objects and request.headers.get("x-upsert") != "true":
                return httpx.Response(400, json={"error": "Duplicate"})
            self.objects[(m[1], m[2])] = (request.content, request.headers["content-type"])
            return httpx.Response(200, json={"Key": f"{m[1]}/{m[2]}"})
        return httpx.Response(404, json={"error": f"unexpected {request.method} {path}"})


@pytest.fixture
def fake_storage(monkeypatch, tmp_path):
    fake = FakeSupabaseStorage()
    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "supabase")
    monkeypatch.setattr(settings, "supabase_project_url", "https://proj.supabase.co")
    monkeypatch.setattr(settings, "supabase_secret_key", SECRET)
    monkeypatch.setattr(settings, "instructor_token", None)
    monkeypatch.setattr(storage, "_transport", httpx.MockTransport(fake))
    monkeypatch.setattr(storage, "_bucket_ready", set())
    return fake


@pytest.fixture
def session_factory(db_engine):
    return sessionmaker(bind=db_engine, autoflush=False)


def test_supabase_backend_round_trip(fake_storage, tmp_path):
    location = storage.save("runs/7/out.log", b"hello", "text/plain")
    assert location == "supabase://course-grader/runs/7/out.log"
    assert fake_storage.buckets == {"course-grader": False}  # created private
    assert fake_storage.objects[("course-grader", "runs/7/out.log")] == (b"hello", "text/plain")

    assert storage.read_bytes(location) == b"hello"
    assert storage.exists(location) and not storage.exists("supabase://course-grader/nope.txt")
    local = storage.local_path(location)
    assert local == tmp_path / "cache" / "course-grader" / "runs" / "7" / "out.log"
    assert local.read_bytes() == b"hello"

    storage.save("runs/7/out.log", b"updated", "text/plain")  # overwrite
    assert storage.local_path(location).read_bytes() == b"updated"

    assert storage.signed_url(location) == "https://proj.supabase.co/storage/v1/object/sign/course-grader/runs/7/out.log?token=t0k"
    assert storage.signed_url(location, download_name="out.log").endswith("?token=t0k&download=out.log")


def test_local_backend_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "data_dir", str(tmp_path))
    location = storage.save("runs/1/a.txt", b"x")
    assert location == str(tmp_path / "artifacts" / "runs" / "1" / "a.txt")
    assert storage.read_bytes(location) == b"x"
    assert storage.local_path(location) == Path(location)
    assert not storage.is_remote(location)


def test_zip_ingest_and_worker_outputs_go_to_supabase(fake_storage, session_factory, tmp_path):
    with session_factory() as db:
        course = Course(code="AI101", name="Applied AI", year=2026, semester="A")
        db.add(course)
        db.commit()
        ingest_submission_zip(
            db=db,
            course_id=course.id,
            assignment_type="HW2",
            zip_path=str(FIXTURES / "sample_submissions.zip"),
            fallback_workcode=2,
            assignment_name="HW2",
        )
        artifacts = db.scalars(select(Artifact)).all()
        assert artifacts and all(a.path.startswith("supabase://course-grader/uploads/") for a in artifacts)
        assert all(storage.read_bytes(a.path) for a in artifacts)

        submission = db.scalar(select(Submission))
        run_artifact = jobs._create_artifact(db, submission.id, "run_logs", "run_1.log", b"log text", "text/plain")
        assert run_artifact.path == f"supabase://course-grader/runs/{submission.id}/run_1.log"

        snap = ColabSnapshot(submission_id=submission.id, url="https://colab.research.google.com/drive/x")
        db.add(snap)
        db.flush()
        location, _ = snapshot_service.persist_snapshot_file(snap, b'{"cells": []}')
        assert location.startswith(f"supabase://course-grader/snapshots/{submission.id}/snapshot_")

        # The worker stages remote data files next to the notebook it runs.
        db.add(Artifact(submission_id=submission.id, kind="data_file", filename="ID_1_data.csv",
                        path=storage.save(f"uploads/x/{submission.id}/data.csv", b"a,b\n1,2\n", "text/csv")))
        db.commit()
        workdir = tmp_path / "work"
        jobs._stage_data_files(db, submission.id, workdir)
        assert (workdir / "data.csv").read_bytes() == b"a,b\n1,2\n"


def test_artifact_downloads_redirect_to_signed_urls(fake_storage, session_factory):
    with session_factory() as db:
        pdf = Artifact(kind="presentation_slides", filename="slides.pdf", mime_type="application/pdf",
                       path=storage.save("peer/rounds/1/p.pdf", b"%PDF-1.4", "application/pdf"), size_bytes=8)
        html = Artifact(kind="executed_html", filename="nb.html", mime_type="text/html",
                        path=storage.save("runs/1/nb.html", b"<p>hi</p>", "text/html"), size_bytes=9)
        db.add_all([pdf, html])
        db.commit()
        pdf_id, html_id = pdf.id, html.id

    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    try:
        with TestClient(app, follow_redirects=False) as client:
            inline = client.get(f"/api/artifacts/{pdf_id}?inline=1")
            assert inline.status_code == 307
            assert inline.headers["location"].endswith("/object/sign/course-grader/peer/rounds/1/p.pdf?token=t0k")
            attachment = client.get(f"/api/artifacts/{pdf_id}")
            assert attachment.headers["location"].endswith("&download=slides.pdf")
            raw = client.get(f"/api/artifacts/{html_id}/raw")
            assert raw.status_code == 200 and raw.text == "<p>hi</p>"
    finally:
        app.dependency_overrides.clear()


def test_ai_grader_reads_slides_from_supabase(fake_storage, session_factory):
    with session_factory() as db:
        slides = Artifact(kind="presentation_slides", filename="s.pdf", mime_type="application/pdf",
                          path=storage.save("peer/rounds/1/presentation_5_slides.pdf", b"%PDF-1.7 deck", "application/pdf"),
                          size_bytes=13)
        db.add(slides)
        db.flush()
        presentation = SimpleNamespace(id=5, team_id=-1, demo_url="", materials_text="", slides_artifact_id=slides.id)
        [materials] = llm_peer_review._load_materials(db, [presentation])  # type: ignore[list-item]
        assert materials.slides_pdf == b"%PDF-1.7 deck"


def _client_with(session_factory):
    def _db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_large_files_upload_straight_to_storage(fake_storage, session_factory, tmp_path):
    """Hosted request bodies are capped, so the browser PUTs files to a signed
    URL and the API registers them by key."""
    try:
        with _client_with(session_factory) as c:
            cid = c.post("/api/courses", json={"code": "AI", "name": "AI", "year": 2026, "semester": "A"}).json()["id"]
            with session_factory() as db:
                from app.models.entities import Enrollment, Student

                s = Student(national_id="111111118", name="Noa")
                db.add(s)
                db.flush()
                db.add(Enrollment(course_id=cid, student_id=s.id))
                db.commit()
                sid = s.id
            team = c.post(f"/api/courses/{cid}/peer/teams", json={"name": "T1"}).json()["id"]
            c.put(f"/api/courses/{cid}/peer/students/{sid}/team", json={"team_id": team})
            c.post(f"/api/courses/{cid}/peer/setup")
            c.post(f"/api/courses/{cid}/peer/links/generate")
            token = c.get(f"/api/courses/{cid}/peer/links").json()[0]["token"]
            pres = c.get(f"/api/courses/{cid}/peer/overview").json()["rounds"][0]["presentations"][0]["id"]

            # Slides: signed URL, browser upload (simulated), then register.
            target = c.post(f"/api/r/{token}/presentations/{pres}/slides/upload-url").json()
            assert target["direct"] and target["url"].endswith("?token=up")
            assert target["key"].startswith("peer/rounds/") and target["key"].endswith(f"presentation_{pres}_slides.pdf")
            fake_storage.objects[("course-grader", target["key"])] = (b"%PDF-1.7 big deck", "application/pdf")
            done = c.post(f"/api/r/{token}/presentations/{pres}/slides/complete", json={"key": target["key"], "filename": "deck.pdf"})
            assert done.status_code == 200
            overview = c.get(f"/api/courses/{cid}/peer/overview").json()["rounds"][0]["presentations"]
            assert next(p for p in overview if p["id"] == pres)["has_slides"]
            bad = c.post(f"/api/r/{token}/presentations/{pres}/slides/complete", json={"key": "peer/rounds/9/other.pdf"})
            assert bad.status_code == 400
            fake_storage.objects[("course-grader", target["key"])] = (b"not a pdf", "application/pdf")
            assert c.post(f"/api/r/{token}/presentations/{pres}/slides/complete", json={"key": target["key"]}).status_code == 400

            # Imports: same idea, by storage_key; the upload is removed after import.
            from openpyxl import Workbook

            wb = Workbook()
            wb.active.append(["תעודת זהות", "שם"])
            wb.active.append(["222222226", "Itay"])
            xlsx = tmp_path / "roster.xlsx"
            wb.save(xlsx)
            target = c.post(f"/api/courses/{cid}/imports/upload-url", json={"filename": "roster.xlsx"}).json()
            assert target["key"].startswith(f"imports/{cid}/")
            fake_storage.objects[("course-grader", target["key"])] = (xlsx.read_bytes(), "application/octet-stream")
            res = c.post(f"/api/courses/{cid}/imports/roster", data={"storage_key": target["key"]})
            assert res.status_code == 200 and res.json()["imported"] == 1
            assert ("course-grader", target["key"]) not in fake_storage.objects
            other = c.post(f"/api/courses/{cid}/imports/roster", data={"storage_key": "imports/999/x/roster.xlsx"})
            assert other.status_code == 400
    finally:
        app.dependency_overrides.clear()
