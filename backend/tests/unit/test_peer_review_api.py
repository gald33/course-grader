from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import (
    Enrollment,
    PeerReview,
    Presentation,
    PresentationMove,
    ReviewRound,
    Student,
)
from app.services import llm_peer_review

STUDENTS = {
    "a1": ("100000001", "Alice Avraham"),
    "a2": ("100000002", "Amir Agmon"),
    "b1": ("200000001", "Bella Ben-David"),
    "b2": ("200000002", "Boaz Barak"),
    "c1": ("300000001", "Carmel Cohen"),
    "c2": ("300000002", "Chen Carmi"),
}
GOOD = {"final_score": 4, "problem_clarity": 4, "usefulness": 4, "functionality": 3, "testing": 3}
TEXT = {"worked_well": "Clear demo", "improvement": "Add user testing"}


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


@pytest.fixture
def course(env):
    """Course with 3 teams x 2 students, default schedule, links generated."""
    c = env.client
    course_id = _ok(c.post("/api/courses", json={"code": "AI", "name": "AI Products", "year": 2026, "semester": "A"}))["id"]
    with env.Session() as db:
        ids = {}
        for key, (nid, name) in STUDENTS.items():
            s = Student(national_id=nid, name=name)
            db.add(s)
            db.flush()
            db.add(Enrollment(course_id=course_id, student_id=s.id))
            ids[key] = s.id
        db.commit()
    teams = {}
    for name in ("A", "B", "C"):
        teams[name] = _ok(c.post(f"/api/courses/{course_id}/peer/teams", json={"name": f"Team {name}", "project_title": f"Project {name}"}))["id"]
    for key, sid in ids.items():
        _ok(c.put(f"/api/courses/{course_id}/peer/students/{sid}/team", json={"team_id": teams[key[0].upper()]}))
    _ok(c.post(f"/api/courses/{course_id}/peer/setup"))
    _ok(c.post(f"/api/courses/{course_id}/peer/links/generate"))
    links = {row["student_id"]: row["token"] for row in _ok(c.get(f"/api/courses/{course_id}/peer/links"))}
    tokens = {key: links[sid] for key, sid in ids.items()}
    overview = _ok(c.get(f"/api/courses/{course_id}/peer/overview"))
    round1 = next(r for r in overview["rounds"] if r["number"] == 1)
    pres = {p["team_name"][-1]: p["id"] for p in round1["presentations"]}
    return SimpleNamespace(id=course_id, students=ids, teams=teams, tokens=tokens, round_id=round1["id"], pres=pres)


def _base(course) -> str:
    return f"/api/courses/{course.id}/peer"


def _schedule_and_open(env, course):
    """A and B present in session 2, C in session 3; reviewing open for session 2."""
    c = env.client
    _ok(c.post(f"{_base(course)}/rounds/{course.round_id}/actions/open-selection"))
    _ok(c.put(f"/api/r/{course.tokens['a1']}/presentations/{course.pres['A']}/session", json={"session_number": 2}))
    _ok(c.put(f"/api/r/{course.tokens['b2']}/presentations/{course.pres['B']}/session", json={"session_number": 2}))
    _ok(c.patch(f"{_base(course)}/presentations/{course.pres['C']}", json={"move": True, "session_number": 3, "reason": "setup"}))
    _ok(c.post(f"{_base(course)}/rounds/{course.round_id}/actions/open-reviewing"))
    _ok(c.post(f"{_base(course)}/rounds/{course.round_id}/sessions/2/reviewing", json={"open": True}))


def _review(env, course, who, team, scores=GOOD, responses=TEXT):
    return env.client.put(
        f"/api/r/{course.tokens[who]}/reviews/{course.pres[team]}",
        json={"scores": scores, "responses": responses},
    )


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def test_volunteering_capacity_and_random_assignment(env, course):
    c = env.client
    base = _base(course)
    _ok(c.patch(f"{base}/rounds/{course.round_id}", json={"sessions": [{"number": 2, "capacity": 1}, {"number": 3, "capacity": 4}]}))
    # Not open yet
    res = c.put(f"/api/r/{course.tokens['a1']}/presentations/{course.pres['A']}/session", json={"session_number": 2})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "selection_closed"

    _ok(c.post(f"{base}/rounds/{course.round_id}/actions/open-selection"))
    _ok(c.put(f"/api/r/{course.tokens['a1']}/presentations/{course.pres['A']}/session", json={"session_number": 2}))
    # Only your own team
    res = c.put(f"/api/r/{course.tokens['c1']}/presentations/{course.pres['A']}/session", json={"session_number": 3})
    assert res.status_code == 403 and res.json()["detail"]["code"] == "not_your_team"
    # Session 2 is full
    res = c.put(f"/api/r/{course.tokens['b1']}/presentations/{course.pres['B']}/session", json={"session_number": 2})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "capacity_full"
    # Session outside the round
    res = c.put(f"/api/r/{course.tokens['b1']}/presentations/{course.pres['B']}/session", json={"session_number": 5})
    assert res.json()["detail"]["code"] == "invalid_session"

    result = _ok(c.post(f"{base}/rounds/{course.round_id}/actions/random-assign"))
    assert result == {"status": "ok", "assigned": 2, "left_unassigned": 0}
    overview = _ok(c.get(f"{base}/overview"))
    rnd = next(r for r in overview["rounds"] if r["id"] == course.round_id)
    sessions = {p["team_name"]: p["session_number"] for p in rnd["presentations"]}
    assert sessions == {"Team A": 2, "Team B": 3, "Team C": 3}

    # Selection deadline is enforced
    _ok(c.patch(f"{base}/rounds/{course.round_id}", json={"selection_deadline": (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"}))
    res = c.put(f"/api/r/{course.tokens['a1']}/presentations/{course.pres['A']}/session", json={"session_number": 3})
    assert res.json()["detail"]["code"] == "selection_closed"


def test_postponement_and_swap_preserve_round_and_reviews(env, course):
    _schedule_and_open(env, course)
    c = env.client
    _ok(_review(env, course, "c1", "A"))
    _ok(_review(env, course, "c2", "A"))

    _ok(c.patch(f"{_base(course)}/presentations/{course.pres['A']}", json={"move": True, "session_number": 10, "postpone": True, "reason": "Team sick"}))
    with env.Session() as db:
        p = db.get(Presentation, course.pres["A"])
        assert (p.round_id, p.session_number, p.original_session_number, p.status) == (course.round_id, 10, 2, "postponed")
        assert p.review_open is False
        assert len(db.scalars(select(PeerReview).where(PeerReview.presentation_id == p.id)).all()) == 2
        kinds = [m.kind for m in db.scalars(select(PresentationMove).where(PresentationMove.presentation_id == p.id))]
        assert kinds[-1] == "postpone"

    # Reviews still count after the move
    scores = _ok(c.get(f"{_base(course)}/rounds/{course.round_id}/scores"))
    team_a = next(t for t in scores["teams"] if t["team_name"] == "Team A")
    assert team_a["valid_reviews"] == 2 and team_a["share"] is not None

    # Swap within the round
    _ok(c.post(f"{_base(course)}/rounds/{course.round_id}/swap", json={"a_id": course.pres["A"], "b_id": course.pres["C"], "reason": "requested"}))
    with env.Session() as db:
        assert db.get(Presentation, course.pres["A"]).session_number == 3
        assert db.get(Presentation, course.pres["C"]).session_number == 10


# ---------------------------------------------------------------------------
# Review rules
# ---------------------------------------------------------------------------


def test_own_team_window_and_validation_rules(env, course):
    _schedule_and_open(env, course)
    res = _review(env, course, "a1", "A")
    assert res.status_code == 403 and res.json()["detail"]["code"] == "own_team"
    # Session 3 isn't open yet
    res = _review(env, course, "a1", "C")
    assert res.status_code == 409 and res.json()["detail"]["code"] == "window_closed"
    # Out-of-scale score / missing criterion / missing required text
    res = _review(env, course, "a1", "B", scores={**GOOD, "testing": 7})
    assert res.json()["detail"]["code"] == "invalid_score"
    # Only the final score is required; criteria and comments are optional remarks.
    res = _review(env, course, "a1", "B", scores={"problem_clarity": 4})
    assert res.json()["detail"]["code"] == "missing_score"
    _ok(_review(env, course, "a1", "B", scores={"final_score": 3}, responses={}))
    _ok(_review(env, course, "a1", "B"))


def test_one_review_per_student_with_edits_until_deadline(env, course):
    _schedule_and_open(env, course)
    _ok(_review(env, course, "a1", "B"))
    _ok(_review(env, course, "a1", "B", scores={**GOOD, "testing": 5}))
    with env.Session() as db:
        rows = db.scalars(select(PeerReview).where(PeerReview.presentation_id == course.pres["B"])).all()
        assert len(rows) == 1 and json.loads(rows[0].scores_json)["testing"] == 5
        # The database itself rejects a second row for the same student.
        db.add(PeerReview(
            round_id=course.round_id, presentation_id=course.pres["B"], rubric_version_id=rows[0].rubric_version_id,
            reviewer_kind="student", reviewer_student_id=course.students["a1"],
        ))
        with pytest.raises(IntegrityError):
            db.commit()

    past = (datetime.utcnow() - timedelta(minutes=1)).isoformat() + "Z"
    _ok(env.client.patch(f"{_base(course)}/rounds/{course.round_id}", json={"review_deadline": past}))
    res = _review(env, course, "a1", "B", scores={**GOOD, "testing": 1})
    assert res.status_code == 409 and res.json()["detail"]["code"] == "deadline_passed"

    _ok(env.client.patch(f"{_base(course)}/rounds/{course.round_id}", json={"clear_review_deadline": True}))
    _ok(env.client.post(f"{_base(course)}/rounds/{course.round_id}/actions/close"))
    res = _review(env, course, "a1", "B")
    assert res.json()["detail"]["code"] == "window_closed"


def test_rubric_is_frozen_when_reviews_open(env, course):
    c = env.client
    rubrics = _ok(c.get(f"{_base(course)}/rubrics"))
    assert rubrics["progress"]["version"] == 1 and not rubrics["progress"]["frozen"]
    _schedule_and_open(env, course)
    edited = rubrics["progress"]
    edited["criteria"][0]["weight"] = 3
    saved = _ok(c.put(f"{_base(course)}/rubrics/progress", json={k: edited[k] for k in ("criteria", "scale", "prompts", "instructions")}))
    assert saved["version"] == 2
    overview = _ok(c.get(f"{_base(course)}/overview"))
    rnd = next(r for r in overview["rounds"] if r["id"] == course.round_id)
    assert rnd["rubric_version"]["version"] == 1
    home = _ok(c.get(f"/api/r/{course.tokens['a1']}"))
    rubric = next(r for r in home["rounds"] if r["id"] == course.round_id)["reviewing"]["rubric"]
    assert rubric["version"] == 1 and rubric["criteria"][0]["weight"] == 1.0


def test_team_change_keeps_historical_eligibility(env, course):
    _schedule_and_open(env, course)
    # a1 moves to team B after the round opened: the round still counts a1 on team A.
    _ok(env.client.put(f"{_base(course)}/students/{course.students['a1']}/team", json={"team_id": course.teams["B"]}))
    res = _review(env, course, "a1", "A")
    assert res.json()["detail"]["code"] == "own_team"  # still A's member for this round
    res = _review(env, course, "a1", "B")
    assert res.json()["detail"]["code"] == "own_team"  # and B is now their team
    scores = _ok(env.client.get(f"{_base(course)}/rounds/{course.round_id}/scores"))
    a1 = next(s for s in scores["students"] if s["student_id"] == course.students["a1"])
    assert a1["team_name"] == "Team A"


# ---------------------------------------------------------------------------
# Anonymity & access
# ---------------------------------------------------------------------------


def _all_identities_except(env, course, keep: set[str]) -> list[str]:
    out = []
    for key, (nid, name) in STUDENTS.items():
        if key in keep:
            continue
        out += [nid, name]
    return out


def test_student_payloads_never_reveal_reviewers(env, course):
    _schedule_and_open(env, course)
    c = env.client
    _ok(_review(env, course, "a1", "B", responses={"worked_well": "Loved the onboarding", "improvement": "Measure retention"}))
    _ok(_review(env, course, "c1", "B"))

    # Before release, B's members see nothing about reviews of their team.
    home = _ok(c.get(f"/api/r/{course.tokens['b1']}"))
    raw = json.dumps(home, ensure_ascii=False)
    assert "Loved the onboarding" not in raw
    for ident in _all_identities_except(env, course, {"b1"}):
        assert ident not in raw
    rnd = next(r for r in home["rounds"] if r["id"] == course.round_id)
    assert rnd["results"] is None

    # a1 sees their own review and own normalised shares, nothing else.
    home_a1 = _ok(c.get(f"/api/r/{course.tokens['a1']}"))
    rnd_a1 = next(r for r in home_a1["rounds"] if r["id"] == course.round_id)
    b = next(p for p in rnd_a1["reviewing"]["presentations"] if p["id"] == course.pres["B"])
    assert b["my_review"]["responses"]["worked_well"] == "Loved the onboarding"
    assert b["my_share"] == pytest.approx(1.0)  # only one review so far
    assert "Carmel" not in json.dumps(home_a1, ensure_ascii=False)

    _ok(c.post(f"{_base(course)}/rounds/{course.round_id}/actions/close"))
    _ok(c.post(f"{_base(course)}/rounds/{course.round_id}/actions/release"))
    home = _ok(c.get(f"/api/r/{course.tokens['b1']}"))
    raw = json.dumps(home, ensure_ascii=False)
    results = next(r for r in home["rounds"] if r["id"] == course.round_id)["results"]
    assert results["valid_reviews"] == 2
    texts = [f["responses"]["worked_well"] for f in results["feedback"]]
    assert "Loved the onboarding" in texts
    for ident in _all_identities_except(env, course, {"b1"}):
        assert ident not in raw
    for forbidden in ("reviewer", "student_id", "updated_at\": \"20"):
        assert all(forbidden not in json.dumps(f) for f in results["feedback"])


def test_release_requires_closed_round(env, course):
    _schedule_and_open(env, course)
    res = env.client.post(f"{_base(course)}/rounds/{course.round_id}/actions/release")
    assert res.status_code == 409


def test_instructor_routes_require_token_when_configured(env, course, monkeypatch):
    c = env.client
    monkeypatch.setattr(env.settings, "instructor_token", "s3cret-token")
    assert c.get(f"{_base(course)}/overview").status_code == 401
    assert c.get("/api/courses").status_code == 401
    assert c.get(f"{_base(course)}/overview", headers={"X-Instructor-Token": "wrong"}).status_code == 401
    _ok(c.get(f"{_base(course)}/overview", headers={"X-Instructor-Token": "s3cret-token"}))
    # Student and health routes stay reachable
    _ok(c.get(f"/api/r/{course.tokens['a1']}"))
    _ok(c.get("/api/health"))
    assert _ok(c.get("/api/auth/status")) == {"required": True, "authenticated": False}
    # Cookie session for browser links
    assert c.post("/api/auth/instructor-session", json={"token": "nope"}).status_code == 401
    res = c.post("/api/auth/instructor-session", json={"token": "s3cret-token"})
    assert res.status_code == 200 and "cg_instructor" in res.cookies
    _ok(c.get(f"{_base(course)}/overview"))
    # Unknown student link
    c.cookies.clear()
    assert c.get("/api/r/not-a-real-token-123456").status_code == 404


# ---------------------------------------------------------------------------
# Moderation, participation, exemptions, scores
# ---------------------------------------------------------------------------


def test_exclusion_participation_exemptions_and_scores(env, course):
    _schedule_and_open(env, course)
    c = env.client
    base = _base(course)
    for who in ("c1", "c2", "b1"):
        _ok(_review(env, course, who, "A"))
    for who in ("c1", "a1", "a2"):
        _ok(_review(env, course, who, "B", scores={k: 5 for k in GOOD}))

    reviews = _ok(c.get(f"{base}/rounds/{course.round_id}/reviews"))
    assert {r["reviewer_name"] for r in reviews} >= {"Carmel Cohen", "Alice Avraham"}  # instructor sees identity
    target = next(r for r in reviews if r["reviewer_name"] == "Bella Ben-David")
    assert c.post(f"{base}/reviews/{target['id']}/exclusion", json={"excluded": True, "reason": " "}).status_code == 400
    _ok(c.post(f"{base}/reviews/{target['id']}/exclusion", json={"excluded": True, "reason": "Abusive text"}))
    reviews = _ok(c.get(f"{base}/rounds/{course.round_id}/reviews"))
    kept = next(r for r in reviews if r["id"] == target["id"])
    assert kept["excluded"] and kept["exclusion_reason"] == "Abusive text"  # original kept

    scores = _ok(c.get(f"{base}/rounds/{course.round_id}/scores"))
    teams = {t["team_name"]: t for t in scores["teams"]}
    assert teams["Team A"]["valid_reviews"] == 2  # excluded review left out
    assert teams["Team C"]["share"] is None and teams["Team C"]["valid_reviews"] == 0  # not yet scored
    assert teams["Team A"]["share"] + teams["Team B"]["share"] == pytest.approx(1.0)

    part = {p["name"]: p for p in _ok(c.get(f"{base}/rounds/{course.round_id}/participation"))}
    # Each student owes reviews of the 2 other teams' presentations.
    assert part["Carmel Cohen"]["expected"] == 2 and part["Carmel Cohen"]["completed"] == 2
    assert part["Bella Ben-David"]["completed"] == 0 and part["Bella Ben-David"]["excluded"] == 1
    # A teammate's review doesn't count for b2
    assert part["Boaz Barak"]["completed"] == 0

    _ok(c.post(f"{base}/rounds/{course.round_id}/exemptions", json={"student_id": course.students["b2"], "session_number": 3, "exempt": True, "reason": "Reserve duty"}))
    part = {p["name"]: p for p in _ok(c.get(f"{base}/rounds/{course.round_id}/participation"))}
    assert (part["Boaz Barak"]["expected"], part["Boaz Barak"]["exempt"]) == (1, 1)
    assert c.post(f"{base}/rounds/{course.round_id}/exemptions", json={"student_id": course.students["b2"], "exempt": True, "reason": ""}).status_code == 400

    # Bonus via the existing override mechanism lands on the round's final score
    _ok(c.post(f"/api/courses/{course.id}/overrides", json={"student_id": course.students["a1"], "component": "peer_round_1", "delta": 3, "reason": "Great feedback"}))
    scores = _ok(c.get(f"{base}/rounds/{course.round_id}/scores"))
    students = {s["student_id"]: s for s in scores["students"]}
    a1 = students[course.students["a1"]]
    assert a1["bonus"] == 3 and a1["final"] == pytest.approx(a1["normalized"] + 3)
    # Team C hasn't been scored yet, so its members get no round score yet
    c1 = students[course.students["c1"]]
    assert c1["normalized"] is None and "team_not_scored" in c1["flags"]
    scored = [s["normalized"] for s in scores["students"] if s["normalized"] is not None]
    assert len(scored) == 4 and sum(scored) / len(scored) == pytest.approx(80.0, abs=0.01)


def test_export_contains_scores_but_no_reviewer_identities(env, course):
    _schedule_and_open(env, course)
    c = env.client
    _ok(_review(env, course, "c1", "A"))
    _ok(_review(env, course, "a1", "B"))
    res = c.get(f"{_base(course)}/rounds/{course.round_id}/export.xlsx")
    assert res.status_code == 200
    path = env.settings.data_dir + "/export.xlsx"
    with open(path, "wb") as fh:
        fh.write(res.content)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Team scores", "Student scores", "Participation", "Reviews (anonymised)"]
    reviews_sheet = " ".join(str(v) for row in wb["Reviews (anonymised)"].iter_rows(values_only=True) for v in row)
    for nid, name in STUDENTS.values():
        assert nid not in reviews_sheet and name not in reviews_sheet
    assert "Reviewer 0" in reviews_sheet


# ---------------------------------------------------------------------------
# LLM grader
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, text: str):
        self._text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return SimpleNamespace(
            stop_reason="end_turn",
            model="claude-opus-5-5",
            content=[SimpleNamespace(type="text", text=self._text)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=10),
        )


def test_llm_grader_is_one_reviewer_and_rerun_replaces_it(env, course, monkeypatch):
    _schedule_and_open(env, course)
    captured = {}

    def fake_stream(**kwargs):
        captured.update(kwargs)
        keys = [k for k in kwargs["extra_body"]["output_config"]["format"]["schema"]["required"]]
        body = {
            k: {
                "scores": GOOD,
                "rationales": {c: "ok" for c in GOOD},
                "responses": {"worked_well": "בינה מלאכותית: עבודה טובה", "improvement": "לבדוק עם משתמשים"},
            }
            for k in keys
        }
        return _FakeStream(json.dumps(body))

    fake_client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=fake_stream)))
    with env.Session() as db:
        rnd = db.get(ReviewRound, course.round_id)
        saved = llm_peer_review.run_llm_round_review(db, rnd, client=fake_client)
        assert len(saved) == 3
        llm_peer_review.run_llm_round_review(db, rnd, client=fake_client)  # re-run updates in place
        rows = db.scalars(select(PeerReview).where(PeerReview.reviewer_kind == "llm")).all()
        assert len(rows) == 3 and all(r.reviewer_student_id is None for r in rows)
    assert captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert captured["extra_body"]["fallbacks"] == "default"

    scores = _ok(env.client.get(f"{_base(course)}/rounds/{course.round_id}/scores"))
    assert all(t["valid_reviews"] == 1 and t["share"] == pytest.approx(1 / 3) for t in scores["teams"])

    _ok(env.client.post(f"{_base(course)}/rounds/{course.round_id}/actions/close"))
    _ok(env.client.post(f"{_base(course)}/rounds/{course.round_id}/actions/release"))
    home = _ok(env.client.get(f"/api/r/{course.tokens['a1']}"))
    results = next(r for r in home["rounds"] if r["id"] == course.round_id)["results"]
    assert [f["source"] for f in results["feedback"]] == ["ai"]


def test_llm_parse_rejects_out_of_scale_scores():
    rubric = {
        "criteria": [{"key": "x", "weight": 1}],
        "scale": [{"value": 1}, {"value": 2}],
        "prompts": [],
    }
    with pytest.raises(Exception):
        llm_peer_review.parse_result(json.dumps({"p1": {"scores": {"x": 9}, "responses": {}, "rationales": {}}}), rubric, [1])


def test_course_details_can_be_edited(env):
    c = env.client
    a = _ok(c.post("/api/courses", json={"code": "X1", "name": "One", "year": 2026, "semester": "A"}))["id"]
    _ok(c.post("/api/courses", json={"code": "X2", "name": "Two", "year": 2026, "semester": "A"}))
    updated = _ok(c.patch(f"/api/courses/{a}", json={"name": "בינה מלאכותית", "year": 2027}))
    assert (updated["name"], updated["code"], updated["year"]) == ("בינה מלאכותית", "X1", 2027)
    assert c.patch(f"/api/courses/{a}", json={"code": "X2", "year": 2026}).status_code == 409


def test_practice_round_opened_before_teams_exist(env):
    c = env.client
    cid = _ok(c.post("/api/courses", json={"code": "PR", "name": "Practice", "year": 2026, "semester": "A"}))["id"]
    base = f"/api/courses/{cid}/peer"
    with env.Session() as db:
        ids = {}
        for key, (nid, name) in list(STUDENTS.items())[:4]:  # a1, a2, b1, b2
            s = Student(national_id=nid, name=name)
            db.add(s)
            db.flush()
            db.add(Enrollment(course_id=cid, student_id=s.id))
            ids[key] = s.id
        db.commit()
    _ok(c.post(f"{base}/setup"))
    made = _ok(c.post(f"{base}/rounds/practice", json={"title": "Demo round", "open_now": True}))
    assert made["number"] == 0
    rounds = {r["number"]: r for r in _ok(c.get(f"{base}/overview"))["rounds"]}
    assert rounds[0]["status"] == "reviewing" and rounds[0]["counts_toward_grade"] is False
    assert rounds[0]["rubric_version"] is not None and rounds[1]["counts_toward_grade"] is True

    # Teams come later; the open practice round picks them up automatically.
    _ok(c.post("/api/courses/%d/peer/links/generate" % cid))
    tokens = {row["student_id"]: row["token"] for row in _ok(c.get(f"{base}/links"))}
    ta = _ok(c.post(f"{base}/teams", json={"name": "Team A"}))["id"]
    tb = _ok(c.post(f"{base}/teams", json={"name": "Team B"}))["id"]
    for key, team in (("a1", ta), ("a2", ta), ("b1", tb), ("b2", tb)):
        _ok(c.put(f"{base}/students/{ids[key]}/team", json={"team_id": team}))

    home = _ok(c.get(f"/api/r/{tokens[ids['a1']]}"))
    practice = next(r for r in home["rounds"] if r["number"] == 0)
    assert practice["practice"] is True
    items = {p["team_name"]: p for p in practice["reviewing"]["presentations"]}
    assert items["Team A"]["own_team"] and not items["Team A"]["accepting"]
    assert items["Team B"]["accepting"]  # open without any per-session switch
    assert practice["reviewing"]["progress"]["expected"] == 1  # only the other team

    rubric = practice["reviewing"]["rubric"]
    scores = {cr["key"]: 4 for cr in rubric["criteria"]}
    _ok(c.put(f"/api/r/{tokens[ids['a1']]}/reviews/{items['Team B']['id']}", json={"scores": scores, "responses": TEXT}))
    own = c.put(f"/api/r/{tokens[ids['a1']]}/reviews/{items['Team A']['id']}", json={"scores": scores, "responses": TEXT})
    assert own.json()["detail"]["code"] == "own_team"

    scored = _ok(c.get(f"{base}/rounds/{made['round_id']}/scores"))
    assert scored["counts_toward_grade"] is False
    graded = next(r for r in _ok(c.get(f"{base}/overview"))["rounds"] if r["number"] == 1)
    assert graded["status"] == "draft" and graded["obligations"]["expected"] == 0



def test_only_the_final_score_counts(env, course):
    """Remarks (the other criteria) never move the grade."""
    _schedule_and_open(env, course)
    base = _base(course)
    remarks_high = {"final_score": 3, "problem_clarity": 5, "usefulness": 5, "functionality": 5, "testing": 5}
    remarks_low = {"final_score": 3, "problem_clarity": 1, "usefulness": 1, "functionality": 1, "testing": 1}
    _ok(_review(env, course, "c1", "A", scores=remarks_high))
    _ok(_review(env, course, "c2", "B", scores=remarks_low))
    _ok(_review(env, course, "c1", "B", scores={"final_score": 3}))
    _ok(_review(env, course, "c2", "A", scores={"final_score": 3}))
    scores = _ok(env.client.get(f"{base}/rounds/{course.round_id}/scores"))
    teams = {t["team_name"]: t for t in scores["teams"]}
    assert teams["Team A"]["share"] == pytest.approx(teams["Team B"]["share"])
    assert teams["Team A"]["mean_total"] == pytest.approx(3.0)
    assert teams["Team A"]["criterion_means"]["problem_clarity"] == pytest.approx(5.0)  # still shown as feedback

    rubrics = _ok(env.client.get(f"{base}/rubrics"))
    bad = rubrics["final"]
    for c in bad["criteria"]:
        c["counts"] = False
    res = env.client.put(f"{base}/rubrics/final", json={k: bad[k] for k in ("criteria", "scale", "prompts", "instructions")})
    assert res.status_code == 400 and res.json()["detail"]["code"] == "invalid_rubric"



def test_instructor_can_preview_a_students_page(env, course, monkeypatch):
    _schedule_and_open(env, course)
    sid = course.students["a1"]
    preview = _ok(env.client.get(f"/api/courses/{course.id}/peer/student-view/{sid}"))
    assert preview == _ok(env.client.get(f"/api/r/{course.tokens['a1']}"))  # exactly what the student sees
    assert env.client.get(f"/api/courses/{course.id}/peer/student-view/999999").status_code == 404
    monkeypatch.setattr(env.settings, "instructor_token", "teacher")
    assert env.client.get(f"/api/courses/{course.id}/peer/student-view/{sid}").status_code == 401


def test_test_students_take_part_but_never_count(env, course):
    with env.Session() as db:
        s = Student(national_id="test-abcd1234", name="Test student")
        db.add(s)
        db.flush()
        db.add(Enrollment(course_id=course.id, student_id=s.id, is_test=True, review_token="t" * 32))
        db.commit()
        test_id = s.id
    course.tokens["test"] = "t" * 32
    _schedule_and_open(env, course)
    c, base = env.client, _base(course)
    for who in ("c1", "b1"):
        _ok(_review(env, course, who, "A"))
    for who in ("c1", "a1"):
        _ok(_review(env, course, who, "B", scores={k: 5 for k in GOOD}))
    before = _ok(c.get(f"{base}/rounds/{course.round_id}/scores"))

    # The test student sees the round and can review like anyone else...
    home = _ok(c.get(f"/api/r/{course.tokens['test']}"))
    assert home["rounds"]
    _ok(_review(env, course, "test", "A", scores={k: 1 for k in GOOD}))
    # ...but the review changes nothing and the student is in no score table.
    after = _ok(c.get(f"{base}/rounds/{course.round_id}/scores"))
    assert after["teams"] == before["teams"] and after["students"] == before["students"]
    assert test_id not in {s["student_id"] for s in after["students"]}
    students = {s["student_id"]: s for s in _ok(c.get(f"{base}/teams"))["students"]}
    assert students[test_id]["is_test"] and not students[course.students["a1"]]["is_test"]


def test_site_link_is_checked_when_saved_and_shown_to_reviewers(env, course, monkeypatch):
    from app.services import link_check

    checked = []

    def fake_check(url):
        checked.append(url)
        if "github.com" in url:
            return link_check.LinkCheck("warning", "זה קישור לקוד ב-GitHub, לא לאתר פעיל", url)
        return link_check.LinkCheck("ok", "האתר נפתח", url)

    monkeypatch.setattr(link_check, "check_link", fake_check)
    c, base = env.client, _base(course)
    _ok(c.patch(f"{base}/rounds/{course.round_id}", json={"link_required": True}))
    _schedule_and_open(env, course)

    url = f"/api/r/{course.tokens['a1']}/presentations/{course.pres['A']}/materials"
    assert c.patch(url, json={"demo_url": "jokes.example.org"}).status_code == 422
    home = _ok(c.patch(url, json={"demo_url": "https://github.com/team-a/jokes"}))
    mine = next(r for r in home["rounds"] if r["id"] == course.round_id)
    assert mine["link_required"] and mine["my_presentation"]["link_status"] == "warning"
    _ok(c.patch(url, json={"demo_url": " https://team-a.example.org/ "}))

    # A reviewer from another team sees the link and that it was checked.
    view = _ok(c.get(f"/api/r/{course.tokens['b1']}"))
    rnd = next(r for r in view["rounds"] if r["id"] == course.round_id)
    item = next(i for i in rnd["reviewing"]["presentations"] if i["id"] == course.pres["A"])
    assert (item["demo_url"], item["link_status"]) == ("https://team-a.example.org/", "ok")

    # The instructor can re-check every link at once.
    res = _ok(c.post(f"{base}/rounds/{course.round_id}/check-links"))
    assert res["counts"] == {"ok": 1, "missing": 2}
    overview = _ok(c.get(f"{base}/overview"))
    rnd = next(r for r in overview["rounds"] if r["id"] == course.round_id)
    assert rnd["link_required"] and {p["link_status"] for p in rnd["presentations"]} == {"ok", ""}
