"""The course plan (13 draft lessons from the 42052 handoff, the schedule,
readiness) and private answer keys: kept out of the repository, loaded into
the database, and never sent to a student before an answer.

Every key here is FAKE, made by a rule: the last option is "correct" and the
feedback says FAKE. They say nothing about the real answers.
"""

from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path

import pytest
from lesson_samples import sample_content
from sqlalchemy import func, select
from test_lessons import Browser, _code, _course, _ok, _rid, env  # noqa: F401  (env is a fixture)

from app.lessons import FIXTURES, PLANS, assets_root, course_plan, load_fixture, load_plan, validate_content
from app.models.entities import Course, Lesson, LessonAnswerKey, LessonVersion
from app.core.config import get_settings
from app.services import lessons as lessons_svc
from app.services import student_session

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
HANDOFF = REPO / "content" / "course-42052"
FAKE = "FAKE-FEEDBACK-not-a-real-key"
FAKE_EMAIL = "fake-instructor@example.invalid"
PRIVATE_FIELDS = {"answer", "correct_choice_id", "feedback_he", "correct", "misconceptions", "explanation",
                  "sample_reasoning", "rubric", "email"}
PLAN_KEYS = [f"42052-lesson-{n:02d}" for n in range(1, 14)]
# What importing the plan installs, in order: each session's lesson, then its
# optional extra lessons (session 3 has the "go deeper" lesson).
INSTALLED_KEYS = [*PLAN_KEYS[:3], "42052-lesson-03-deeper", *PLAN_KEYS[3:]]
INSTALLED_SLUGS = [k.removeprefix("42052-") for k in INSTALLED_KEYS]


def _choice_keys(fixture_key: str) -> list[str]:
    """The single-choice questions of a fixture: the ones that need a key."""
    return [k for k, q in load_fixture(fixture_key)["questions"].items() if q["type"] == "single_choice"]


# Lessons 3, 4, 5, 6 and 7 are authored in the repository (more checks than their seeds' three).
L03_CHECKS = _choice_keys("42052-lesson-03")
# Session 3 part 2 holds the seed's l03-q1 (the example question several tests use).
D03_CHECKS = _choice_keys("42052-lesson-03-deeper")
L04_CHECKS = _choice_keys("42052-lesson-04")
L05_CHECKS = _choice_keys("42052-lesson-05")
L06_CHECKS = _choice_keys("42052-lesson-06")
L07_CHECKS = _choice_keys("42052-lesson-07")


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, BACKEND / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keys_in(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys_in(v)}
    return set()


def fake_entry(question: dict) -> dict:
    """FAKE: the last option is "correct"."""
    return {"correct_choice_id": question["options"][-1]["id"], "feedback_he": f"{FAKE} {question['key']}"}


def fake_key_file(fixture_keys: list[str], email: bool = True) -> dict:
    lessons: dict[str, dict] = {}
    for key in fixture_keys:
        content = load_fixture(key)
        lessons[content["slug"]] = {
            qkey: fake_entry(q) for qkey, q in content["questions"].items() if q["type"] == "single_choice"
        }
    # The instructor's file's shape: course, a flat instructor_email, lessons.
    data = {"course": "42052", "lessons": lessons}
    if email:
        data["instructor_email"] = FAKE_EMAIL
    return data


# ---------------------------------------------------------------------------
# The repository carries no private field
# ---------------------------------------------------------------------------


def test_repository_carries_no_answer_keys_or_instructor_email():
    """Lesson fixtures, the built plan and the handoff are public: no answer
    key, no correct choice, no private feedback, no email."""
    files = sorted((BACKEND / "app" / "lessons" / "content").rglob("*.json"))
    if HANDOFF.is_dir():
        files += sorted(HANDOFF.rglob("*.json"))
    assert len(files) >= 15
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        leaked = PRIVATE_FIELDS & _keys_in(data)
        assert not leaked, f"{path}: {sorted(leaked)}"
    lesson_2 = load_fixture("lesson-2")
    assert all("answer" not in q for q in lesson_2["questions"].values())


@pytest.mark.skipif(not HANDOFF.is_dir(), reason="the handoff is only in a full checkout")
def test_plan_files_match_the_handoff():
    assert _script("build_course_plan").main(["--check"]) == 0


def test_plan_has_13_sessions_rounds_and_finals_and_no_invented_facts():
    plan = load_plan("42052")
    assert list(PLANS) == ["42052"]
    sessions = plan["sessions"]
    assert [s["session"] for s in sessions] == list(range(1, 14))
    assert [s["fixture_key"] for s in sessions] == PLAN_KEYS
    rounds = {s["session"]: s["presentation_round"] for s in sessions if s["presentation_round"]}
    assert rounds == {2: 1, 3: 1, 4: 2, 5: 2, 6: 3, 7: 3, 8: 4, 9: 4}
    assert {s["session"]: s["final_presentation_part"] for s in sessions if s["final_presentation_part"]} == {12: 1, 13: 2}
    assert not any(s["formal_presentations"] for s in sessions if s["session"] in (1, 10, 11))
    # No field for a fact the handoff leaves open, and no link.
    fields = _keys_in(plan)
    for word in ("date", "time", "room", "deadline", "slot", "team", "weight"):
        assert not [f for f in fields if word in f and f != "planned_presenting_teams"], word
    assert "http" not in json.dumps(plan)
    assert sessions[1]["existing_fixture_keys"] == ["lesson-2"]


@pytest.mark.parametrize("key", PLAN_KEYS)
def test_each_plan_lesson_is_a_valid_keyless_draft(key):
    raw = load_fixture(key)
    content = validate_content(raw, assets_root())
    assert content.course_code == "42052"
    checks = [q for q in raw["questions"].values() if q["type"] == "single_choice"]
    assert all(q["mode"] == "check" for q in checks)  # no reveal before an answer
    # A generated lesson has its seed's three checks; an authored one has at least those.
    seed_checks = load_plan("42052")["lessons"][raw["slug"]]["checks"]
    assert len(seed_checks) == 3
    # A session taught in parts (session 3) spreads its seed's checks across them.
    session = next(s for s in load_plan("42052")["sessions"] if s["fixture_key"] == key)
    in_parts = {q for k in [key, *session["part_fixture_keys"]] for q, v in load_fixture(k)["questions"].items()
                if v["type"] == "single_choice"}
    assert set(seed_checks) <= in_parts
    if raw["slug"] not in course_plan.AUTHORED:
        assert len(checks) == 3
    assert all("answer" not in q for q in raw["questions"].values())
    assert raw["steps"][-1]["key"] == "wrap-up"
    # A homework proposal is not shown to students; it stays in the plan.
    plan = load_plan("42052")["lessons"][raw["slug"]]
    if plan["homework"]["status"] != "existing_assignment":
        assert plan["homework"]["text"] not in json.dumps(raw, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Importing the plan
# ---------------------------------------------------------------------------


@pytest.fixture
def penv(env, monkeypatch):
    """env, with lesson assets checked against the real frontend/public (the
    plan's lessons link prepared files there)."""
    monkeypatch.setattr(lessons_svc, "assets_root", assets_root)
    return env


def _plan_course(env, code="42052"):
    return _course(env, code, [("200000001", "Alice", False), ("200000002", "Bob", False)])


def _import(env, course, **extra):
    return _ok(env.client.post(f"/api/courses/{course.id}/plan/import", json={"plan_code": "42052", **extra}))


def _upload(env, course, data, **params):
    return env.client.post(f"/api/courses/{course.id}/answer-keys", json=data, params=params)


def test_import_plan_installs_13_drafts_and_publishes_nothing(penv):
    env = penv
    course = _plan_course(env)
    result = _import(env, course)
    assert [i["action"] for i in result["installs"]] == ["create"] * len(INSTALLED_KEYS)
    lessons = _ok(env.client.get(f"/api/courses/{course.id}/lessons"))
    assert [l["slug"] for l in lessons] == INSTALLED_SLUGS
    assert all(l["status"] == "draft" and l["active_version"] is None for l in lessons)
    alice = Browser(env.client, course.tokens["Alice"], course.ids["Alice"])
    assert _ok(alice.call("GET"))["lessons"] == []
    assert _code(alice.lesson("lesson-03"), 404) == "lesson_not_found"

    again = _import(env, course)
    assert [i["action"] for i in again["installs"]] == ["unchanged"] * len(INSTALLED_KEYS)
    sessions = again["sessions"]
    assert len(sessions) == 13 and again["plan_code"] == "42052"
    s2 = sessions[1]
    assert (s2["presentation_round"], s2["formal_presentations"], s2["planned_presenting_teams"]) == (1, True, 4)
    assert s2["lesson"]["status"] == "draft" and s2["lesson"]["answer_keys"]["latest"]["missing"] == ["l02-q1", "l02-q2", "l02-q3"]
    # Five states, kept apart.
    ready = sessions[2]["readiness"]
    assert ready["drafted"] is True and ready["reviewed_at"] is None and ready["published"] is False
    assert ready["live_verified_at"] is None and ready["handoff_says_taught"] is False
    assert ready["runnable"]["state"] == "built_not_reviewed" and ready["still_needed"]  # lesson 3: authored here
    four = sessions[3]["readiness"]["runnable"]  # lesson 4: authored here
    assert four["state"] == "built_not_reviewed" and "not run in Antigravity" in four["note"]
    five = sessions[4]["readiness"]["runnable"]  # lesson 5: authored here (template + self-check)
    assert five["state"] == "built_not_reviewed" and "not run" in five["note"]
    six = sessions[5]["readiness"]["runnable"]  # lesson 6: authored here (templates)
    assert six["state"] == "built_not_reviewed" and "not run" in six["note"]
    seven = sessions[6]["readiness"]["runnable"]  # lesson 7: authored here (reference implementation, mock check)
    assert seven["state"] == "built_not_reviewed" and "not run with a real key" in seven["note"]
    assert sessions[7]["readiness"]["runnable"]["state"] == "not_built"
    assert sessions[0]["readiness"]["runnable"]["state"] == "prepared_not_rerun"

    marked = _ok(env.client.patch(f"/api/courses/{course.id}/plan/sessions/3", json={"reviewed": True}))
    row = marked["sessions"][2]["readiness"]
    assert row["reviewed_at"] and row["published"] is False and row["live_verified_at"] is None
    assert _import(env, course)["sessions"][2]["readiness"]["reviewed_at"] == row["reviewed_at"]  # kept on re-import
    cleared = _ok(env.client.patch(f"/api/courses/{course.id}/plan/sessions/3", json={"reviewed": False}))
    assert cleared["sessions"][2]["readiness"]["reviewed_at"] is None
    assert _code(env.client.patch(f"/api/courses/{course.id}/plan/sessions/99", json={"reviewed": True}), 404) == "session_not_found"


def test_import_plan_refuses_another_course_unless_confirmed(penv):
    env = penv
    course = _plan_course(env, code="OTHER")
    assert _code(env.client.post(f"/api/courses/{course.id}/plan/import", json={"plan_code": "42052"}), 409) == "course_mismatch"
    assert _code(env.client.post(f"/api/courses/{course.id}/plan/import", json={"plan_code": "nope"}), 404) == "unknown_plan"
    assert len(_import(env, course, allow_course_mismatch=True)["sessions"]) == 13


# ---------------------------------------------------------------------------
# Loading keys
# ---------------------------------------------------------------------------


def _stored(env) -> int:
    with env.Session() as db:
        return db.scalar(select(func.count()).select_from(LessonAnswerKey))


def test_key_upload_is_validated_all_or_nothing(penv):
    env = penv
    course = _plan_course(env)
    _import(env, course)
    good = fake_key_file(["42052-lesson-03"])
    bad = json.loads(json.dumps(good))
    bad["lessons"]["lesson-03"]["l03-q2"]["correct_choice_id"] = "99"
    bad["lessons"]["lesson-04"] = {"l04-q9": {"correct_choice_id": "1"}}
    bad["lessons"]["no-such-lesson"] = {"q": {"correct_choice_id": "1"}}
    bad["instructor_email"] = "not an email"
    res = _upload(env, course, bad)
    detail = res.json()["detail"]
    assert res.status_code == 422 and detail["code"] == "invalid_answer_keys"
    assert set(detail["errors"]) == {
        "instructor email: not an email address",
        "lessons.lesson-03.l03-q2: correct is not one of the question's options",
        "lessons.lesson-04.l04-q9: lesson 'lesson-04' has no question 'l04-q9'",
        "lessons.no-such-lesson.q: no lesson 'no-such-lesson' in course 42052",
    }
    assert FAKE not in res.text
    # Paths only: no submitted value comes back.
    assert "'99'" not in res.text and "99999" not in res.text
    assert _stored(env) == 0
    with env.Session() as db:
        assert db.get(Course, course.id).instructor_email is None

    other = dict(good, course="99999")
    res = _upload(env, course, other)
    assert res.json()["detail"]["errors"] == ["course: the file is for another course, not 42052"] and "99999" not in res.text
    for broken in ([], {"lessons": {"lesson-03": {"l03-q1": {"correct_choice_id": 2}}}}, {"surprise": 1},
                   {"course_code": "42052", "lessons": {}}, {"instructor": {"email": FAKE_EMAIL}},
                   {"checks": [{"lesson_slug": "lesson-03", "check_key": "l03-q1", "correct_choice_id": "1"}]},
                   {"lessons": {"lesson-03": {"l03-exit": {"correct_choice_id": "1"}}}}):
        assert _upload(env, course, broken).status_code == 422
    assert _stored(env) == 0


def test_key_upload_shapes_dry_run_and_status_never_return_a_key(penv):
    env = penv
    course = _plan_course(env)
    _import(env, course)
    data = fake_key_file(["42052-lesson-03"])
    dry = _ok(_upload(env, course, data, dry_run=True))
    n = len(L03_CHECKS)
    assert (dry["keys"], dry["added"], dry["dry_run"], dry["instructor_contact"]) == (n, n, True, "set")
    assert _stored(env) == 0

    first = _ok(_upload(env, course, data))
    assert (first["added"], first["lessons"], first["instructor_contact"]) == (n, ["lesson-03"], "set")
    # Left out of the file: reported, not refused; the other plan lessons by slug.
    assert first["not_in_file"] == [f"lesson-{n:02d}" for n in range(1, 14) if n != 3]
    again = _ok(_upload(env, course, data))
    assert (again["unchanged"], again["instructor_contact"]) == (n, "unchanged")

    # feedback_he is one text; a lesson given in part is reported.
    q = load_fixture("42052-lesson-04")["questions"]["l04-q1"]
    per_option = {"lessons": {"lesson-04": {"l04-q1": {
        "correct_choice_id": q["options"][-1]["id"], "feedback_he": {o["id"]: FAKE for o in q["options"]}}}}}
    assert _upload(env, course, per_option).json()["detail"]["errors"] == ["lessons.lesson-04.l04-q1: feedback_he must be a text"]
    partial = {"lessons": {"lesson-04": {"l04-q1": fake_entry(q)}}}
    result = _ok(_upload(env, course, partial))
    assert result["added"] == 1 and {"lesson-04/l04-q2", "lesson-04/l04-q3"} <= set(result["not_in_file"])
    assert "lesson-04/l04-q1" not in result["not_in_file"]

    status = env.client.get(f"/api/courses/{course.id}/answer-keys")
    body = _ok(status)
    assert body["stored_keys"] == n + 1 and body["instructor_contact_set"] is True
    l03 = next(l for l in body["lessons"] if l["slug"] == "lesson-03")
    assert l03["latest"] == {"version_number": 1, "needed": n, "missing": [], "mismatched": []}
    for res in (status, env.client.get(f"/api/courses/{course.id}/plan"), env.client.get(f"/api/courses/{course.id}/lessons")):
        assert FAKE not in res.text and FAKE_EMAIL not in res.text
    with env.Session() as db:
        assert db.get(Course, course.id).instructor_email == FAKE_EMAIL


def test_the_whole_plan_file_loads_13_lessons_and_every_check(penv):
    """A file of the instructor's shape covering every plan check (FAKE values)."""
    env = penv
    course = _plan_course(env)
    _import(env, course)
    data = fake_key_file(INSTALLED_KEYS)
    total = sum(len(_choice_keys(k)) for k in INSTALLED_KEYS)  # three per generated lesson, more in an authored one
    assert total == 24 + len(L03_CHECKS) + len(_choice_keys("42052-lesson-03-deeper")) + len(L04_CHECKS) + len(L05_CHECKS) + len(L06_CHECKS) + len(L07_CHECKS)
    assert sum(len(v) for v in data["lessons"].values()) == total and len(data["lessons"]) == 14
    result = _ok(_upload(env, course, data))
    assert (result["keys"], result["added"], result["not_in_file"], result["instructor_contact"]) == (total, total, [], "set")
    status = _ok(env.client.get(f"/api/courses/{course.id}/answer-keys"))
    assert all(l["latest"]["missing"] == [] for l in status["lessons"])


def test_a_stored_key_that_no_longer_fits_a_revised_version_blocks_publishing(penv, tmp_path, monkeypatch):
    """Reed's repro: keys loaded and v1 published, then l03-q1 loses the
    option its key marks right and v2 is installed. Publishing v2 is refused
    (never "every answer wrong"), the status names the mismatch, and the key
    is never applied to v2."""
    env = penv
    course = _plan_course(env)
    _import(env, course)
    base = f"/api/courses/{course.id}/lessons"
    lesson = next(l for l in _ok(env.client.get(base)) if l["slug"] == "lesson-03-deeper")
    _ok(_upload(env, course, fake_key_file(["42052-lesson-03-deeper"])))  # FAKE: l03-q1's right option is "3"
    _ok(env.client.post(f"{base}/{lesson['id']}/publish", json={"version_id": lesson["draft_version"]["id"]}))

    revised = load_fixture("42052-lesson-03-deeper")
    revised["questions"]["l03-q1"]["options"] = [o for o in revised["questions"]["l03-q1"]["options"] if o["id"] != "3"]
    fixture = tmp_path / "lesson-03-deeper.json"
    fixture.write_text(json.dumps(revised, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(FIXTURES, "42052-lesson-03-deeper", fixture)
    v2 = _ok(env.client.post(f"{base}/install", json={"fixture_key": "42052-lesson-03-deeper"}))
    assert v2["answer_keys"]["latest"]["mismatched"] == ["l03-q1"]
    assert v2["answer_keys"]["latest"]["missing"] == ["l03-q1"]  # no usable key
    assert v2["answer_keys"]["live"] == {"version_number": 1, "needed": len(D03_CHECKS), "missing": [], "mismatched": []}

    res = env.client.post(f"{base}/{lesson['id']}/publish", json={"version_id": v2["draft_version"]["id"]})
    assert _code(res, 422) == "answer_key_mismatch" and res.json()["detail"]["questions"] == ["l03-q1"]
    assert FAKE not in res.text
    # The preview never checks against the stale key either.
    evaluated = _ok(env.client.post(f"{base}/{lesson['id']}/preview/evaluate",
                                    json={"version_id": v2["draft_version"]["id"], "question_key": "l03-q1", "answer": {"choice": "1"}}))
    assert evaluated["feedback"] == {"correct": None}

    # A corrected key fits v2; v1 (which had option 3) still fits it too here.
    fixed = {"lessons": {"lesson-03-deeper": {"l03-q1": {"correct_choice_id": "2", "feedback_he": FAKE}}}}
    result = _ok(_upload(env, course, fixed))
    assert result["replaced"] == 1 and result["older_versions_not_fitting"] == []
    _ok(env.client.post(f"{base}/{lesson['id']}/publish", json={"version_id": v2["draft_version"]["id"]}))


def test_keys_that_would_break_a_published_version_are_refused_unless_confirmed(penv, tmp_path, monkeypatch):
    """Reed's N2: a key that fits the latest version (here, a new option 9 in
    draft v2) but not the published v1 would leave v1's students unchecked.
    The dry run reports it; storing is refused with nothing saved; only an
    explicit confirmation stores it. Paths only, never values."""
    env = penv
    course = _plan_course(env)
    _import(env, course)
    base = f"/api/courses/{course.id}/lessons"
    lesson = next(l for l in _ok(env.client.get(base)) if l["slug"] == "lesson-04")
    _ok(_upload(env, course, fake_key_file(["42052-lesson-04"])))
    _ok(env.client.post(f"{base}/{lesson['id']}/publish", json={"version_id": lesson["draft_version"]["id"]}))
    revised = load_fixture("42052-lesson-04")
    revised["questions"]["l04-q1"]["options"].append({"id": "9", "text": "אפשרות חדשה"})
    fixture = tmp_path / "lesson-04.json"
    fixture.write_text(json.dumps(revised, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(FIXTURES, "42052-lesson-04", fixture)
    _ok(env.client.post(f"{base}/install", json={"fixture_key": "42052-lesson-04"}))  # draft v2 has option 9

    def stored_key():
        with env.Session() as db:
            row = db.scalar(select(LessonAnswerKey).where(LessonAnswerKey.lesson_slug == "lesson-04",
                                                          LessonAnswerKey.question_key == "l04-q1"))
            return row.answer_json

    before = stored_key()
    new_option = {"lessons": {"lesson-04": {"l04-q1": {"correct_choice_id": "9", "feedback_he": FAKE}}}}
    dry = _ok(_upload(env, course, new_option, dry_run=True))
    assert dry["older_versions_not_fitting"] == ["lesson-04/l04-q1 (version 1)"]
    assert dry["published_versions_not_fitting"] == ["lesson-04/l04-q1 (version 1)"]

    refused = _upload(env, course, new_option)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["code"] == "breaks_published_version"
    assert detail["published_versions_not_fitting"] == ["lesson-04/l04-q1 (version 1)"]
    assert FAKE not in refused.text and '"9"' not in refused.text
    assert stored_key() == before  # nothing saved
    live = next(l for l in _ok(env.client.get(base)) if l["slug"] == "lesson-04")["answer_keys"]["live"]
    assert live["missing"] == [] and live["mismatched"] == []  # the live version still checks every question

    stored = _ok(_upload(env, course, new_option, confirm_published_breaks=True))
    assert stored["replaced"] == 1 and stored["published_versions_not_fitting"] == ["lesson-04/l04-q1 (version 1)"]
    live = next(l for l in _ok(env.client.get(base)) if l["slug"] == "lesson-04")["answer_keys"]["live"]
    assert live["mismatched"] == ["l04-q1"]  # what the instructor confirmed, shown on the card

    gone = {"lessons": {"lesson-04": {"l04-q1": {"correct_choice_id": "7", "feedback_he": FAKE}}}}
    assert _upload(env, course, gone, confirm_published_breaks=True).status_code == 422  # must fit the latest version


def test_an_unpublished_older_version_is_only_reported(penv, tmp_path, monkeypatch):
    env = penv
    course = _plan_course(env)
    _import(env, course)  # v1 of lesson-05 stays a draft
    revised = load_fixture("42052-lesson-05")
    revised["questions"]["l05-q1"]["options"].append({"id": "9", "text": "אפשרות חדשה"})
    revised["intro"] = "גרסה שנייה"
    fixture = tmp_path / "lesson-05.json"
    fixture.write_text(json.dumps(revised, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(FIXTURES, "42052-lesson-05", fixture)
    _ok(env.client.post(f"/api/courses/{course.id}/lessons/install", json={"fixture_key": "42052-lesson-05"}))
    result = _ok(_upload(env, course, {"lessons": {"lesson-05": {"l05-q1": {"correct_choice_id": "9", "feedback_he": FAKE}}}}))
    # The draft was updated in place (no published version to protect): nothing to report.
    assert result["added"] == 1 and result["published_versions_not_fitting"] == []


def test_instructor_routes_need_the_token_when_one_is_configured(penv):
    env = penv
    course = _plan_course(env)
    settings = get_settings()
    original = settings.instructor_token
    settings.instructor_token = "test-instructor-token"
    try:
        routes = [
            ("GET", f"/api/courses/{course.id}/plan", None),
            ("POST", f"/api/courses/{course.id}/plan/import", {"plan_code": "42052"}),
            ("PATCH", f"/api/courses/{course.id}/plan/sessions/1", {"reviewed": True}),
            ("GET", f"/api/courses/{course.id}/answer-keys", None),
            ("POST", f"/api/courses/{course.id}/answer-keys", fake_key_file(["42052-lesson-03"])),
        ]
        student = {"Cookie": f"{student_session.COOKIE_NAME}={student_session.issue(course.ids['Alice'])}", "X-CG-Student": "1"}
        for method, path, body in routes:
            for headers in ({}, student, {"X-Instructor-Token": "wrong"}):
                res = env.client.request(method, path, json=body, headers=headers)
                assert res.status_code == 401, (method, path, headers)
                assert FAKE not in res.text
        assert _stored(env) == 0
        token = {"X-Instructor-Token": "test-instructor-token"}
        statuses = [env.client.request(m, p, json=b, headers=token).status_code for m, p, b in routes]
        assert statuses[:2] == [200, 200] and statuses[3:] == [200, 200]
        assert statuses[2] == 200  # the session exists once the plan is imported
    finally:
        settings.instructor_token = original


def test_publishing_needs_keys_and_the_preview_warns_the_instructor(penv):
    env = penv
    course = _plan_course(env)
    _import(env, course)
    lesson = next(l for l in _ok(env.client.get(f"/api/courses/{course.id}/lessons")) if l["slug"] == "lesson-03-deeper")
    base = f"/api/courses/{course.id}/lessons/{lesson['id']}"
    preview = _ok(env.client.get(f"{base}/preview"))
    assert preview["missing_answer_keys"] == D03_CHECKS
    evaluated = _ok(env.client.post(f"{base}/preview/evaluate", json={"question_key": "l03-q1", "answer": {"choice": "1"}}))
    assert evaluated["feedback"] == {"correct": None}  # nothing to check against
    res = env.client.post(f"{base}/publish", json={"version_id": lesson["draft_version"]["id"]})
    assert _code(res, 422) == "missing_answer_keys" and res.json()["detail"]["questions"] == D03_CHECKS

    _ok(_upload(env, course, fake_key_file(["42052-lesson-03-deeper"])))
    assert _ok(env.client.get(f"{base}/preview"))["missing_answer_keys"] == []
    q = load_fixture("42052-lesson-03-deeper")["questions"]["l03-q1"]
    right = q["options"][-1]["id"]
    evaluated = _ok(env.client.post(f"{base}/preview/evaluate", json={"question_key": "l03-q1", "answer": {"choice": right}}))
    assert evaluated["feedback"] == {"correct": True, "explanation": f"{FAKE} l03-q1", "correct_options": [right]}
    assert _ok(env.client.post(f"{base}/publish", json={"version_id": lesson["draft_version"]["id"]}))["status"] == "published"


# ---------------------------------------------------------------------------
# Nothing private reaches a student before an answer
# ---------------------------------------------------------------------------


def _assert_clean(res, *, before_answer: bool = True):
    assert res.status_code < 500, res.text
    assert FAKE_EMAIL not in res.text
    assert "correct_choice_id" not in res.text and "feedback_he" not in res.text
    if before_answer:
        assert FAKE not in res.text and "correct_options" not in res.text


def test_student_endpoints_never_return_keys_before_an_answer(penv):
    env = penv
    course = _plan_course(env)
    _import(env, course)
    _ok(_upload(env, course, fake_key_file(INSTALLED_KEYS)))
    lesson = next(l for l in _ok(env.client.get(f"/api/courses/{course.id}/lessons")) if l["slug"] == "lesson-03-deeper")
    _ok(env.client.post(f"/api/courses/{course.id}/lessons/{lesson['id']}/publish", json={"version_id": lesson["draft_version"]["id"]}))
    alice = Browser(env.client, course.tokens["Alice"], course.ids["Alice"])
    bob = Browser(env.client, course.tokens["Bob"], course.ids["Bob"])
    cookie = {"Cookie": f"{student_session.COOKIE_NAME}={student_session.issue(course.ids['Alice'])}"}

    # The course page (/api/r/<token>), the lesson list, the lesson itself.
    _assert_clean(env.client.get(f"/api/r/{course.tokens['Alice']}", headers=cookie))
    _assert_clean(env.client.get("/api/student-auth/me", headers=cookie))
    _assert_clean(alice.call("GET"))
    payload = alice.lesson("lesson-03-deeper")
    _assert_clean(payload)
    body = payload.json()
    assert not PRIVATE_FIELDS & _keys_in(body["content"])
    assert all(state["feedback"] is None for state in body["questions"].values())

    # Every write a student can make, before answering the question.
    reveal = alice.call("POST", "/lesson-03-deeper/questions/l03-q1/reveal", json={"request_id": _rid()})
    assert _code(reveal, 409) == "answer_first"  # check mode: no reveal before an answer
    _assert_clean(reveal)
    _assert_clean(alice.progress({"expected_revision": 0, "current_step_key": "tokens", "viewed_add": ["tokens"]}, slug="lesson-03-deeper"))
    run = "6f1d3c2a-1b2c-4d3e-8f9a-0b1c2d3e4f5a"
    exp = alice.call("PUT", f"/lesson-03-deeper/experiments/{run}", json={
        "expected_revision": None, "depth_kind": None, "depth": None, "training_examples": None,
        "train_accuracy_pct": None, "validation_accuracy_pct": None, "baseline_validation_pct": None,
        "hypothesis": "A guess.", "observation": "", "explanation": ""})
    _assert_clean(exp)
    _assert_clean(alice.call("DELETE", f"/lesson-03-deeper/experiments/{run}", params={"expected_revision": 1}))
    commit = alice.call("POST", "/lesson-03-deeper/commitments", json={
        "request_id": _rid(), "run_uuid": None, "depth_kind": "limited", "depth": 3,
        "training_examples": 100, "justification": "Chosen for the test."})
    _assert_clean(commit)
    final = alice.call("PATCH", f"/lesson-03-deeper/commitments/{commit.json()['commitments'][0]['id']}/final",
                       json={"final_accuracy_pct": 70, "final_precision_pct": None, "final_recall_pct": None, "final_note": ""})
    _assert_clean(final)
    _assert_clean(alice.answer("l03-q1", {"choice": "nope"}, slug="lesson-03-deeper"))  # invalid: not an answer

    # After answering: feedback for that question only, never the email.
    q1 = load_fixture("42052-lesson-03-deeper")["questions"]["l03-q1"]
    wrong = q1["options"][0]["id"]
    answered = alice.answer("l03-q1", {"choice": wrong}, slug="lesson-03-deeper")
    _assert_clean(answered, before_answer=False)
    feedback = answered.json()["question"]["feedback"]
    assert feedback == {"correct": False, "explanation": f"{FAKE} l03-q1", "correct_options": [q1["options"][-1]["id"]]}
    after = alice.lesson("lesson-03-deeper")
    _assert_clean(after, before_answer=False)
    states = after.json()["questions"]
    assert states["l03-q1"]["feedback"]["correct"] is False
    assert all(states[k]["feedback"] is None for k in ("l03-tokens-ratio", "l03-q3", "lesson-03-deeper-exit"))
    assert FAKE + " l03-tokens-ratio" not in after.text and not PRIVATE_FIELDS & _keys_in(after.json()["content"])
    # Another student who hasn't answered gets nothing.
    _assert_clean(bob.lesson("lesson-03-deeper"))
    _assert_clean(env.client.get(f"/api/r/{course.tokens['Alice']}", headers=cookie), before_answer=False)
    # The instructor's "view as student" shows the student page, not the keys.
    _assert_clean(env.client.get(f"/api/courses/{course.id}/peer/student-view/{course.ids['Bob']}"))


# ---------------------------------------------------------------------------
# Lesson 2: keys moved from the fixture into the database
# ---------------------------------------------------------------------------


def test_lesson_2_installs_without_keys_and_publishes_once_they_are_loaded(penv):
    env = penv
    course = _plan_course(env)
    lesson = _ok(env.client.post(f"/api/courses/{course.id}/lessons/install", json={"fixture_key": "lesson-2"}))
    missing = lesson["answer_keys"]["latest"]["missing"]
    assert len(missing) == lesson["answer_keys"]["latest"]["needed"] == 14
    base = f"/api/courses/{course.id}/lessons/{lesson['id']}"
    assert _code(env.client.post(f"{base}/publish", json={"version_id": lesson["draft_version"]["id"]}), 422) == "missing_answer_keys"
    _ok(_upload(env, course, fake_key_file(["lesson-2"], email=False)))
    published = _ok(env.client.post(f"{base}/publish", json={"version_id": lesson["draft_version"]["id"]}))
    assert published["answer_keys"]["live"]["missing"] == []
    alice = Browser(env.client, course.tokens["Alice"], course.ids["Alice"])
    q = load_fixture("lesson-2")["questions"]["q_target"]
    state = _ok(alice.answer("q_target", {"choice": q["options"][-1]["id"]}, slug="from-data-to-prediction"))["question"]
    assert state["feedback"]["correct"] is True and state["feedback"]["explanation"] == f"{FAKE} q_target"


def test_a_version_that_embeds_its_keys_keeps_working_beside_database_keys(env):
    """The live lesson 2 was installed with keys inside its version. After the
    keys move out, that version keeps them; the new keyless version publishes
    once the same keys are in the database, and answers to both count as the
    same question."""
    course = _course(env, "AI", [("300000001", "Alice", False), ("300000002", "Bob", False)])
    base = f"/api/courses/{course.id}/lessons"
    v1 = _ok(env.client.post(f"{base}/install", json={"fixture_key": "test-lesson"}))
    _ok(env.client.post(f"{base}/{v1['id']}/publish", json={"version_id": v1["draft_version"]["id"]}))
    alice = Browser(env.client, course.tokens["Alice"], course.ids["Alice"])
    _ok(alice.answer("q_pick", {"choice": "a"}))  # pinned to v1

    embedded = sample_content()
    keys = {k: {"answer": q.pop("answer")} for k, q in embedded["questions"].items()}
    env.fixture.write_text(json.dumps(embedded, ensure_ascii=False), encoding="utf-8")
    v2 = _ok(env.client.post(f"{base}/install", json={"fixture_key": "test-lesson"}))
    assert [v["number"] for v in v2["versions"]] == [1, 2]
    assert v2["answer_keys"]["latest"]["missing"] == ["q_pick", "q_check", "q_extra"]
    assert v2["answer_keys"]["live"]["missing"] == []  # v1 embeds its keys
    publish = env.client.post(f"{base}/{v1['id']}/publish", json={"version_id": v2["draft_version"]["id"]})
    assert _code(publish, 422) == "missing_answer_keys"

    _ok(_upload(env, course, {"lessons": {embedded["slug"]: keys}}))
    _ok(env.client.post(f"{base}/{v1['id']}/publish", json={"version_id": v2["draft_version"]["id"]}))
    bob = Browser(env.client, course.tokens["Bob"], course.ids["Bob"])
    bob_state = _ok(bob.answer("q_pick", {"choice": "a"}))["question"]
    alice_state = _ok(alice.answer("q_pick", {"choice": "a"}))["question"]
    assert bob_state["feedback"] == alice_state["feedback"] and bob_state["feedback"]["correct"] is True
    with env.Session() as db:
        versions = {v.id: v.number for v in db.scalars(select(LessonVersion))}
        assert len(versions) == 2
    insights = _ok(env.client.get(f"{base}/{v1['id']}/insights"))
    pick = next(q for q in insights["questions"] if q["key"] == "q_pick")
    assert pick["other_version_answers"] == 0  # same question, key included, in both versions


# ---------------------------------------------------------------------------
# Scripts: one-time export, local load
# ---------------------------------------------------------------------------


def test_export_script_writes_a_private_file_and_refuses_a_tracked_path(tmp_path, capsys):
    export = _script("export_lesson_answer_keys")
    source = tmp_path / "old-lesson.json"
    source.write_text(json.dumps(sample_content(), ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "keys.json"
    assert export.main(["--from-file", str(source), "--out", str(out)]) == 0
    assert stat.S_IMODE(out.stat().st_mode) == 0o600
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["course"] == "AI" and set(data["lessons"]["test-lesson"]) == {"q_pick", "q_free", "q_check", "q_extra"}
    assert "correct" not in capsys.readouterr().out  # counts only
    assert export.main(["--from-file", str(source), "--out", str(out)]) == 2  # no silent overwrite

    # The default output is gitignored; a path git would track is refused.
    assert not export.tracked_by_git(export.PRIVATE_DIR / "from-data-to-prediction.answer-keys.json")
    assert not export.tracked_by_git(REPO / "backend" / "anything.answer-keys.json")
    tracked = REPO / "backend" / "leaked-keys.json"
    assert export.tracked_by_git(tracked)
    assert export.main(["--from-file", str(source), "--out", str(tracked)]) == 2
    assert not tracked.exists()
    keyless = tmp_path / "keyless.json"
    keyless.write_text(json.dumps(load_fixture("lesson-2"), ensure_ascii=False), encoding="utf-8")
    assert export.main(["--from-file", str(keyless), "--out", str(tmp_path / "none.json")]) == 1


def test_load_script_stores_keys_in_the_chosen_course(penv, tmp_path, capsys, monkeypatch):
    env = penv
    course = _plan_course(env)
    _import(env, course)
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps(fake_key_file(["42052-lesson-08"])), encoding="utf-8")
    load = _script("load_answer_keys")
    assert load.main(["--course-id", str(course.id), "--file", str(keys), "--dry-run"], env.Session) == 0
    assert _stored(env) == 0
    assert load.main(["--course-id", str(course.id), "--file", str(keys)], env.Session) == 0
    out = capsys.readouterr().out
    assert "Stored 3 key(s) for 1 lesson(s): 3 new" in out and FAKE not in out and FAKE_EMAIL not in out
    with env.Session() as db:
        assert {r.source for r in db.scalars(select(LessonAnswerKey))} == {"script"}
        lesson = db.scalar(select(Lesson).where(Lesson.slug == "lesson-08"))
        assert lesson.status == "draft"  # loading keys publishes nothing
    assert load.main(["--course-id", "999", "--file", str(keys)], env.Session) == 2
    # A key a published version can't use: listed by path, refused without the flag.
    lesson = next(l for l in _ok(env.client.get(f"/api/courses/{course.id}/lessons")) if l["slug"] == "lesson-08")
    _ok(env.client.post(f"/api/courses/{course.id}/lessons/{lesson['id']}/publish", json={"version_id": lesson["draft_version"]["id"]}))
    revised = load_fixture("42052-lesson-08")
    revised["questions"]["l08-q1"]["options"].append({"id": "9", "text": "אפשרות חדשה"})
    fixture = tmp_path / "lesson-08.json"
    fixture.write_text(json.dumps(revised, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setitem(FIXTURES, "42052-lesson-08", fixture)
    _ok(env.client.post(f"/api/courses/{course.id}/lessons/install", json={"fixture_key": "42052-lesson-08"}))
    breaking = tmp_path / "breaking.json"
    breaking.write_text(json.dumps({"lessons": {"lesson-08": {"l08-q1": {"correct_choice_id": "9", "feedback_he": FAKE}}}}), encoding="utf-8")
    capsys.readouterr()
    assert load.main(["--course-id", str(course.id), "--file", str(breaking), "--dry-run"], env.Session) == 0
    out = capsys.readouterr().out
    assert "lesson-08/l08-q1 (version 1)" in out and "published" in out and FAKE not in out
    assert load.main(["--course-id", str(course.id), "--file", str(breaking)], env.Session) == 3
    err = capsys.readouterr().err
    assert "lesson-08/l08-q1 (version 1)" in err and "--confirm-published-breaks" in err and FAKE not in err
    assert load.main(["--course-id", str(course.id), "--file", str(breaking), "--confirm-published-breaks"], env.Session) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"lessons": {"lesson-08": {"l08-q1": {"correct_choice_id": "99"}}}}), encoding="utf-8")
    assert load.main(["--course-id", str(course.id), "--file", str(bad)], env.Session) == 1


def test_every_plan_fixture_is_registered():
    assert set(INSTALLED_KEYS) <= set(FIXTURES)


def test_migration_0026_round_trips(tmp_path):
    """0026 upgrades, downgrades to 0025 and upgrades again, on SQLite and (when
    TEST_DATABASE_URL is set) on Postgres; it only adds."""
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine, inspect, text

    from app.core.config import sqlalchemy_database_url

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
            res = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)
            assert res.returncode == 0, res.stderr
            return res.stdout

        def tables():
            engine = create_engine(sqlalchemy_database_url(url))
            try:
                found = inspect(engine)
                return set(found.get_table_names()), {c["name"] for c in found.get_columns("courses")}
            finally:
                engine.dispose()

        alembic("upgrade", "0025_custom_rubrics")
        before_tables, before_columns = tables()
        alembic("upgrade", "head")
        assert "0026_course_plan_answer_keys (head)" in alembic("current")
        after_tables, after_columns = tables()
        assert after_tables - before_tables == {"lesson_answer_keys", "course_plan_sessions"}
        assert after_columns - before_columns == {"instructor_email"} and before_columns <= after_columns
        alembic("downgrade", "0025_custom_rubrics")
        assert tables() == (before_tables, before_columns)
        alembic("upgrade", "head")
        assert "0026_course_plan_answer_keys (head)" in alembic("current")
