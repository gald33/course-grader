"""Auto-assigning unteamed students: propose (no write), review, approve."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import Course, Enrollment, Student, Team, TeamMembership
from app.services import peer_review as svc


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


def _code(res, status):
    assert res.status_code == status, res.text
    return res.json()["detail"]["code"]


_nid = iter(range(500000000, 600000000))


def _course(env, code, max_size, team_sizes, unteamed, test=0, withdrawn=0):
    """Course with teams of the given sizes plus unteamed students; teams locked."""
    c = env.client
    course_id = _ok(c.post("/api/courses", json={"code": code, "name": code, "year": 2026, "semester": "A"}))["id"]
    base = f"/api/courses/{course_id}/peer"
    _ok(c.put(f"{base}/team-settings", json={"max_team_size": max_size}))
    ids = {"free": [], "test": [], "withdrawn": []}
    tokens = {}
    with env.Session() as db:

        def student(kind, **kw):
            nid = next(_nid)
            s = Student(national_id=str(nid), name=f"{kind} {nid}")
            db.add(s)
            db.flush()
            token = f"t{nid}".ljust(32, "x")
            db.add(Enrollment(course_id=course_id, student_id=s.id, review_token=token, **kw))
            tokens[s.id] = token
            return s.id

        members = [[student("member") for _ in range(n)] for n in team_sizes]
        ids["free"] = [student("free") for _ in range(unteamed)]
        ids["test"] = [student("test", is_test=True) for _ in range(test)]
        ids["withdrawn"] = [student("gone", withdrawn_at=datetime(2026, 1, 1)) for _ in range(withdrawn)]
        db.commit()
    teams = []
    for i, group in enumerate(members):
        tid = _ok(c.post(f"{base}/teams", json={"name": f"Team {i}"}))["id"]
        teams.append(tid)
        for sid in group:
            _ok(c.put(f"{base}/students/{sid}/team", json={"team_id": tid}))
    _ok(c.put(f"{base}/team-settings", json={"teams_open": False}))
    return SimpleNamespace(id=course_id, base=base, ids=ids, teams=teams, tokens=tokens)


def _state(env, course_id):
    with env.Session() as db:
        return (
            db.scalar(select(func.count(Team.id)).where(Team.course_id == course_id)),
            sorted(
                (m.student_id, m.team_id, m.end_at)
                for m in db.scalars(select(TeamMembership).where(TeamMembership.course_id == course_id))
            ),
        )


def _sizes(env, course_id):
    teams = _ok(env.client.get(f"/api/courses/{course_id}/peer/teams"))
    sizes = {t["id"]: 0 for t in teams["teams"]}
    for s in teams["students"]:
        if s["team_id"] is not None:
            sizes[s["team_id"]] += 1
    return sizes, teams


def test_propose_writes_nothing_and_places_every_eligible_student(env):
    course = _course(env, "P", max_size=3, team_sizes=[2, 3], unteamed=5, test=1, withdrawn=1)
    before = _state(env, course.id)
    proposal = _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={}))
    assert _state(env, course.id) == before  # nothing written

    # Team 0 (2 of 3) gets one; full Team 1 gets none; the other 4 form two pairs.
    assert [e["team_id"] for e in proposal["existing"]] == [course.teams[0]]
    assert len(proposal["existing"][0]["student_ids"]) == 1
    assert sorted(len(t["student_ids"]) for t in proposal["new_teams"]) == [2, 2]
    placed = [s for e in proposal["existing"] for s in e["student_ids"]]
    placed += [s for t in proposal["new_teams"] for s in t["student_ids"]]
    assert sorted(placed) == sorted(course.ids["free"])  # test / withdrawn left out
    assert proposal["max_team_size"] == 3 and isinstance(proposal["seed"], int)
    assert len({t["name"] for t in proposal["new_teams"]}) == 2

    # Students still have no team until the instructor approves.
    for sid in course.ids["free"]:
        assert _ok(env.client.get(f"/api/r/{course.tokens[sid]}"))["team"] is None


def test_proposal_is_deterministic_for_a_seed(env):
    course = _course(env, "S", max_size=4, team_sizes=[1, 2], unteamed=11)
    first = _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={"seed": 42}))
    again = _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={"seed": 42}))
    assert first == again and first["seed"] == 42
    other = _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={"seed": 7}))
    assert other["fingerprint"] == first["fingerprint"]
    # A seedless re-run reports the seed it used, which reproduces it.
    fresh = _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={}))
    assert _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={"seed": fresh["seed"]})) == fresh


@pytest.mark.parametrize(
    "max_size,team_sizes,unteamed,expect_existing,expect_new",
    [
        (7, [], 15, [], [5, 5, 5]),  # ceil(15/7)=3 balanced teams, not 7+7+1
        (7, [], 8, [], [4, 4]),
        (3, [2], 2, [], [2]),  # filling Team 0 would leave a lone student: pair them instead
        (3, [2, 2], 3, [1], [2]),  # fill gives 1 + 1, the last filled joins the one left
        (5, [5], 1, [], [1]),  # nothing has room and nobody else: a team of 1 is unavoidable
        (1, [], 3, [], [1, 1, 1]),
        (4, [1, 3], 2, [2], []),  # room for everyone: no new team
        # Empty existing teams are never filled one by one (no teams of one) ...
        (4, [3, 0, 0, 0], 3, [1, 2], []),  # team of 3 gets one, the pair goes to an empty team
        (4, [0, 0], 6, [3, 3], []),  # ... they take whole balanced groups instead
        (3, [0], 7, [3], [2, 2]),  # more groups than empty teams: the rest are new teams
        (4, [0, 2, 0], 5, [2, 3], []),  # mixed: fill the partial team, group the rest
        # max_team_size 2: an odd remainder pulls back a filled student to pair up.
        (2, [1], 4, [], [2, 2]),
        (2, [], 3, [], [1, 2]),  # nothing filled: one lone student is unavoidable
        (1, [1, 0], 2, [1], [1]),  # max 1: everyone alone, empty team used first
        (3, [2], 0, [], []),  # nobody to place
        (4, [], 8, [], [4, 4]),  # exact division
        (5, [], 203, [], [4, 4] + [5] * 39),
    ],
)
def test_assignment_rule(env, max_size, team_sizes, unteamed, expect_existing, expect_new):
    course = _course(env, f"R{max_size}{len(team_sizes)}{unteamed}", max_size, team_sizes, unteamed)
    with env.Session() as db:
        proposal = svc.propose_assignment(db, db.get(Course, course.id), seed=1)
    existing = sorted(len(e["student_ids"]) for e in proposal["existing"])
    new = sorted(len(t["student_ids"]) for t in proposal["new_teams"])
    assert existing == expect_existing and new == expect_new
    for e in proposal["existing"]:
        assert team_sizes[course.teams.index(e["team_id"])] + len(e["student_ids"]) <= max_size


def test_approve_applies_exactly_the_edited_proposal(env):
    course = _course(env, "A", max_size=3, team_sizes=[2], unteamed=5)
    c = env.client
    proposal = _ok(c.post(f"{course.base}/teams/auto-assign/propose", json={"seed": 3}))
    # Edit: drop one student from a new team, move another into the other new team, rename.
    dropped = proposal["new_teams"][0]["student_ids"].pop()
    moved = proposal["new_teams"][0]["student_ids"].pop()
    proposal["new_teams"][1]["student_ids"].append(moved)
    proposal["new_teams"][1]["name"] = "Night Owls"
    body = {k: proposal[k] for k in ("fingerprint", "existing", "new_teams")}
    result = _ok(c.post(f"{course.base}/teams/auto-assign/approve", json=body))
    assert result["placed"] == 4

    sizes, teams = _sizes(env, course.id)
    by_student = {s["student_id"]: s["team_id"] for s in teams["students"]}
    for e in proposal["existing"]:
        assert all(by_student[s] == e["team_id"] for s in e["student_ids"])
    names = {t["id"]: t["name"] for t in teams["teams"]}
    for t in proposal["new_teams"]:
        tids = {by_student[s] for s in t["student_ids"]}
        if t["student_ids"]:
            assert len(tids) == 1 and names[tids.pop()] == t["name"]
    assert by_student[dropped] is None and teams["unassigned"] == [dropped]
    assert max(sizes.values()) <= 3

    # Students see their new team now.
    home = _ok(c.get(f"/api/r/{course.tokens[moved]}"))
    assert home["team"]["name"] == "Night Owls"

    # Approving the same proposal again is refused (stale) and writes nothing.
    before = _state(env, course.id)
    assert _code(c.post(f"{course.base}/teams/auto-assign/approve", json=body), 409) == "stale_proposal"
    assert _state(env, course.id) == before


def test_approve_refuses_a_stale_proposal(env):
    course = _course(env, "St", max_size=4, team_sizes=[1], unteamed=3)
    c = env.client
    proposal = _ok(c.post(f"{course.base}/teams/auto-assign/propose", json={}))
    body = {k: proposal[k] for k in ("fingerprint", "existing", "new_teams")}
    # The instructor places a student by hand in the meantime.
    _ok(c.put(f"{course.base}/students/{course.ids['free'][0]}/team", json={"team_id": course.teams[0]}))
    before = _state(env, course.id)
    assert _code(c.post(f"{course.base}/teams/auto-assign/approve", json=body), 409) == "stale_proposal"
    assert _state(env, course.id) == before

    # Roster changes make it stale too (a student marked as a test student).
    proposal = _ok(c.post(f"{course.base}/teams/auto-assign/propose", json={}))
    with env.Session() as db:
        e = db.scalar(select(Enrollment).where(Enrollment.student_id == course.ids["free"][1]))
        e.is_test = True
        db.commit()
    body = {k: proposal[k] for k in ("fingerprint", "existing", "new_teams")}
    assert _code(c.post(f"{course.base}/teams/auto-assign/approve", json=body), 409) == "stale_proposal"


def _stale_after(env, course, change):
    proposal = _ok(env.client.post(f"{course.base}/teams/auto-assign/propose", json={}))
    change()
    body = {k: proposal[k] for k in ("fingerprint", "existing", "new_teams")}
    before = _state(env, course.id)
    assert _code(env.client.post(f"{course.base}/teams/auto-assign/approve", json=body), 409) == "stale_proposal"
    assert _state(env, course.id) == before


def test_team_delete_withdrawal_and_new_enrollment_make_a_proposal_stale(env):
    course = _course(env, "St2", max_size=4, team_sizes=[1, 0], unteamed=4)
    c = env.client
    _stale_after(env, course, lambda: _ok(c.delete(f"{course.base}/teams/{course.teams[1]}")))
    _stale_after(
        env, course, lambda: _ok(c.post(f"/api/courses/{course.id}/students/{course.ids['free'][0]}/withdraw"))
    )
    _stale_after(
        env,
        course,
        lambda: _ok(c.post(f"/api/courses/{course.id}/students", json={"national_id": "123456782", "name": "Late"})),
    )


def test_approve_refreshes_open_practice_rounds(env):
    from app.models.entities import ReviewRoundRoster

    course = _course(env, "Pr", max_size=3, team_sizes=[2], unteamed=1)
    c = env.client
    round_id = _ok(c.post(f"{course.base}/rounds/practice", json={"open_now": True}))["round_id"]
    proposal = _ok(c.post(f"{course.base}/teams/auto-assign/propose", json={}))
    _ok(c.post(f"{course.base}/teams/auto-assign/approve", json={k: proposal[k] for k in ("fingerprint", "existing", "new_teams")}))
    with env.Session() as db:
        row = db.scalar(
            select(ReviewRoundRoster).where(
                ReviewRoundRoster.round_id == round_id, ReviewRoundRoster.student_id == course.ids["free"][0]
            )
        )
        assert row is not None and row.team_id == course.teams[0]


def test_approve_validates_every_placement(env):
    course = _course(env, "V", max_size=3, team_sizes=[2], unteamed=2, test=1, withdrawn=1)
    other = _course(env, "V2", max_size=3, team_sizes=[1], unteamed=1)
    c = env.client
    fp = _ok(c.post(f"{course.base}/teams/auto-assign/propose", json={}))["fingerprint"]
    url = f"{course.base}/teams/auto-assign/approve"
    free = course.ids["free"]
    before = _state(env, course.id)

    def approve(existing=(), new_teams=()):
        return c.post(url, json={"fingerprint": fp, "existing": list(existing), "new_teams": list(new_teams)})

    assert _code(approve(new_teams=[{"name": "X", "student_ids": [course.ids["test"][0]]}]), 422) == "invalid_proposal"
    assert _code(approve(new_teams=[{"name": "X", "student_ids": [course.ids["withdrawn"][0]]}]), 422) == "invalid_proposal"
    assert _code(approve(new_teams=[{"name": "X", "student_ids": [other.ids["free"][0]]}]), 422) == "invalid_proposal"
    assert _code(approve(existing=[{"team_id": other.teams[0], "student_ids": [free[0]]}]), 404) == "not_found"
    assert _code(approve(existing=[{"team_id": course.teams[0], "student_ids": free}]), 409) == "team_full"
    split = [{"team_id": course.teams[0], "student_ids": [free[0]]}, {"team_id": course.teams[0], "student_ids": [free[1]]}]
    assert _code(approve(existing=split), 409) == "team_full"
    assert _code(approve(new_teams=[{"name": "X", "student_ids": [free[0], free[0]]}]), 422) == "invalid_proposal"
    assert _code(approve(new_teams=[{"name": "Team 0", "student_ids": [free[0]]}]), 409) == "team_name_taken"
    assert _code(approve(new_teams=[{"name": "Y", "student_ids": [free[0]]}, {"name": "Y", "student_ids": [free[1]]}]), 409) == "team_name_taken"
    assert _state(env, course.id) == before

    # A proposal from another course's state doesn't apply here.
    other_fp = _ok(c.post(f"{other.base}/teams/auto-assign/propose", json={}))["fingerprint"]
    res = c.post(url, json={"fingerprint": other_fp, "existing": [], "new_teams": []})
    assert _code(res, 409) == "stale_proposal"


def test_only_after_teams_lock(env):
    course = _course(env, "L", max_size=3, team_sizes=[], unteamed=2)
    c = env.client
    proposal = _ok(c.post(f"{course.base}/teams/auto-assign/propose", json={}))
    _ok(c.put(f"{course.base}/team-settings", json={"teams_open": True}))
    assert _code(c.post(f"{course.base}/teams/auto-assign/propose", json={}), 409) == "teams_open"
    body = {k: proposal[k] for k in ("fingerprint", "existing", "new_teams")}
    assert _code(c.post(f"{course.base}/teams/auto-assign/approve", json=body), 409) == "teams_open"


def test_instructor_only(env, monkeypatch):
    course = _course(env, "I", max_size=3, team_sizes=[], unteamed=2)
    monkeypatch.setattr(env.settings, "instructor_token", "teacher-token")
    c = env.client
    assert c.post(f"{course.base}/teams/auto-assign/propose", json={}).status_code == 401
    body = {"fingerprint": "x", "existing": [], "new_teams": []}
    assert c.post(f"{course.base}/teams/auto-assign/approve", json=body).status_code == 401
    assert c.post("/api/courses/999999/peer/teams/auto-assign/propose", json={}).status_code == 401
    monkeypatch.setattr(env.settings, "instructor_token", None)
    assert c.post("/api/courses/999999/peer/teams/auto-assign/propose", json={}).status_code == 404
