"""The Feedback button's tickets (app/services/feedback.py, app/api/feedback.py):
filed by a student or the instructor from any page, kept in org-core's
tickets-core shape, and read and annotated by org-core's roles through
/api/admin/feedback with the service token."""

from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Enrollment, FeedbackTicket, Student
from app.services import feedback as svc
from app.services import student_session

STUDENT = {"X-CG-Student": "1"}
TOKEN_A = "tok-a-" + "a" * 26
TOKEN_B = "tok-b-" + "b" * 26


def _ok(res, status=200):
    assert res.status_code == status, res.text
    return res.json()


@pytest.fixture
def env(tmp_path, monkeypatch, db_engine):
    Session = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    settings = get_settings()
    monkeypatch.setattr(settings, "data_dir", str(tmp_path))
    monkeypatch.setattr(settings, "instructor_token", None)
    monkeypatch.setattr(settings, "org_tickets_token", None)
    monkeypatch.setattr(settings, "session_secret", "test-session-secret")
    for name in ("VERCEL_GIT_COMMIT_SHA", "VERCEL_DEPLOYMENT_ID", "VERCEL_URL", "VERCEL_ENV"):
        monkeypatch.delenv(name, raising=False)
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        course_id = _ok(client.post("/api/courses", json={"code": "AI", "name": "AI Products", "year": 2026, "semester": "A"}))["id"]
        with Session() as db:
            ids = {}
            for key, token, nid, name in (("a", TOKEN_A, "900000101", "Noa Test"), ("b", TOKEN_B, "900000102", "Ido Test")):
                s = Student(national_id=nid, name=name)
                db.add(s)
                db.flush()
                e = Enrollment(course_id=course_id, student_id=s.id, review_token=token)
                db.add(e)
                db.flush()
                ids[key] = SimpleNamespace(student_id=s.id, enrollment_id=e.id, token=token)
            db.commit()
        yield SimpleNamespace(client=client, Session=Session, settings=settings, course_id=course_id, students=ids)
    app.dependency_overrides.clear()


def _ticket(env, ticket_id: str) -> FeedbackTicket:
    with env.Session() as db:
        return db.get(FeedbackTicket, ticket_id)


def _student_post(env, who="a", **body):
    payload = {"category": "broken", "text": "The next-step button does nothing", **body}
    return env.client.post(f"/api/r/{env.students[who].token}/feedback", json=payload, headers=STUDENT)


def test_a_student_files_a_named_ticket_with_the_page_it_came_from(env):
    a = env.students["a"]
    context = {
        "path": f"/r/{a.token}/lessons/lesson-02",
        "title": "Lesson 2",
        "lesson": "lesson-02",
        "step": "s3",
        "viewport": "390x844",
        "browser": "Mozilla/5.0 (iPhone)",
        "language": "he-IL",
    }
    filed = _ok(_student_post(env, context=context))
    row = svc.ticket_row(_ticket(env, filed["id"]))

    assert row["source"] == "student"
    assert row["reporter_ref"] == f"enrollment:{a.enrollment_id}"
    assert row["course_id"] == env.course_id
    assert row["status"] == "open"
    assert row["kinds"] == ["bug"]
    assert row["feedback_text"] == "The next-step button does nothing"
    # Where it came from goes to refs, what it ran on to metadata — and the link token, a credential, to neither.
    assert row["refs"] == {
        "category": "broken",
        "path": "/r/…/lessons/lesson-02",
        "title": "Lesson 2",
        "lesson": "lesson-02",
        "step": "s3",
        "course_id": env.course_id,
    }
    assert row["metadata"] == {"viewport": "390x844", "browser": "Mozilla/5.0 (iPhone)", "language": "he-IL", "anonymous": False}
    assert a.token not in json.dumps(row)
    assert row["deployed_version"]["captured_at"].endswith("Z")


def test_an_anonymous_student_ticket_names_nobody(env):
    a = env.students["a"]
    filed = _ok(_student_post(env, category="idea", text="A dark mode for the lessons", anonymous=True,
                              context={"path": f"/r/{a.token}", "note": f"my link is {a.token}"}))
    assert filed["anonymous"] is True
    row = svc.ticket_row(_ticket(env, filed["id"]))
    assert row["reporter_ref"] is None
    assert row["kinds"] == ["feature_request"]
    assert row["metadata"]["anonymous"] is True
    dumped = json.dumps(row)
    assert a.token not in dumped
    assert "enrollment" not in dumped
    assert "Noa" not in dumped


def test_confusing_is_left_for_a_person_to_classify(env):
    row = svc.ticket_row(_ticket(env, _ok(_student_post(env, category="confusing", text="I don't get what step 3 wants"))["id"]))
    assert row["kinds"] == []
    assert row["refs"]["category"] == "confusing"


def test_a_student_post_needs_the_link_the_header_and_the_same_student(env):
    a, b = env.students["a"], env.students["b"]
    body = {"category": "broken", "text": "Something broke"}
    # An unknown link.
    assert env.client.post("/api/r/not-a-real-token-123456/feedback", json=body, headers=STUDENT).status_code == 404
    # No custom header: another site could post with the student's cookie.
    assert env.client.post(f"/api/r/{a.token}/feedback", json=body).status_code == 403
    # Signed in as b, posting under a's link.
    env.client.cookies.set(student_session.COOKIE_NAME, student_session.issue(b.student_id))
    res = env.client.post(f"/api/r/{a.token}/feedback", json=body, headers=STUDENT)
    assert res.status_code == 403 and res.json()["detail"]["code"] == "wrong_account"
    # Signed in as a: fine. Nothing was filed by the refused posts.
    env.client.cookies.set(student_session.COOKIE_NAME, student_session.issue(a.student_id))
    _ok(env.client.post(f"/api/r/{a.token}/feedback", json=body, headers=STUDENT))
    with env.Session() as db:
        assert len(db.scalars(select(FeedbackTicket)).all()) == 1


def test_a_withdrawn_student_can_still_send_feedback(env):
    with env.Session() as db:
        e = db.get(Enrollment, env.students["a"].enrollment_id)
        e.withdrawn_at = datetime(2026, 11, 1)
        db.commit()
    _ok(_student_post(env))


def test_bad_input_is_refused_and_a_long_context_is_cut_not_refused(env):
    assert _student_post(env, category="praise").status_code == 422
    assert _student_post(env, text="  ").status_code == 422
    assert _student_post(env, text="x" * (svc.MAX_TEXT + 1)).status_code == 422

    context = {f"fact_{i}": "y" * 1000 for i in range(40)}
    context["Bad Name"] = "dropped"
    context["nested"] = {"no": "objects"}
    row = svc.ticket_row(_ticket(env, _ok(_student_post(env, context=context))["id"]))
    facts = {k: v for k, v in row["metadata"].items() if k != "anonymous"}
    assert "Bad Name" not in facts and "nested" not in facts
    assert len(facts) <= svc.MAX_FACTS
    assert all(len(v) <= svc.MAX_FACT_CHARS for v in facts.values())
    assert sum(len(v) for v in facts.values()) <= svc.MAX_CONTEXT_CHARS


def test_the_instructor_files_from_any_page_and_the_middleware_guards_it(env, monkeypatch):
    c = env.client
    body = {"category": "idea", "text": "Show open feedback on the overview", "course_id": env.course_id,
            "context": {"path": f"/course/{env.course_id}?section=lessons", "section": "lessons"}}
    row = svc.ticket_row(_ticket(env, _ok(c.post("/api/feedback", json=body))["id"]))
    assert row["source"] == "instructor" and row["reporter_ref"] == "instructor"
    assert row["refs"]["section"] == "lessons" and row["course_id"] == env.course_id
    assert c.post("/api/feedback", json={**body, "course_id": 999999}).status_code == 404

    monkeypatch.setattr(env.settings, "instructor_token", "s3cret-token")
    assert c.post("/api/feedback", json=body).status_code == 401
    _ok(c.post("/api/feedback", json=body, headers={"X-Instructor-Token": "s3cret-token"}))


def test_the_ticket_api_answers_the_service_token_or_the_instructor_only(env, monkeypatch):
    c = env.client
    _ok(_student_post(env))
    monkeypatch.setattr(env.settings, "instructor_token", "s3cret-token")
    monkeypatch.setattr(env.settings, "org_tickets_token", "svc-token")

    assert c.get("/api/admin/feedback").status_code == 401
    assert c.get("/api/admin/feedback", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert len(_ok(c.get("/api/admin/feedback", headers={"Authorization": "Bearer svc-token"}))) == 1
    assert len(_ok(c.get("/api/admin/feedback", headers={"X-Instructor-Token": "s3cret-token"}))) == 1
    # The service token is not an instructor credential.
    assert c.get("/api/courses", headers={"Authorization": "Bearer svc-token"}).status_code == 401
    # With no service token configured, a Bearer header grants nothing.
    monkeypatch.setattr(env.settings, "org_tickets_token", None)
    assert c.get("/api/admin/feedback", headers={"Authorization": "Bearer "}).status_code == 401


def test_the_ticket_list_pages_to_exhaustion_the_way_org_tickets_reads_it(env):
    for i in range(5):
        _ok(_student_post(env, text=f"report number {i}"))
    c = env.client
    page1 = _ok(c.get("/api/admin/feedback", params={"limit": 2, "offset": 0}))
    page2 = _ok(c.get("/api/admin/feedback", params={"limit": 2, "offset": 2}))
    page3 = _ok(c.get("/api/admin/feedback", params={"limit": 2, "offset": 4}))
    assert [len(p) for p in (page1, page2, page3)] == [2, 2, 1]  # a short page is the end of the table
    ids = [t["id"] for t in page1 + page2 + page3]
    assert len(set(ids)) == 5
    # tickets-core's fields, as org_core/tickets/adapters.py GENERIC_TICKETS_SQL selects them.
    assert {"id", "source", "reporter_ref", "feedback_text", "status", "kinds", "refs", "metadata",
            "sentiment_score", "deployed_version", "created_at", "updated_at"} <= set(page1[0])
    assert _ok(c.get("/api/admin/feedback", params={"status": "closed"})) == []
    assert c.get("/api/admin/feedback", params={"status": "nope"}).status_code == 422


def test_roles_triage_with_notes_status_and_kinds(env):
    c = env.client
    tid = _ok(_student_post(env, category="confusing", text="Step 3 is unclear"))["id"]
    assert _ok(c.get(f"/api/admin/feedback/{tid}/notes")) == []
    note = _ok(c.post(f"/api/admin/feedback/{tid}/notes", json={"author": "Ruth", "note": "Reproduced on a phone", "meta": {"item": "x"}}))
    assert note["ticket_id"] == tid and note["author"] == "Ruth"
    assert [n["note"] for n in _ok(c.get(f"/api/admin/feedback/{tid}/notes"))] == ["Reproduced on a phone"]

    row = _ok(c.patch(f"/api/admin/feedback/{tid}", json={"status": "needs_attention", "kinds": ["question", "bug", "bug"]}))
    assert row["status"] == "needs_attention" and row["kinds"] == ["bug", "question"]
    assert c.patch(f"/api/admin/feedback/{tid}", json={"status": "fixed"}).status_code == 422
    assert c.patch(f"/api/admin/feedback/{tid}", json={"kinds": ["nonsense"]}).status_code == 422
    assert c.post(f"/api/admin/feedback/{tid}/notes", json={"author": "", "note": "x"}).status_code == 422
    assert c.get("/api/admin/feedback/no-such-ticket").status_code == 404
    assert c.post("/api/admin/feedback/no-such-ticket/notes", json={"author": "Ruth", "note": "x"}).status_code == 404
    assert _ok(c.get(f"/api/admin/feedback/{tid}"))["status"] == "needs_attention"


def test_deployed_version_records_the_vercel_build(env, monkeypatch):
    monkeypatch.setenv("VERCEL_GIT_COMMIT_SHA", "abc123")
    monkeypatch.setenv("VERCEL_DEPLOYMENT_ID", "dpl_42")
    monkeypatch.setenv("VERCEL_ENV", "production")
    row = svc.ticket_row(_ticket(env, _ok(_student_post(env))["id"]))
    assert row["deployed_version"]["git_sha"] == "abc123"
    assert row["deployed_version"]["deployment"] == "dpl_42"
    assert row["deployed_version"]["env"] == "production"


def test_migration_0027_round_trips(tmp_path):
    """0027 only adds the two ticket tables, and downgrades to 0026 cleanly, on SQLite and (when TEST_DATABASE_URL
    is set) on Postgres."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import create_engine, inspect, text

    from app.core.config import sqlalchemy_database_url

    backend = Path(__file__).resolve().parents[2]
    urls = [f"sqlite:///{tmp_path / 'm.sqlite3'}"]
    if os.environ.get("TEST_DATABASE_URL"):
        engine = create_engine(sqlalchemy_database_url(os.environ["TEST_DATABASE_URL"]))
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()
        urls.append(os.environ["TEST_DATABASE_URL"])

    for url in urls:
        env = {**os.environ, "DATABASE_URL": url}

        def alembic(*args):
            res = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=backend, env=env, capture_output=True, text=True)
            assert res.returncode == 0, res.stderr
            return res.stdout

        def tables():
            engine = create_engine(sqlalchemy_database_url(url))
            try:
                return set(inspect(engine).get_table_names())
            finally:
                engine.dispose()

        alembic("upgrade", "0026_course_plan_answer_keys")
        before = tables()
        alembic("upgrade", "0027_feedback_tickets")
        assert "0027_feedback_tickets" in alembic("current")
        assert tables() - before == {"feedback_tickets", "feedback_ticket_notes"}
        alembic("downgrade", "0026_course_plan_answer_keys")
        assert tables() == before
        alembic("upgrade", "0027_feedback_tickets")
        assert "0027_feedback_tickets" in alembic("current")


@pytest.mark.parametrize("anonymous", [False, True])
def test_a_link_typed_into_the_text_never_reaches_the_ticket(env, anonymous):
    """Reed's B1 on #52: pasting the page's address into the box is the natural thing to do, and the token in it
    is the student's credential. Named or not, it is cut from the text as it is from the page's facts."""
    a, b = env.students["a"], env.students["b"]
    text = (
        f"page broke: https://course-grader-pi.vercel.app/r/{a.token}/lessons/lesson-04#step=s2 "
        f"(my token is {a.token}; a friend's page https://x.example/r/{b.token} too; "
        f"encoded %2Fr%2F{b.token}%2Flessons)"
    )
    filed = _ok(_student_post(env, text=text, anonymous=anonymous, context={"note": f"https://x/r/{b.token}/x"}))
    row = svc.ticket_row(_ticket(env, filed["id"]))
    dumped = json.dumps(row)
    assert a.token not in dumped and b.token not in dumped
    assert row["feedback_text"] == (
        "page broke: https://course-grader-pi.vercel.app/r/…/lessons/lesson-04#step=s2 "
        "(my token is …; a friend's page https://x.example/r/… too; encoded %2Fr%2F…%2Flessons)"
    )
    assert row["metadata"]["note"] == "https://x/r/…/x"
    # and through the API the roles read
    listed = json.dumps(_ok(env.client.get("/api/admin/feedback")))
    assert a.token not in listed and b.token not in listed


def test_the_instructor_pasting_a_students_link_does_not_store_it_either(env):
    b = env.students["b"]
    filed = _ok(env.client.post("/api/feedback", json={"category": "broken", "text": f"Ido's page /r/{b.token} is blank"}))
    row = svc.ticket_row(_ticket(env, filed["id"]))
    assert row["feedback_text"] == "Ido's page /r/… is blank"
    note = _ok(env.client.post(f"/api/admin/feedback/{filed['id']}/notes", json={"author": "Link", "note": f"see /r/{b.token}"}))
    assert note["note"] == "see /r/…"
    assert b.token not in json.dumps(_ok(env.client.get(f"/api/admin/feedback/{filed['id']}/notes")))


def test_a_text_that_is_only_a_link_is_too_short_once_scrubbed(env):
    assert _student_post(env, text=env.students["a"].token).status_code == 422


def test_only_the_ticket_api_is_exempt_from_the_instructor_middleware(env, monkeypatch):
    """Reed's N1 on #52: the exemption is /api/admin/feedback and what is under it, not all of /api/admin."""
    from app.api import auth

    assert not auth.requires_instructor("/api/admin/feedback", "GET")
    assert not auth.requires_instructor("/api/admin/feedback/abc/notes", "POST")
    assert auth.requires_instructor("/api/admin/feedbackx", "GET")
    assert auth.requires_instructor("/api/admin/other", "GET")
    assert auth.requires_instructor("/api/admin", "GET")
    monkeypatch.setattr(env.settings, "instructor_token", "s3cret-token")
    assert env.client.get("/api/admin/other").status_code == 401
