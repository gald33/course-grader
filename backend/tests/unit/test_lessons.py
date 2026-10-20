from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from lesson_samples import sample_content, write_assets
from sqlalchemy import func, select, text
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.lessons import FIXTURES
from app.main import app
from app.models.entities import (
    Course,
    Enrollment,
    Lesson,
    LessonAttempt,
    LessonCommitment,
    LessonExperiment,
    LessonProgress,
    LessonVersion,
    Student,
)
from app.services import lessons as lessons_svc
from app.services import student_session

BACKEND = Path(__file__).resolve().parents[2]
# Answer-key fields; "answer" and "feedback" are also keys of the answer key
# itself, but the payload's QuestionState legitimately uses those names.
ANSWER_KEYS = {"correct", "misconceptions", "sample_reasoning", "rubric", "explanation"}
CONTENT_KEY_FIELDS = ANSWER_KEYS | {"answer", "feedback"}
LESSON_TABLES = (Lesson, LessonVersion, LessonProgress, LessonAttempt, LessonExperiment, LessonCommitment)
# The sample lesson as the student course page lists it, and its required steps.
_LINK = {"slug": "test-lesson", "title": "שיעור ניסוי"}
_REQUIRED = sum(1 for step in sample_content()["steps"] if not step.get("optional"))


def _ok(res, status=200):
    assert res.status_code == status, res.text
    return res.json()


def _code(res, status):
    assert res.status_code == status, res.text
    return res.json()["detail"]["code"]


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _rid() -> str:
    return str(uuid.uuid4())


class Browser:
    """A student's browser: their signed cookie and the write header the
    lesson pages send. Requests go to the lesson API under a link token."""

    def __init__(self, client: TestClient, token: str, student_id: int | None, header: bool = True):
        self.client, self.token, self.student_id, self.header = client, token, student_id, header

    def call(self, method: str, path: str = "", **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        if self.student_id is not None:
            headers["Cookie"] = f"{student_session.COOKIE_NAME}={student_session.issue(self.student_id)}"
        if method != "GET" and self.header:
            headers["X-CG-Student"] = "1"
        return self.client.request(method, f"/api/r/{self.token}/lessons{path}", headers=headers, **kwargs)

    def lesson(self, slug="test-lesson"):
        return self.call("GET", f"/{slug}")

    def progress(self, body, slug="test-lesson"):
        return self.call("PATCH", f"/{slug}/progress", json=body)

    def answer(self, question_key, answer, request_id=None, slug="test-lesson"):
        body = {"request_id": request_id or _rid(), "question_key": question_key, "answer": answer}
        return self.call("POST", f"/{slug}/attempts", json=body)

    def reveal(self, question_key, request_id=None):
        return self.call("POST", f"/test-lesson/questions/{question_key}/reveal", json={"request_id": request_id or _rid()})

    def experiment(self, run, body):
        base = {"expected_revision": None, "depth_kind": None, "depth": None, "training_examples": None,
                "train_accuracy_pct": None, "validation_accuracy_pct": None, "baseline_validation_pct": None,
                "hypothesis": "", "observation": "", "explanation": ""}
        return self.call("PUT", f"/test-lesson/experiments/{run}", json={**base, **body})

    def commit(self, body):
        base = {"request_id": _rid(), "run_uuid": None, "depth_kind": "limited", "depth": 3,
                "training_examples": 100, "justification": "Validation was highest at depth 3."}
        return self.call("POST", "/test-lesson/commitments", json={**base, **body})

    def final(self, commitment_id, body):
        base = {"final_accuracy_pct": 75, "final_precision_pct": None, "final_recall_pct": None, "final_note": ""}
        return self.call("PATCH", f"/test-lesson/commitments/{commitment_id}/final", json={**base, **body})


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
    monkeypatch.setattr(settings, "session_secret", "lesson-test-secret")
    root = write_assets(tmp_path / "public")
    fixture = tmp_path / "test-lesson.json"
    fixture.write_text(json.dumps(sample_content(), ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(FIXTURES, "test-lesson", fixture)
    monkeypatch.setattr(lessons_svc, "assets_root", lambda: root)
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, Session=SessionLocal, fixture=fixture, root=root)
    app.dependency_overrides.clear()


def _write_fixture(env, content: dict) -> None:
    env.fixture.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")


def _course(env, code: str, students: list[tuple[str, str, bool]]):
    """A course and its students (national id, name, is_test), with links."""
    c = env.client
    course_id = _ok(c.post("/api/courses", json={"code": code, "name": f"Course {code}", "year": 2026, "semester": "A"}))["id"]
    ids, tokens = {}, {}
    with env.Session() as db:
        for nid, name, is_test in students:
            s = Student(national_id=nid, name=name)
            db.add(s)
            db.flush()
            token = f"tok-{nid}-{'x' * 20}"
            db.add(Enrollment(course_id=course_id, student_id=s.id, is_test=is_test, review_token=token))
            ids[name], tokens[name] = s.id, token
        db.commit()
    return SimpleNamespace(id=course_id, ids=ids, tokens=tokens)


def _base(course) -> str:
    return f"/api/courses/{course.id}/lessons"


def _install(env, course, **extra) -> dict:
    return _ok(env.client.post(f"{_base(course)}/install", json={"fixture_key": "test-lesson", **extra}))


def _publish(env, course, summary: dict, version_id: int | None = None) -> dict:
    vid = version_id or summary["draft_version"]["id"]
    return _ok(env.client.post(f"{_base(course)}/{summary['id']}/publish", json={"version_id": vid}))


def _rows(env, model) -> int:
    with env.Session() as db:
        return db.scalar(select(func.count()).select_from(model))


@pytest.fixture
def course(env):
    """Course AI (matches the sample fixture) with the lesson published:
    Alice, Bob, Tess (a test student), Wendy (withdraws)."""
    course = _course(
        env,
        "AI",
        [("100000001", "Alice", False), ("100000002", "Bob", False), ("100000003", "Tess", True), ("100000004", "Wendy", False)],
    )
    course.lesson = _publish(env, course, _install(env, course))
    return course


def _browser(env, course, name, as_name=None, header=True) -> Browser:
    who = course.ids[as_name or name] if as_name != "" else None
    return Browser(env.client, course.tokens[name], who, header=header)


# ---------------------------------------------------------------------------
# Install, publish, versions
# ---------------------------------------------------------------------------


def test_install_is_idempotent_and_versions_published_content(env):
    course = _course(env, "AI", [])
    first = _install(env, course)
    assert first["status"] == "draft" and first["active_version"] is None
    assert first["draft_version"]["number"] == 1 and first["fixture_update_available"] is False
    again = _install(env, course)
    assert again["versions"] == first["versions"]  # same content: no-op

    content = sample_content()
    content["intro"] = "גרסה מתוקנת"
    _write_fixture(env, content)
    listed = _ok(env.client.get(_base(course)))
    assert listed[0]["fixture_update_available"] is True
    updated = _install(env, course)
    assert [v["number"] for v in updated["versions"]] == [1]  # the draft is updated in place
    assert updated["draft_version"]["content_hash"] != first["draft_version"]["content_hash"]

    published = _publish(env, course, updated)
    assert published["status"] == "published" and published["draft_version"] is None
    assert published["active_version"]["number"] == 1 and published["active_version"]["published_at"]

    content["intro"] = "גרסה שלישית"
    _write_fixture(env, content)
    v2 = _install(env, course)
    assert [(v["number"], v["status"]) for v in v2["versions"]] == [(1, "published"), (2, "draft")]
    assert v2["active_version"]["number"] == 1
    with env.Session() as db:  # the published snapshot is untouched
        v1 = db.scalar(select(LessonVersion).where(LessonVersion.number == 1))
        assert json.loads(v1.content_json)["intro"] == "גרסה מתוקנת"

    fixtures = _ok(env.client.get(f"{_base(course)}/fixtures"))
    entry = next(f for f in fixtures if f["key"] == "test-lesson")
    assert entry["valid"] and entry["matches_course"] and entry["installed_lesson_id"] == first["id"]
    assert _rows(env, LessonProgress) == 0 and _rows(env, LessonAttempt) == 0


def test_install_refuses_another_course_and_invalid_content(env):
    other = _course(env, "OTHER", [])
    res = env.client.post(f"{_base(other)}/install", json={"fixture_key": "test-lesson"})
    assert _code(res, 409) == "course_mismatch"
    assert _rows(env, Lesson) == 0
    assert _install(env, other, allow_course_mismatch=True)["status"] == "draft"

    bad = sample_content()
    bad["questions"]["q_pick"]["answer"]["correct"] = ["nope"]
    _write_fixture(env, bad)
    course = _course(env, "AI", [])
    res = env.client.post(f"{_base(course)}/install", json={"fixture_key": "test-lesson"})
    assert _code(res, 422) == "invalid_content"
    assert any("answer.correct 'nope'" in e for e in res.json()["detail"]["errors"])
    assert _code(env.client.post(f"{_base(course)}/install", json={"fixture_key": "nope"}), 404) == "unknown_fixture"


def test_colab_url_settings(env, course):
    url = f"{_base(course)}/{course.lesson['id']}"
    for bad in ("http://colab.research.google.com/x", "https://evil.example/colab", "https://user@drive.google.com/x",
                "javascript:alert(1)", "https://colab.research.google.com.evil.example/"):
        assert _code(env.client.patch(url, json={"colab_url": bad}), 422) == "invalid_colab_url"
    good = "https://colab.research.google.com/drive/abc123"
    assert _ok(env.client.patch(url, json={"colab_url": good}))["colab_url"] == good
    alice = _browser(env, course, "Alice")
    assert _ok(alice.lesson())["colab_url"] == good
    assert _ok(env.client.patch(url, json={"colab_url": ""}))["colab_url"] == ""
    assert _ok(alice.lesson())["colab_url"] is None


# ---------------------------------------------------------------------------
# Student access
# ---------------------------------------------------------------------------


def test_every_student_route_needs_the_matching_signed_in_student(env, course):
    alice = _browser(env, course, "Alice")
    assert _ok(alice.lesson())["mode"] == "student"

    anonymous = _browser(env, course, "Alice", as_name="")
    assert _code(anonymous.call("GET"), 401) == "not_signed_in"
    assert _code(anonymous.lesson(), 401) == "not_signed_in"
    assert _code(anonymous.progress({"expected_revision": 0}), 401) == "not_signed_in"
    forged = Browser(env.client, course.tokens["Alice"], None)
    res = forged.call("GET", headers={"Cookie": f"cg_student={course.ids['Alice']}.9999999999.forged"})
    assert _code(res, 401) == "not_signed_in"

    # Alice's cookie on Bob's link: no reads, no writes.
    as_alice_on_bob = _browser(env, course, "Bob", as_name="Alice")
    assert _code(as_alice_on_bob.lesson(), 403) == "wrong_account"
    assert _code(as_alice_on_bob.progress({"expected_revision": 0, "viewed_add": ["intro"]}), 403) == "wrong_account"
    assert _code(as_alice_on_bob.answer("q_pick", {"choice": "a"}), 403) == "wrong_account"

    assert _code(Browser(env.client, "short", course.ids["Alice"]).call("GET"), 404) == "invalid_link"
    assert _code(Browser(env.client, "x" * 32, course.ids["Alice"]).call("GET"), 404) == "invalid_link"

    no_header = _browser(env, course, "Alice", header=False)
    assert _code(no_header.progress({"expected_revision": 0}), 403) == "bad_request_origin"
    assert _code(no_header.answer("q_pick", {"choice": "a"}), 403) == "bad_request_origin"
    assert _rows(env, LessonProgress) == 0 and _rows(env, LessonAttempt) == 0


def test_lessons_of_another_course_or_unpublished_are_not_found(env, course):
    # Olga's course has no lessons; course AI's published lesson has the same
    # slug she asks for through her own link.
    other = _course(env, "AI2", [("200000001", "Olga", False)])
    olga = _browser(env, other, "Olga")
    assert _code(olga.lesson(), 404) == "lesson_not_found"
    assert _code(olga.progress({"expected_revision": 0, "viewed_add": ["intro"]}), 404) == "lesson_not_found"
    assert _ok(olga.call("GET")) == {"lessons": []}
    _publish(env, other, _install(env, other, allow_course_mismatch=True))
    assert _ok(olga.lesson())["lesson"]["id"] != course.lesson["id"]  # her own course's copy

    alice = _browser(env, course, "Alice")
    _ok(alice.progress({"expected_revision": 0, "viewed_add": ["intro"]}))
    url = f"{_base(course)}/{course.lesson['id']}"
    _ok(env.client.patch(url, json={"status": "draft"}))  # unpublish
    assert _code(alice.lesson(), 404) == "lesson_not_found"
    assert _code(alice.progress({"expected_revision": 1}), 404) == "lesson_not_found"
    assert _ok(alice.call("GET")) == {"lessons": []}
    assert _ok(env.client.get(f"/api/r/{course.tokens['Alice']}"))["lessons"] == []
    _ok(env.client.patch(url, json={"status": "archived"}))
    assert _code(alice.lesson(), 404) == "lesson_not_found"  # existing progress doesn't reopen it
    _publish(env, course, course.lesson, course.lesson["active_version"]["id"])
    assert _ok(alice.lesson())["progress"]["viewed"] == ["intro"]  # progress was kept
    assert _ok(env.client.get(f"/api/r/{course.tokens['Alice']}"))["lessons"] == [
        {**_LINK, "status": "in_progress", "required_done": 0, "required_total": _REQUIRED}
    ]


def test_draft_lesson_is_invisible_to_students(env):
    course = _course(env, "AI", [("100000001", "Alice", False)])
    _install(env, course)
    alice = _browser(env, course, "Alice")
    assert _code(alice.lesson(), 404) == "lesson_not_found"
    assert _ok(alice.call("GET")) == {"lessons": []}


def test_student_payload_never_contains_answer_keys(env, course):
    alice = _browser(env, course, "Alice")
    payload = _ok(alice.lesson())
    assert not ANSWER_KEYS & _keys(payload), ANSWER_KEYS & _keys(payload)
    assert not CONTENT_KEY_FIELDS & _keys(payload["content"])
    assert not ANSWER_KEYS & _keys(_ok(alice.call("GET")))
    assert payload["asset_base"] == "/lessons/test/v1"
    assert payload["version"]["number"] == 1 and payload["progress"] is None
    assert payload["student"] == {"name": "Alice"} and payload["course"]["code"] == "AI"
    assert payload["steps"]["intro"] == {"viewed": False, "completed": False, "done": 0, "total": 2}
    assert payload["questions"]["q_pick"] == {"attempts": 0, "revealed": False, "first": None, "latest": None, "feedback": None}
    # A wrong practice answer reveals only that option's message.
    state = _ok(alice.answer("q_pick", {"choice": "b"}))["question"]
    assert state["feedback"] == {"correct": False, "message": "זו תכונה, לא תווית."}
    assert "correct_options" not in json.dumps(_ok(alice.lesson())["questions"])
    assert _ok(alice.lesson())["questions"]["q_pick"]["feedback"] == state["feedback"]  # same after reload


def test_withdrawn_student_can_read_but_not_write(env, course):
    with env.Session() as db:
        enrollment = db.scalar(select(Enrollment).where(Enrollment.student_id == course.ids["Wendy"]))
        enrollment.withdrawn_at = datetime(2026, 10, 1)
        db.commit()
    wendy = _browser(env, course, "Wendy")
    assert _ok(wendy.lesson())["mode"] == "student"
    assert _code(wendy.progress({"expected_revision": 0, "viewed_add": ["intro"]}), 409) == "withdrawn"
    assert _code(wendy.answer("q_pick", {"choice": "a"}), 409) == "withdrawn"
    assert _rows(env, LessonProgress) == 0


# ---------------------------------------------------------------------------
# Preview
# ---------------------------------------------------------------------------


def test_preview_and_evaluate_write_nothing(env, course):
    base = f"{_base(course)}/{course.lesson['id']}"
    preview = _ok(env.client.get(f"{base}/preview"))
    assert preview["mode"] == "preview" and preview["progress"] is None and preview["student"] is None
    assert preview["questions"] == {} and preview["experiments"] == [] and preview["commitments"] == []
    assert preview["steps"]["lab"] == {"viewed": False, "completed": False, "done": 0, "total": 2}
    assert not ANSWER_KEYS & _keys(preview) and not CONTENT_KEY_FIELDS & _keys(preview["content"])
    vid = course.lesson["active_version"]["id"]
    assert _ok(env.client.get(f"{base}/preview", params={"version_id": vid}))["version"]["id"] == vid

    def evaluate(**body):
        return env.client.post(f"{base}/preview/evaluate", json={"version_id": vid, **body})

    wrong = _ok(evaluate(question_key="q_pick", answer={"choice": "c"}))
    assert wrong == {"feedback": {"correct": False, "message": "זה מזהה."}, "correct": False}
    right = _ok(evaluate(question_key="q_pick", answer={"choice": "a"}, prior_answers=1))
    assert right["correct"] is True and right["feedback"]["correct_options"] == ["a"]
    revealed = _ok(evaluate(question_key="q_pick", reveal=True))
    assert revealed["feedback"]["explanation"] and revealed["correct"] is None
    assert _code(evaluate(question_key="q_check", reveal=True, prior_answers=0), 409) == "answer_first"
    assert _code(evaluate(question_key="q_check", answer={"choice": "x"}), 422) == "invalid_values"
    check = _ok(evaluate(question_key="q_check", answer={"choice": "y", "text": "Because 15 is bigger."}))
    assert check["feedback"]["correct_options"] == ["x"] and check["correct"] is False
    free = _ok(evaluate(question_key="q_free", answer={"text": "Missing values"}))
    assert free == {"feedback": {"correct": None, "sample_reasoning": ["יש ערך חסר."], "rubric": ["מתאר ממצא", "מציע בדיקה"]},
                    "correct": None}
    assert _code(evaluate(question_key="q_nope", answer={"choice": "a"}), 404) == "question_not_found"
    for model in LESSON_TABLES[2:]:
        assert _rows(env, model) == 0, model


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------


def test_progress_is_revision_checked_and_merged(env, course):
    alice = _browser(env, course, "Alice")
    first = _ok(alice.progress({"expected_revision": 0, "current_step_key": "intro", "viewed_add": ["intro"],
                                "drafts": {"q:q_free": "half a thought"}}))
    assert first["progress"]["revision"] == 1 and first["progress"]["viewed"] == ["intro"]
    assert first["steps"]["intro"]["viewed"] and not first["steps"]["intro"]["completed"]

    # A second tab still on revision 0 is stale: 409 with the current state.
    stale = alice.progress({"expected_revision": 0, "viewed_add": ["write"]})
    assert _code(stale, 409) == "stale"
    detail = stale.json()["detail"]
    assert detail["current"]["revision"] == 1 and detail["current"]["drafts"] == {"q:q_free": "half a thought"}
    assert detail["steps"]["intro"]["viewed"] is True

    second = _ok(alice.progress({"expected_revision": 1, "current_step_key": "write", "viewed_add": ["write", "intro"],
                                 "acks_add": ["read_intro"], "drafts": {"q:q_free": None, "experiment_form": "{}"}}))
    progress = second["progress"]
    assert progress["revision"] == 2 and progress["current_step_key"] == "write"
    assert progress["viewed"] == ["intro", "write"] and progress["acks"] == ["read_intro"]
    assert progress["drafts"] == {"experiment_form": "{}"}
    third = _ok(alice.progress({"expected_revision": 2, "acks_remove": ["read_intro"]}))["progress"]
    assert third["acks"] == [] and third["current_step_key"] == "write" and third["revision"] == 3

    # Invalid values: 422 with field messages, nothing saved.
    for body, fields in [
        ({"current_step_key": "nowhere"}, {"current_step_key"}),
        ({"viewed_add": ["nowhere"]}, {"viewed_add"}),
        ({"acks_add": ["made_up"], "acks_remove": ["also"]}, {"acks_add", "acks_remove"}),
        ({"drafts": {"big": "x" * 20001}}, {"drafts.big"}),
        ({"drafts": {"k" * 101: "v"}}, {"drafts"}),
        ({"drafts": {f"d{i}": "v" for i in range(201)}}, {"drafts"}),
        ({"drafts": {f"d{i}": "x" * 20000 for i in range(11)}}, {"drafts"}),
        ({"viewed_add": "intro"}, {"viewed_add"}),
    ]:
        res = alice.progress({"expected_revision": 3, **body})
        assert _code(res, 422) == "invalid_values", body
        assert set(res.json()["detail"]["fields"]) == fields, res.json()
    assert _ok(alice.lesson())["progress"]["revision"] == 3

    bob = _browser(env, course, "Bob")
    assert _code(bob.progress({"expected_revision": 4}), 409) == "stale"  # no row yet: only 0 is current
    assert _rows(env, LessonProgress) == 1


# ---------------------------------------------------------------------------
# Attempts and feedback
# ---------------------------------------------------------------------------


def test_attempts_are_idempotent_append_only_and_keep_the_first_answer(env, course):
    alice = _browser(env, course, "Alice")
    rid = _rid()
    first = _ok(alice.answer("q_pick", {"choice": "b"}, request_id=rid))
    retry = _ok(alice.answer("q_pick", {"choice": "b"}, request_id=rid))
    assert retry == first and _rows(env, LessonAttempt) == 1
    assert _code(alice.answer("q_free", {"text": "something"}, request_id=rid), 409) == "request_reused"

    state = _ok(alice.answer("q_pick", {"choice": "a"}))["question"]
    assert state["attempts"] == 2
    assert state["first"]["answer"] == {"choice": "b"} and state["first"]["correct"] is False
    assert state["latest"]["answer"] == {"choice": "a"} and state["latest"]["attempt_number"] == 2
    assert state["feedback"] == {"correct": True, "message": "נכון: זה מה שמנבאים.",
                                 "explanation": "התווית היא מה שמנסים לחזות.", "correct_options": ["a"]}

    with env.Session() as db:
        rows = db.scalars(select(LessonAttempt).order_by(LessonAttempt.id)).all()
        assert [(r.attempt_number, r.correct, r.after_feedback) for r in rows] == [(1, False, False), (2, True, True)]
        assert rows[0].version_id == course.lesson["active_version"]["id"] and rows[0].step_key == "intro"
        assert len(rows[0].question_hash) == 64

    # Answering pins the student's progress, revision 0 until the first progress write.
    payload = _ok(alice.lesson())
    assert payload["progress"]["revision"] == 0
    assert payload["steps"]["intro"] == {"viewed": False, "completed": False, "done": 1, "total": 2}
    _ok(alice.progress({"expected_revision": 0, "acks_add": ["read_intro"]}))
    assert _ok(alice.lesson())["steps"]["intro"]["completed"] is True

    stats = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/insights"))
    q = next(q for q in stats["questions"] if q["key"] == "q_pick")
    assert (q["answered"], q["first_correct"], q["first_incorrect"], q["eventually_correct_after_wrong_first"]) == (1, 0, 1, 1)
    assert q["attempts_after_feedback"] == 1 and q["unanswered"] == 2  # Bob and (included) nobody else
    options = {o["id"]: o for o in q["options"]}
    assert options["b"]["first_count"] == 1 and options["b"]["misconception"] == "feature-as-label"
    assert options["a"]["first_count"] == 0 and options["a"]["all_count"] == 1 and options["a"]["correct"] is True

    for bad, field in [({"choice": "nope"}, "choice"), ({}, "choice")]:
        assert set(alice.answer("q_pick", bad).json()["detail"]["fields"]) == {field}
    assert _code(alice.answer("q_unknown", {"choice": "a"}), 404) == "question_not_found"
    res = alice.call("POST", "/test-lesson/attempts", json={"request_id": "bad id!", "question_key": "q_pick", "answer": {"choice": "a"}})
    assert _code(res, 422) == "invalid_values"
    res = alice.call("POST", "/test-lesson/attempts", json={"request_id": _rid(), "question_key": "q_pick", "answer": "a"})
    assert _code(res, 422) == "invalid_values" and "answer" in res.json()["detail"]["fields"]
    assert _rows(env, LessonAttempt) == 2


def test_reveal_and_check_mode_rules(env, course):
    alice = _browser(env, course, "Alice")
    # Practice: reveal before answering is allowed and recorded.
    revealed = _ok(alice.reveal("q_pick"))["question"]
    assert revealed["revealed"] is True and revealed["attempts"] == 0
    assert revealed["feedback"] == {"correct": None, "explanation": "התווית היא מה שמנסים לחזות.", "correct_options": ["a"]}
    after = _ok(alice.answer("q_pick", {"choice": "c"}))["question"]
    assert after["feedback"] == {"correct": False, "message": "זה מזהה."}  # feedback for the latest answer
    again = _ok(alice.reveal("q_pick"))["question"]
    assert again["feedback"]["correct"] is False and again["feedback"]["message"] == "זה מזהה."
    assert again["feedback"]["correct_options"] == ["a"]

    # Check mode: no reveal before an individual answer; the explanation is required.
    assert _code(alice.reveal("q_check"), 409) == "answer_first"
    res = alice.answer("q_check", {"choice": "y", "text": "short"})
    assert _code(res, 422) == "invalid_values" and set(res.json()["detail"]["fields"]) == {"text"}
    check = _ok(alice.answer("q_check", {"choice": "y", "text": "It goes left because 15 is small."}))["question"]
    assert check["feedback"]["correct"] is False and check["feedback"]["correct_options"] == ["x"]
    assert check["feedback"]["explanation"] == "15 גדול מ-13.5 ולכן ימינה."
    revised = _ok(alice.answer("q_check", {"choice": "x", "text": "15 is above 13.5 so it goes right."}))["question"]
    assert revised["first"]["answer"]["choice"] == "y" and revised["attempts"] == 2

    # Free text: never graded; the sample reasoning and rubric come after submitting.
    assert set(alice.answer("q_free", {"text": "abc"}).json()["detail"]["fields"]) == {"text"}  # min_chars 5
    free = _ok(alice.answer("q_free", {"text": "Two rows are out of range."}))["question"]
    assert free["feedback"] == {"correct": None, "sample_reasoning": ["יש ערך חסר."], "rubric": ["מתאר ממצא", "מציע בדיקה"]}
    assert free["latest"]["correct"] is None

    detail = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/students/{course.ids['Alice']}"))
    kinds = [(a["question_key"], a["kind"], a["attempt_number"]) for a in detail["attempts"]]
    assert kinds[:3] == [("q_pick", "reveal", 0), ("q_pick", "answer", 1), ("q_pick", "reveal", 1)]
    stats = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/insights"))["questions"]
    pick = next(q for q in stats if q["key"] == "q_pick")
    assert pick["revealed_before_answer"] == 1 and pick["attempts_after_feedback"] == 1
    check_stats = next(q for q in stats if q["key"] == "q_check")
    assert [t["text"] for t in check_stats["free_text"]] == [
        "It goes left because 15 is small.", "15 is above 13.5 so it goes right."
    ]


def test_answers_after_a_reveal_are_not_first_try_evidence(env, course):
    alice, bob, wendy = (_browser(env, course, n) for n in ("Alice", "Bob", "Wendy"))
    _ok(alice.answer("q_pick", {"choice": "a"}))  # right, on her own
    _ok(bob.reveal("q_pick"))  # sees the correct option, then picks it
    _ok(bob.answer("q_pick", {"choice": "a"}))
    _ok(wendy.reveal("q_pick"))
    _ok(wendy.answer("q_pick", {"choice": "b"}))
    _ok(wendy.answer("q_pick", {"choice": "a"}))

    base = f"{_base(course)}/{course.lesson['id']}"
    pick = next(q for q in _ok(env.client.get(f"{base}/insights"))["questions"] if q["key"] == "q_pick")
    assert (pick["answered"], pick["answered_after_reveal"], pick["revealed_before_answer"]) == (3, 2, 2)
    assert (pick["first_correct"], pick["first_incorrect"], pick["eventually_correct_after_wrong_first"]) == (1, 0, 0)
    assert pick["attempts_after_feedback"] == 3  # every answer after a reveal or an earlier answer
    counts = {o["id"]: (o["first_count"], o["all_count"]) for o in pick["options"]}
    assert counts == {"a": (1, 3), "b": (0, 1), "c": (0, 0)}

    rows = env.client.get(f"{base}/export.csv").content.decode("utf-8").lstrip("\ufeff").splitlines()
    first_correct = {r.split(",")[0]: r.split(",")[6] for r in rows[1:]}
    assert (first_correct["Alice"], first_correct["Bob"], first_correct["Wendy"]) == ("1", "0", "0")


def test_written_answers_list_each_students_first_and_latest(env, course):
    alice = _browser(env, course, "Alice")
    for body in ("First try at a finding.", "Second, middle version.", "Third and latest version."):
        _ok(alice.answer("q_free", {"text": body}))
    base = f"{_base(course)}/{course.lesson['id']}"

    def written():
        stats = _ok(env.client.get(f"{base}/insights"))["questions"]
        return [(t["attempt_number"], t["text"]) for t in next(q for q in stats if q["key"] == "q_free")["free_text"]]

    assert written() == [(1, "First try at a finding."), (3, "Third and latest version.")]
    middle = _ok(env.client.get(f"{base}/students/{course.ids['Alice']}"))["attempts"][1]
    assert middle["answer"]["text"] == "Second, middle version."  # every attempt in the drilldown
    _ok(env.client.post(f"{base}/attempts/{middle['id']}/flag", json={"flagged": True}))
    assert [n for n, _ in written()] == [1, 2, 3]  # a flagged one stays listed


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------


def test_experiments_validate_units_and_revisions(env, course):
    alice = _browser(env, course, "Alice")
    run = _rid()
    res = alice.experiment(run, {"depth_kind": "limited", "depth": 2, "training_examples": 100,
                                 "train_accuracy_pct": 130, "validation_accuracy_pct": -1,
                                 "baseline_validation_pct": 0.5, "hypothesis": "More depth fits training better."})
    assert _code(res, 422) == "invalid_values"
    assert set(res.json()["detail"]["fields"]) == {"train_accuracy_pct", "validation_accuracy_pct"}
    assert _rows(env, LessonExperiment) == 0 and _rows(env, LessonProgress) == 0  # nothing saved

    for body, field in [
        ({"depth_kind": "limited", "depth": 0}, "depth"),  # Colab's 0 is "unlimited", never a depth
        ({"depth_kind": "limited", "depth": 2.5}, "depth"),
        ({"depth_kind": "limited", "depth": 51}, "depth"),
        ({"depth_kind": "limited"}, "depth"),
        ({"depth_kind": "unlimited", "depth": 0}, "depth"),
        ({"depth": 3}, "depth"),
        ({"depth_kind": "deep"}, "depth_kind"),
        ({"training_examples": 19}, "training_examples"),
        ({"training_examples": 721}, "training_examples"),
        ({"train_accuracy_pct": "80"}, "train_accuracy_pct"),
        ({"hypothesis": "x" * 5001}, "hypothesis"),
        ({}, "hypothesis"),  # an empty record
    ]:
        res = alice.experiment(run, body)
        assert _code(res, 422) == "invalid_values", body
        assert field in res.json()["detail"]["fields"], (body, res.json())
    assert "ללא הגבלה" in alice.experiment(run, {"depth_kind": "limited", "depth": 0}).json()["detail"]["fields"]["depth"]
    assert alice.experiment(run, {"train_accuracy_pct": "80"}).json()["detail"]["fields"] == {"train_accuracy_pct": "הזינו מספר"}
    assert _code(alice.experiment("not-a-uuid", {"hypothesis": "h"}), 422) == "invalid_values"

    # A hypothesis alone is a valid first save.
    saved = _ok(alice.experiment(run, {"hypothesis": "Depth 1 will underfit."}))["experiments"]
    assert saved[0]["revision"] == 1 and saved[0]["complete"] is False and saved[0]["provenance"] == "student_entered"
    assert _code(alice.experiment(run, {"hypothesis": "again"}), 409) == "stale"  # create over an existing record

    full = {"expected_revision": 1, "depth_kind": "unlimited", "depth": None, "training_examples": 100,
            "train_accuracy_pct": 100, "validation_accuracy_pct": 66.25, "baseline_validation_pct": 54.2,
            "hypothesis": "Depth 1 will underfit.", "observation": "Training 100%, validation lower.",
            "explanation": "It memorised the training set."}
    result = _ok(alice.experiment(run, full))
    record = result["experiments"][0]
    assert record["revision"] == 2 and record["complete"] is True
    assert (record["depth_kind"], record["depth"]) == ("unlimited", None)
    assert (record["train_accuracy"], record["validation_accuracy"], record["baseline_validation"]) == (1.0, 0.6625, 0.542)
    assert result["steps"]["lab"]["done"] == 1  # one complete experiment; no commitment yet

    stale = alice.experiment(run, {**full, "expected_revision": 1, "observation": "from an old tab"})
    assert _code(stale, 409) == "stale"
    assert stale.json()["detail"]["current"]["revision"] == 2
    assert stale.json()["detail"]["current"]["observation"] == "Training 100%, validation lower."

    second = _rid()
    _ok(alice.experiment(second, {"depth_kind": "limited", "depth": 3, "training_examples": 300, "hypothesis": "h"}))
    listed = _ok(alice.lesson())["experiments"]
    assert [e["run_uuid"] for e in listed] == [run, second]

    # Delete: stale check, then gone for the student but kept for the instructor.
    assert _code(alice.call("DELETE", f"/test-lesson/experiments/{run}", params={"expected_revision": 1}), 409) == "stale"
    after = _ok(alice.call("DELETE", f"/test-lesson/experiments/{run}", params={"expected_revision": 2}))
    assert [e["run_uuid"] for e in after["experiments"]] == [second]
    _ok(alice.call("DELETE", f"/test-lesson/experiments/{run}", params={"expected_revision": 2}))  # retry: no-op
    assert _code(alice.experiment(run, {**full, "expected_revision": 2}), 409) == "stale"
    assert _code(alice.call("DELETE", f"/test-lesson/experiments/{_rid()}", params={"expected_revision": 1}), 404) == "experiment_not_found"
    detail = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/students/{course.ids['Alice']}"))
    by_run = {e["run_uuid"]: e for e in detail["experiments"]}
    assert by_run[run]["deleted_at"] and by_run[second]["deleted_at"] is None

    # Bob can't touch Alice's record through his own link.
    bob = _browser(env, course, "Bob")
    assert _code(bob.call("DELETE", f"/test-lesson/experiments/{second}", params={"expected_revision": 1}), 404) == "experiment_not_found"
    assert _ok(bob.experiment(second, {"hypothesis": "mine"}))["experiments"][0]["hypothesis"] == "mine"  # his own run id space
    assert _ok(alice.lesson())["experiments"][0]["hypothesis"] == "h"


def test_first_prediction_is_kept_for_the_instructor(env, course):
    alice = _browser(env, course, "Alice")
    run, later = _rid(), _rid()
    _ok(alice.experiment(run, {"hypothesis": "Deeper is better."}))
    _ok(alice.experiment(run, {"expected_revision": 1, "depth_kind": "unlimited", "training_examples": 100,
                               "train_accuracy_pct": 100, "validation_accuracy_pct": 66.25,
                               "baseline_validation_pct": 54.2, "hypothesis": "Deeper overfits (rewritten after).",
                               "observation": "Training 100%, validation 66%."}))
    _ok(alice.experiment(later, {"depth_kind": "limited", "depth": 3, "training_examples": 100}))  # no prediction yet
    _ok(alice.experiment(later, {"expected_revision": 1, "depth_kind": "limited", "depth": 3,
                                 "training_examples": 100, "hypothesis": "Depth 3 helps a little."}))
    _ok(alice.experiment(later, {"expected_revision": 2, "depth_kind": "limited", "depth": 3,
                                 "training_examples": 100, "hypothesis": "Changed again."}))

    detail = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/students/{course.ids['Alice']}"))
    by_run = {e["run_uuid"]: e for e in detail["experiments"]}
    assert by_run[run]["hypothesis"] == "Deeper overfits (rewritten after)."
    assert by_run[run]["first_hypothesis"] == "Deeper is better." and by_run[run]["first_hypothesis_at"]
    assert by_run[run]["first_hypothesis_at"] < by_run[run]["updated_at"]
    assert by_run[later]["first_hypothesis"] == "Depth 3 helps a little."
    assert "first_hypothesis" not in _ok(alice.lesson())["experiments"][0]  # instructor view only


def test_experiment_limit(env, course, monkeypatch):
    alice = _browser(env, course, "Alice")
    for _ in range(lessons_svc.MAX_EXPERIMENTS):
        _ok(alice.experiment(_rid(), {"hypothesis": "h"}))
    assert _code(alice.experiment(_rid(), {"hypothesis": "h"}), 409) == "too_many_experiments"

    # Deleted records count toward a higher cap on every record ever created.
    bob = _browser(env, course, "Bob")
    monkeypatch.setattr(lessons_svc, "MAX_EXPERIMENT_ROWS", 4)
    for _ in range(3):
        run = _rid()
        _ok(bob.experiment(run, {"hypothesis": "h"}))
        _ok(bob.call("DELETE", f"/test-lesson/experiments/{run}", params={"expected_revision": 1}))
    kept = _rid()
    _ok(bob.experiment(kept, {"hypothesis": "h"}))
    res = bob.experiment(_rid(), {"hypothesis": "h"})
    assert _code(res, 409) == "too_many_experiments" and "שנמחקו" in res.json()["detail"]["message"]
    edited = _ok(bob.experiment(kept, {"expected_revision": 1, "hypothesis": "edits still work"}))
    assert [e["hypothesis"] for e in edited["experiments"]] == ["edits still work"]


def test_answers_reveals_and_commitments_are_capped(env, course):
    alice = _browser(env, course, "Alice")
    first_rid = _rid()
    first = _ok(alice.answer("q_pick", {"choice": "c"}, request_id=first_rid))
    for _ in range(lessons_svc.MAX_ANSWERS_PER_QUESTION - 1):
        _ok(alice.answer("q_pick", {"choice": "b"}))
    res = alice.answer("q_pick", {"choice": "a"})
    assert _code(res, 409) == "too_many_attempts" and "20" in res.json()["detail"]["message"]
    replay = _ok(alice.answer("q_pick", {"choice": "c"}, request_id=first_rid))  # a retry still gets its result
    assert replay["question"]["first"] == first["question"]["first"]
    assert _ok(alice.answer("q_extra", {"choice": "id"}))["question"]["attempts"] == 1  # per question

    for _ in range(lessons_svc.MAX_REVEALS_PER_QUESTION):
        _ok(alice.reveal("q_pick"))
    rows = _rows(env, LessonAttempt)
    capped = _ok(alice.reveal("q_pick"))["question"]  # still shows the reasoning, records nothing
    assert _rows(env, LessonAttempt) == rows
    assert capped["revealed"] is True and capped["feedback"]["correct_options"] == ["a"]
    assert capped["feedback"]["explanation"] and capped["feedback"]["message"] == "זו תכונה, לא תווית."

    commit_rid = _rid()
    _ok(alice.commit({"request_id": commit_rid}))
    for _ in range(lessons_svc.MAX_COMMITMENTS - 1):
        _ok(alice.commit({}))
    assert _code(alice.commit({}), 409) == "too_many_commitments"
    assert len(_ok(alice.commit({"request_id": commit_rid}))["commitments"]) == lessons_svc.MAX_COMMITMENTS
    assert _rows(env, LessonCommitment) == lessons_svc.MAX_COMMITMENTS


# ---------------------------------------------------------------------------
# Commitments and final results
# ---------------------------------------------------------------------------


def test_commitments_and_final_results(env, course):
    alice = _browser(env, course, "Alice")
    assert _code(alice.final(999, {}), 404) == "commitment_not_found"
    res = alice.commit({"justification": "short", "depth": 0})
    assert _code(res, 422) == "invalid_values"
    assert set(res.json()["detail"]["fields"]) == {"justification", "depth"}
    res = alice.commit({"run_uuid": _rid()})
    assert set(res.json()["detail"]["fields"]) == {"run_uuid"}  # not one of her runs
    assert _rows(env, LessonCommitment) == 0

    run = _rid()
    _ok(alice.experiment(run, {"depth_kind": "limited", "depth": 3, "training_examples": 100, "hypothesis": "h"}))
    rid = _rid()
    first = _ok(alice.commit({"request_id": rid, "run_uuid": run}))
    assert _ok(alice.commit({"request_id": rid, "run_uuid": run})) == first  # retried request
    commitment = first["commitments"][0]
    assert commitment["after_final_seen"] is False and commitment["final"] is None and commitment["run_uuid"] == run

    bob = _browser(env, course, "Bob")
    assert _code(bob.final(commitment["id"], {}), 404) == "commitment_not_found"
    res = alice.final(commitment["id"], {"final_accuracy_pct": None, "final_recall_pct": 101})
    assert set(res.json()["detail"]["fields"]) == {"final_accuracy_pct", "final_recall_pct"}
    recorded = _ok(alice.final(commitment["id"], {"final_accuracy_pct": 74.5, "final_precision_pct": 70, "final_note": "ok"}))
    final = recorded["commitments"][0]["final"]
    assert (final["accuracy"], final["precision"], final["recall"], final["note"]) == (0.745, 0.7, None, "ok")
    assert _code(alice.final(commitment["id"], {"final_accuracy_pct": 90}), 409) == "final_already_recorded"

    revised = _ok(alice.commit({"depth_kind": "unlimited", "depth": None, "justification": "Changed my mind after the test."}))
    assert [c["after_final_seen"] for c in revised["commitments"]] == [False, True]
    assert revised["commitments"][0]["final"]["accuracy"] == 0.745  # the earlier commitment is kept as it was

    students = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/insights"))["students"]
    row = next(s for s in students if s["name"] == "Alice")
    assert row["committed"] and row["final_recorded"] and row["revised_after_final"]


# ---------------------------------------------------------------------------
# Completion, pinning, insights
# ---------------------------------------------------------------------------


def _complete_required(alice: Browser) -> dict:
    _ok(alice.progress({"expected_revision": 0, "viewed_add": ["intro", "write", "lab"], "acks_add": ["read_intro"]}))
    _ok(alice.answer("q_pick", {"choice": "b"}))
    _ok(alice.answer("q_free", {"text": "Two customers are out of range."}))
    _ok(alice.answer("q_check", {"choice": "x", "text": "15 is above 13.5, so right."}))
    _ok(alice.experiment(_rid(), {"depth_kind": "limited", "depth": 2, "training_examples": 100,
                                  "train_accuracy_pct": 83, "validation_accuracy_pct": 76.25,
                                  "baseline_validation_pct": 54.2, "observation": "A gap of 7 points."}))
    return _ok(alice.commit({}))


def test_completion_is_computed_from_evidence(env, course):
    alice = _browser(env, course, "Alice")
    _ok(alice.progress({"expected_revision": 0, "viewed_add": ["intro", "write", "lab", "extra"]}))
    payload = _ok(alice.lesson())
    assert all(s["viewed"] and not s["completed"] for s in payload["steps"].values())  # viewed is not completed
    assert payload["progress"]["completed_at"] is None

    _ok(alice.progress({"expected_revision": 1, "acks_add": ["read_intro"]}))
    _ok(alice.answer("q_pick", {"choice": "c"}))  # a wrong answer still counts as answered
    _ok(alice.answer("q_free", {"text": "Two customers are out of range."}))
    _ok(alice.answer("q_check", {"choice": "y", "text": "It goes left, I think."}))
    _ok(alice.experiment(_rid(), {"depth_kind": "limited", "depth": 2, "training_examples": 100,
                                  "train_accuracy_pct": 83, "validation_accuracy_pct": 76.25,
                                  "baseline_validation_pct": 54.2}))  # no observation: not complete
    almost = _ok(alice.commit({}))
    assert almost["completed_at"] is None and almost["steps"]["lab"]["done"] == 1
    run = _ok(alice.lesson())["experiments"][0]
    done = _ok(alice.experiment(run["run_uuid"], {**{k: run[k] for k in ("depth_kind", "depth", "training_examples")},
                                                  "expected_revision": 1, "train_accuracy_pct": 83,
                                                  "validation_accuracy_pct": 76.25, "baseline_validation_pct": 54.2,
                                                  "observation": "A gap of 7 points."}))
    assert done["completed_at"] is not None  # the optional step was never needed
    assert done["steps"]["extra"]["completed"] is False
    listed = _ok(alice.call("GET"))["lessons"][0]
    assert (listed["status"], listed["required_done"], listed["required_total"]) == ("completed", 3, 3)

    # completed_at is set once: removing an ack later doesn't unset it, but
    # the status follows the evidence.
    revision = _ok(alice.lesson())["progress"]["revision"]
    after = _ok(alice.progress({"expected_revision": revision, "acks_remove": ["read_intro"]}))
    assert after["progress"]["completed_at"] == done["completed_at"] and after["steps"]["intro"]["completed"] is False
    listed = _ok(alice.call("GET"))["lessons"][0]
    assert (listed["status"], listed["required_done"], listed["required_total"]) == ("in_progress", 2, 3)


def test_status_follows_evidence_after_completion(env, course):
    alice = _browser(env, course, "Alice")
    _complete_required(alice)
    run = _ok(alice.lesson())["experiments"][0]
    base = f"{_base(course)}/{course.lesson['id']}"

    def statuses():
        listed = _ok(alice.call("GET"))["lessons"][0]
        stats = _ok(env.client.get(f"{base}/insights"))
        row = next(s for s in stats["students"] if s["name"] == "Alice")
        csv_row = next(r for r in env.client.get(f"{base}/export.csv").text.splitlines() if "Alice" in r)
        detail = _ok(env.client.get(f"{base}/students/{course.ids['Alice']}"))
        return {
            "list": (listed["status"], listed["required_done"]),
            "insights": (row["status"], row["completed_required"], stats["totals"]["completed"]),
            "csv": csv_row.split(",")[1],
            "detail": detail["status"],
            "completed_at": detail["progress"]["completed_at"],
        }

    before = statuses()
    assert before["list"] == ("completed", 3) and before["insights"] == ("completed", 3, 1)
    assert before["csv"] == "completed" and before["detail"] == "completed" and before["completed_at"]

    deleted = _ok(alice.call("DELETE", f"/test-lesson/experiments/{run['run_uuid']}", params={"expected_revision": 1}))
    assert deleted["steps"]["lab"]["completed"] is False and deleted["completed_at"] == before["completed_at"]
    after = statuses()
    assert after["list"] == ("in_progress", 2) and after["insights"] == ("in_progress", 2, 0)
    assert after["csv"] == "in_progress" and after["detail"] == "in_progress"
    assert after["completed_at"] == before["completed_at"]  # history: when she first completed

    _ok(alice.experiment(_rid(), {"depth_kind": "unlimited", "training_examples": 300, "train_accuracy_pct": 100,
                                  "validation_accuracy_pct": 70, "baseline_validation_pct": 54.2,
                                  "observation": "Training 100%, validation 70%."}))
    again = statuses()
    assert again["list"] == ("completed", 3) and again["insights"] == ("completed", 3, 1)
    assert again["completed_at"] == before["completed_at"]


def test_published_versions_stay_pinned(env, course):
    alice = _browser(env, course, "Alice")
    _ok(alice.progress({"expected_revision": 0, "viewed_add": ["intro"]}))
    _ok(alice.answer("q_pick", {"choice": "a"}))
    v1 = course.lesson["active_version"]

    content = sample_content()
    content["questions"]["q_pick"]["prompt"] = "גרסה 2: מהי התווית?"
    _write_fixture(env, content)
    v2 = _install(env, course)["draft_version"]
    assert v2["number"] == 2
    assert _ok(alice.lesson())["version"]["id"] == v1["id"]  # a draft changes nothing
    _publish(env, course, course.lesson, v2["id"])

    mine = _ok(alice.lesson())
    assert mine["version"]["id"] == v1["id"] and mine["content"]["questions"]["q_pick"]["prompt"] == "מהי התווית?"
    bob = _browser(env, course, "Bob")
    theirs = _ok(bob.lesson())
    assert theirs["version"]["id"] == v2["id"] and theirs["content"]["questions"]["q_pick"]["prompt"].startswith("גרסה 2")
    _ok(bob.answer("q_pick", {"choice": "b"}))
    with env.Session() as db:
        assert sorted(p.version_id for p in db.scalars(select(LessonProgress))) == [v1["id"], v2["id"]]
        attempts = {(a.question_key, a.version_id) for a in db.scalars(select(LessonAttempt))}
        assert attempts == {("q_pick", v1["id"]), ("q_pick", v2["id"])}

    # Correctness counts per question key over every version; the option bars
    # only count answers to the question as the live version defines it.
    base = f"{_base(course)}/{course.lesson['id']}"

    def pick_stats():
        return next(q for q in _ok(env.client.get(f"{base}/insights"))["questions"] if q["key"] == "q_pick")

    def changed(name):
        return [a["question_changed"] for a in _ok(env.client.get(f"{base}/students/{course.ids[name]}"))["attempts"]]

    q = pick_stats()
    assert q["answered"] == 2 and q["first_correct"] == 1 and q["first_incorrect"] == 1
    assert q["prompt"].startswith("גרסה 2")  # as defined in the live version
    assert {o["id"]: o["first_count"] for o in q["options"]} == {"a": 0, "b": 1, "c": 0}
    assert q["other_version_answers"] == 1  # Alice answered v1's wording
    assert changed("Alice") == [True] and changed("Bob") == [False]

    # Republishing v1 sends only students who haven't started back to it.
    _publish(env, course, course.lesson, v1["id"])
    assert _ok(bob.lesson())["version"]["id"] == v2["id"]
    tess = _browser(env, course, "Tess")
    assert _ok(tess.lesson())["version"]["id"] == v1["id"]

    stats = _ok(env.client.get(f"{base}/insights"))
    q = next(q for q in stats["questions"] if q["key"] == "q_pick")
    assert q["answered"] == 2 and q["first_correct"] == 1 and q["first_incorrect"] == 1
    assert q["prompt"] == "מהי התווית?"  # v1 is live again
    assert {o["id"]: o["first_count"] for o in q["options"]} == {"a": 1, "b": 0, "c": 0}
    assert q["other_version_answers"] == 1  # now Bob's v2 answer
    assert changed("Alice") == [False] and changed("Bob") == [True]
    students = {s["name"]: s for s in stats["students"]}
    assert students["Alice"]["version_number"] == 1 and students["Bob"]["version_number"] == 2


def test_option_bars_never_read_an_answer_with_another_versions_options(env, course):
    alice = _browser(env, course, "Alice")
    _ok(alice.answer("q_pick", {"choice": "b"}))  # v1: b is visits_30d (feature-as-label)
    content = sample_content()
    q = content["questions"]["q_pick"]
    q["options"][1]["text"], q["options"][2]["text"] = q["options"][2]["text"], q["options"][1]["text"]
    q["answer"]["misconceptions"] = {"b": "id-as-label", "c": "feature-as-label"}
    q["answer"]["feedback"]["b"], q["answer"]["feedback"]["c"] = q["answer"]["feedback"]["c"], q["answer"]["feedback"]["b"]
    _write_fixture(env, content)
    _publish(env, course, course.lesson, _install(env, course)["draft_version"]["id"])

    stats = _ok(env.client.get(f"{_base(course)}/{course.lesson['id']}/insights"))
    pick = next(x for x in stats["questions"] if x["key"] == "q_pick")
    assert (pick["answered"], pick["first_incorrect"], pick["other_version_answers"]) == (1, 1, 1)
    bars = {o["id"]: (o["misconception"], o["first_count"], o["all_count"]) for o in pick["options"]}
    assert bars["b"] == ("id-as-label", 0, 0)  # not reinterpreted as v2's misconception
    assert bars["c"] == ("feature-as-label", 0, 0)


def test_insights_count_enrolled_students_and_export(env, course):
    with env.Session() as db:
        wendy = db.scalar(select(Enrollment).where(Enrollment.student_id == course.ids["Wendy"]))
        wendy.withdrawn_at = datetime(2026, 10, 1)
        db.commit()
    alice = _browser(env, course, "Alice")
    _complete_required(alice)
    _ok(alice.answer("q_extra", {"choice": "id"}))
    tess = _browser(env, course, "Tess")
    _ok(tess.progress({"expected_revision": 0, "viewed_add": ["intro"]}))

    base = f"{_base(course)}/{course.lesson['id']}"
    stats = _ok(env.client.get(f"{base}/insights"))
    assert stats["totals"] == {"enrolled": 2, "not_started": 1, "in_progress": 0, "completed": 1,
                               "excluded_test": 1, "withdrawn": 1}
    assert stats["lesson"]["id"] == course.lesson["id"]
    steps = {s["key"]: s for s in stats["steps"]}
    assert (steps["intro"]["viewed"], steps["intro"]["completed"]) == (1, 1)
    assert steps["extra"]["optional"] is True and steps["extra"]["completed"] == 1 and steps["extra"]["viewed"] == 0
    students = {s["name"]: s for s in stats["students"]}
    assert list(students) == ["Alice", "Bob", "Tess", "Wendy"]  # every enrollment, by name
    assert students["Bob"]["status"] == "not_started" and students["Bob"]["last_activity_at"] is None
    assert students["Wendy"]["withdrawn"] is True and students["Tess"]["is_test"] is True
    a = students["Alice"]
    assert (a["status"], a["completed_required"], a["required_total"], a["optional_completed"]) == ("completed", 3, 3, 1)
    assert (a["viewed_steps"], a["experiments"], a["committed"], a["free_text_answers"]) == (3, 1, True, 1)
    assert a["last_activity_at"] and a["current_step_key"] is None
    pick = next(q for q in stats["questions"] if q["key"] == "q_pick")
    assert (pick["answered"], pick["unanswered"]) == (1, 1)  # Bob; Tess and Wendy are left out

    with_test = _ok(env.client.get(f"{base}/insights", params={"include_test": True}))
    assert with_test["totals"]["enrolled"] == 3 and with_test["totals"]["in_progress"] == 1
    assert with_test["totals"]["excluded_test"] == 0

    free = next(q for q in stats["questions"] if q["key"] == "q_free")["free_text"]
    assert free[0]["name"] == "Alice" and free[0]["flagged"] is False
    assert _ok(env.client.post(f"{base}/attempts/{free[0]['attempt_id']}/flag", json={"flagged": True})) == {
        "id": free[0]["attempt_id"], "review_flag": True
    }
    stats = _ok(env.client.get(f"{base}/insights"))
    assert next(q for q in stats["questions"] if q["key"] == "q_free")["free_text"][0]["flagged"] is True
    assert next(s for s in stats["students"] if s["name"] == "Alice")["flagged"] == 1
    assert env.client.post(f"{base}/attempts/99999/flag", json={"flagged": True}).status_code == 404

    res = env.client.get(f"{base}/export.csv")
    assert res.status_code == 200 and res.headers["content-type"] == "text/csv; charset=utf-8"
    assert "attachment" in res.headers["content-disposition"]
    text = res.content.decode("utf-8")
    assert text.startswith("﻿name,status,required_done,required_total,experiments,committed,first_attempt_correct")
    lines = text.lstrip("﻿").splitlines()
    assert lines[1].startswith("Alice,completed,3,3,1,yes,2,") and lines[2].startswith("Bob,not_started,0,3,0,no,0,")

    detail = _ok(env.client.get(f"{base}/students/{course.ids['Alice']}"))
    assert detail["student"] == {"id": course.ids["Alice"], "name": "Alice", "is_test": False, "withdrawn": False}
    assert detail["version_number"] == 1 and detail["steps"]["lab"]["completed"] is True
    assert [a["question_key"] for a in detail["attempts"]] == ["q_pick", "q_free", "q_check", "q_extra"]
    assert detail["commitments"][0]["after_final_seen"] is False
    assert env.client.get(f"{base}/students/99999").status_code == 404
    other = _course(env, "OTHER", [("300000001", "Zed", False)])
    assert env.client.get(f"{base}/students/{other.ids['Zed']}").status_code == 404
    assert env.client.get(f"{_base(other)}/{course.lesson['id']}/insights").status_code == 404


def test_course_page_lists_published_lessons(env):
    course = _course(env, "AI", [("100000001", "Alice", False)])
    home = f"/api/r/{course.tokens['Alice']}"
    assert _ok(env.client.get(home))["lessons"] == []
    summary = _install(env, course)
    assert _ok(env.client.get(home))["lessons"] == []
    _publish(env, course, summary)
    assert _ok(env.client.get(home))["lessons"] == [
        {**_LINK, "status": "not_started", "required_done": 0, "required_total": _REQUIRED}
    ]
    # The course page reports the same progress as the lesson list, so it can
    # point a student at a lesson in progress.
    alice = _browser(env, course, "Alice")
    _ok(alice.progress({"expected_revision": 0, "viewed_add": ["intro"]}))
    listed = _ok(alice.call("GET"))["lessons"][0]
    assert _ok(env.client.get(home))["lessons"] == [
        {k: listed[k] for k in ("slug", "title", "status", "required_done", "required_total")}
    ]
    assert listed["status"] == "in_progress"


def test_course_page_survives_a_database_without_the_lesson_tables(env):
    """Code deployed before migration 0021: the course page (peer review,
    teams, grades) still works and just lists no lessons."""
    from app.api import student_review

    course = _course(env, "AI", [("100000001", "Alice", False)])
    with env.Session() as db:
        cascade = " CASCADE" if db.get_bind().dialect.name == "postgresql" else ""
        db.execute(text(f"DROP TABLE lessons{cascade}"))
        db.commit()
    page = _ok(env.client.get(f"/api/r/{course.tokens['Alice']}"))
    assert page["lessons"] == [] and page["student"]["name"] == "Alice"
    with env.Session() as db:
        enrollment = db.scalar(select(Enrollment).where(Enrollment.student_id == course.ids["Alice"]))
        assert student_review._lesson_links(db, enrollment) == []
        assert db.scalar(select(func.count()).select_from(Student)) == 1  # the session is still usable
        db.add(Student(national_id="100000002", name="Bob"))
        db.commit()
        assert db.scalar(select(func.count()).select_from(Student)) == 2


# ---------------------------------------------------------------------------
# Seed command and migration
# ---------------------------------------------------------------------------


def _seed_main():
    sys.path.insert(0, str(BACKEND / "scripts"))
    try:
        import seed_lesson
    finally:
        sys.path.pop(0)
    return seed_lesson.main


def test_seed_script_is_explicit_and_idempotent(env, monkeypatch, capsys):
    course = _course(env, "AI", [("100000001", "Alice", False)])
    other = _course(env, "OTHER", [])
    main = _seed_main()
    monkeypatch.delenv("LESSON_COURSE_ID", raising=False)

    def _seed(*args) -> int:
        return main(["--fixture", "test-lesson", *args], session_factory=env.Session)

    assert _seed() == 2  # no course: refuses
    assert "never guessed" in capsys.readouterr().err
    assert _seed("--course-id", "999") == 2

    assert _seed("--course-id", str(course.id), "--dry-run", "--publish") == 0
    out = capsys.readouterr().out
    assert f"Course {course.id}: code AI, Course AI, 2026 semester A" in out and "create lesson 'test-lesson'" in out
    with env.Session() as db:
        assert f"Database: {db.get_bind().url.render_as_string(hide_password=True)}" in out
    assert "Dry run" in out and _rows(env, Lesson) == 0

    assert _seed("--course-id", str(course.id)) == 0
    assert _seed("--course-id", str(course.id)) == 0
    assert "nothing: lesson 'test-lesson' version 1 already has this content" in capsys.readouterr().out
    with env.Session() as db:
        lesson = db.scalar(select(Lesson))
        assert lesson.status == "draft" and _rows(env, LessonVersion) == 1

    monkeypatch.setenv("LESSON_COURSE_ID", str(course.id))
    assert _seed("--publish") == 0
    assert _seed("--publish") == 0
    assert "already the published version" in capsys.readouterr().out
    with env.Session() as db:
        lesson = db.scalar(select(Lesson))
        assert lesson.status == "published" and lesson.active_version_id is not None

    assert _seed("--course-id", str(other.id)) == 1  # fixture is for course AI
    assert "course_mismatch" in capsys.readouterr().err
    bad = sample_content()
    bad["steps"][0]["completion"] = []
    _write_fixture(env, bad)
    assert _seed("--course-id", str(course.id), "--dry-run") == 1
    assert "no completion rules" in capsys.readouterr().err
    for model in LESSON_TABLES[2:]:
        assert _rows(env, model) == 0  # never any student activity
    with env.Session() as db:
        assert db.get(Course, other.id) is not None and db.scalar(select(func.count()).select_from(Lesson)) == 1


def test_migrations_upgrade_downgrade_upgrade(tmp_path):
    env = {**os.environ, "DATABASE_URL": f"sqlite:///{tmp_path / 'migrate.sqlite3'}"}

    def alembic(*args):
        res = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        return res

    alembic("upgrade", "head")
    alembic("downgrade", "-1")
    alembic("upgrade", "head")
    assert "0024_lessons" in alembic("current").stdout
