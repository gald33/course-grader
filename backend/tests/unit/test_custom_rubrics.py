"""Custom rubrics: authoring, LLM scoring in the autograder, overrides, the
gradebook, the student view, and the fixed rubric left untouched."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.api.deps import get_db
from app.core.config import get_settings
from app.main import app
from app.models.entities import (
    Assignment,
    Course,
    CriterionOverride,
    CriterionResult,
    Enrollment,
    Job,
    RubricCriterion,
    Submission,
)
from app.services import llm_rubric_review
from app.services.scoring import compute_gradebook_rows

sys.path.insert(0, str(Path(__file__).resolve().parent))
from autograder_harness import fixed_pipeline_snapshot, queue_run, seed_course, stub_autograder  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
GOLDEN = json.loads((BACKEND / "tests" / "fixtures" / "fixed_rubric_golden.json").read_text(encoding="utf-8"))


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
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "instructor_token", None)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as client:
        with Session() as db:
            course = seed_course(db)
        yield SimpleNamespace(client=client, Session=Session, course=course, monkeypatch=monkeypatch)
    app.dependency_overrides.clear()


def _ok(res, status=200):
    assert res.status_code == status, res.text
    return res.json()


def _rubric_url(env, assignment_id=None, course_id=None):
    return f"/api/courses/{course_id or env.course.id}/assignments/{assignment_id or env.course.hw2_id}/rubric"


CRITERIA = [
    {"name": "Data cleaning", "description": "Missing values handled and justified", "max_points": 30},
    {
        "name": "Models",
        "description": "At least three models compared",
        "max_points": 50,
        "levels": [{"points": 50, "description": "3+ models, compared"}, {"points": 20, "description": "one model"}],
    },
    {"name": "Plots", "description": "", "max_points": 20},
]


def _author(env, criteria=CRITERIA, assignment_id=None):
    return _ok(env.client.put(_rubric_url(env, assignment_id), json={"criteria": criteria}))["rubric"]


class FakeLLM:
    """Stands in for anthropic.Anthropic in llm_rubric_review; records calls."""

    def __init__(self, payload=None, error: Exception | None = None):
        self.payload, self.error, self.calls = payload, error, []

    def install(self, monkeypatch):
        fake = self

        class _Client:
            def __init__(self, api_key):
                self.messages = SimpleNamespace(create=fake.create)

        monkeypatch.setattr(llm_rubric_review.anthropic, "Anthropic", _Client)
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        payload = self.payload(kwargs) if callable(self.payload) else self.payload
        return SimpleNamespace(
            stop_reason="tool_use",
            content=[SimpleNamespace(type="tool_use", name=llm_rubric_review.TOOL_NAME, input=payload)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )


def _scores(rubric, values):
    """Tool payload: {"scores": {"c<id>": {"score", "rationale"}}} in criterion order."""
    return {
        "scores": {
            f"c{c['id']}": {"score": v, "rationale": f"[cell {i + 2}] evidence"}
            for i, (c, v) in enumerate(zip(rubric["criteria"], values))
        }
    }


def _run(env, submission_id):
    from app.tasks import jobs

    with env.Session() as db:
        run_id = queue_run(db, submission_id)
    result = jobs.run_notebook(run_id)
    assert result["status"] == "SUCCESS", result
    return run_id


def _view(env, submission_id):
    return _ok(env.client.get(f"/api/submissions/{submission_id}"))["custom_rubric"]


def _row(env, name="Alice"):
    with env.Session() as db:
        return next(r for r in compute_gradebook_rows(db, env.course.id) if r["name"] == name)


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------


def test_create_edit_reorder_delete_criteria(env):
    state = _ok(env.client.get(_rubric_url(env)))
    assert state["rubric"] is None and state["supported"] is True

    rubric = _author(env)
    assert [c["name"] for c in rubric["criteria"]] == ["Data cleaning", "Models", "Plots"]
    assert [c["position"] for c in rubric["criteria"]] == [0, 1, 2]
    assert rubric["total_points"] == 100
    assert rubric["criteria"][1]["levels"] == CRITERIA[1]["levels"]
    ids = [c["id"] for c in rubric["criteria"]]

    # Reorder, edit one, drop one, add one: ids of kept criteria survive.
    edited = [
        {**rubric["criteria"][2], "max_points": 25},
        {**rubric["criteria"][0], "name": "Cleaning"},
        {"name": "Report", "description": "Explains results", "max_points": 10},
    ]
    rubric = _author(env, edited)
    assert [(c["id"], c["name"], c["max_points"]) for c in rubric["criteria"]][:2] == [(ids[2], "Plots", 25), (ids[0], "Cleaning", 30)]
    assert rubric["criteria"][2]["name"] == "Report" and rubric["criteria"][2]["id"] not in ids
    assert rubric["total_points"] == 65
    with env.Session() as db:
        assert db.get(RubricCriterion, ids[1]) is None

    # Delete the rubric: back to none.
    assert _ok(env.client.delete(_rubric_url(env)))["rubric"] is None
    assert env.client.delete(_rubric_url(env)).status_code == 404


@pytest.mark.parametrize(
    "criteria",
    [
        [],
        [{"name": " ", "max_points": 10}],
        [{"name": "A", "max_points": 0}],
        [{"name": "A", "max_points": 10, "levels": [{"points": 11, "description": "too much"}]}],
    ],
)
def test_invalid_rubrics_are_rejected(env, criteria):
    assert env.client.put(_rubric_url(env), json={"criteria": criteria}).status_code == 422


def test_criterion_ids_must_belong_to_the_rubric(env):
    other = _author(env, assignment_id=env.course.project_id)
    res = env.client.put(_rubric_url(env), json={"criteria": [{**other["criteria"][0]}]})
    assert res.status_code == 400
    with env.Session() as db:
        assert db.scalar(select(func.count()).select_from(RubricCriterion)) == 3


def test_copy_from_another_assignment(env):
    source = _author(env, assignment_id=env.course.project_id)
    # Another course's assignment can copy it too (rubrics carry across semesters).
    with env.Session() as db:
        other_course = Course(code="AI2", name="AI 2", year=2027, semester="A")
        db.add(other_course)
        db.flush()
        other = Assignment(course_id=other_course.id, workcode=2, name="HW2 next year", assignment_type="HW2")
        db.add(other)
        db.commit()
        other_course_id, other_id = other_course.id, other.id

    sources = _ok(env.client.get(f"/api/courses/{env.course.id}/rubric-sources"))
    assert [s["assignment_id"] for s in sources] == [env.course.project_id]
    assert sources[0]["criteria_count"] == 3 and sources[0]["total_points"] == 100

    for course_id, assignment_id in ((env.course.id, env.course.hw2_id), (other_course_id, other_id)):
        copied = _ok(
            env.client.post(
                _rubric_url(env, assignment_id, course_id) + "/copy",
                json={"source_assignment_id": env.course.project_id},
            )
        )["rubric"]
        assert [(c["name"], c["description"], c["max_points"], c["levels"]) for c in copied["criteria"]] == [
            (c["name"], c["description"], c["max_points"], c["levels"]) for c in source["criteria"]
        ]
        assert {c["id"] for c in copied["criteria"]}.isdisjoint({c["id"] for c in source["criteria"]})
        assert copied["copied_from"] == {"assignment_id": env.course.project_id, "name": "Project"}

    # The copy is independent of its source.
    _author(env, [{"name": "Only", "max_points": 5}], assignment_id=env.course.project_id)
    assert len(_ok(env.client.get(_rubric_url(env)))["rubric"]["criteria"]) == 3

    assert env.client.post(_rubric_url(env) + "/copy", json={"source_assignment_id": env.course.hw2_id}).status_code == 400
    with env.Session() as db:
        hw1 = Assignment(course_id=env.course.id, workcode=1, name="HW1", assignment_type="HW1")
        db.add(hw1)
        db.commit()
        hw1_id = hw1.id
    assert env.client.post(_rubric_url(env) + "/copy", json={"source_assignment_id": hw1_id}).status_code == 404


def test_rubrics_only_for_autograded_assignments(env):
    with env.Session() as db:
        hw1 = Assignment(course_id=env.course.id, workcode=1, name="HW1", assignment_type="HW1")
        db.add(hw1)
        db.commit()
        hw1_id = hw1.id
    assert _ok(env.client.get(_rubric_url(env, hw1_id)))["supported"] is False
    assert env.client.put(_rubric_url(env, hw1_id), json={"criteria": CRITERIA}).status_code == 400


def test_routes_are_scoped_to_the_course(env):
    with env.Session() as db:
        other = Course(code="X", name="X", year=2026, semester="B")
        db.add(other)
        db.commit()
        other_id = other.id
    rubric = _author(env)
    # The assignment exists, but not in that course.
    for method in ("get", "delete"):
        assert getattr(env.client, method)(_rubric_url(env, course_id=other_id)).status_code == 404
    assert env.client.put(_rubric_url(env, course_id=other_id), json={"criteria": CRITERIA}).status_code == 404
    assert env.client.get(_rubric_url(env, course_id=999999)).status_code == 404

    # A criterion of HW2's rubric can't be overridden on a project submission.
    cid = rubric["criteria"][0]["id"]
    res = env.client.put(f"/api/submissions/{env.course.project_sub_id}/custom-rubric/{cid}/override", json={"score": 1})
    assert res.status_code == 404


def test_routes_are_instructor_only(env):
    env.monkeypatch.setattr(get_settings(), "instructor_token", "secret")
    sub = env.course.hw2_sub_ids[0]
    requests = [
        ("get", _rubric_url(env), None),
        ("put", _rubric_url(env), {"criteria": CRITERIA}),
        ("delete", _rubric_url(env), None),
        ("post", _rubric_url(env) + "/copy", {"source_assignment_id": env.course.project_id}),
        ("post", _rubric_url(env) + "/score", None),
        ("get", f"/api/courses/{env.course.id}/rubric-sources", None),
        ("put", f"/api/submissions/{sub}/custom-rubric/1/override", {"score": 1}),
        ("delete", f"/api/submissions/{sub}/custom-rubric/1/override", None),
        ("post", f"/api/submissions/{sub}/custom-rubric/score", None),
    ]
    for method, url, body in requests:
        kwargs = {"json": body} if body is not None else {}
        assert env.client.request(method.upper(), url, **kwargs).status_code == 401, url
    # A student's login doesn't help either: only the instructor token does.
    env.client.cookies.set("cg_student", "anything")
    assert env.client.get(_rubric_url(env)).status_code == 401
    env.client.cookies.clear()
    res = env.client.get(_rubric_url(env), headers={"X-Instructor-Token": "secret"})
    assert res.status_code == 200


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_run_scores_each_criterion_with_clamping_and_rationales(env):
    rubric = _author(env)
    llm = FakeLLM(lambda kw: _scores(rubric, [45, 30.5, -3])).install(env.monkeypatch)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    run_id = _run(env, sub)

    view = _view(env, sub)
    assert [(c["status"], c["llm_score"], c["effective_score"], c["source"]) for c in view["criteria"]] == [
        ("scored", 30.0, 30.0, "llm"),  # 45 clamped to max 30
        ("scored", 30.5, 30.5, "llm"),
        ("scored", 0.0, 0.0, "llm"),  # -3 clamped to 0
    ]
    assert view["criteria"][0]["rationale"] == "[cell 2] evidence" and view["criteria"][0]["run_id"] == run_id
    assert view["total"] == 60.5 and view["max_total"] == 100 and view["percent"] == 60.5

    # One call: cached system prompt holding the rubric, the configured model,
    # forced tool, and the deterministic metrics as evidence.
    (call,) = llm.calls
    assert call["model"] == get_settings().llm_review_model
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "Data cleaning (max 30 points)" in call["system"][0]["text"]
    assert "50 points: 3+ models, compared" in call["system"][0]["text"]
    assert call["tool_choice"] == {"type": "tool", "name": llm_rubric_review.TOOL_NAME}
    props = call["tools"][0]["input_schema"]["properties"]["scores"]["properties"]
    assert props[f"c{rubric['criteria'][1]['id']}"]["properties"]["score"]["maximum"] == 50
    user = call["messages"][0]["content"]
    assert "[cell 1] (markdown)" in user and "We drop rows with missing age" in user
    assert "AUTOMATIC MEASUREMENTS (evidence, not scores)" in user
    assert '"num_models_baseline"' in user and '"run_ratio": 0.5' in user
    assert "WRITTEN REPORT" not in user  # HW2 has no report

    # The fixed pipeline still ran alongside (its rows feed the evidence).
    with env.Session() as db:
        assert fixed_pipeline_snapshot(db, sub)["scores"]


def test_project_scoring_includes_the_report(env):
    rubric = _author(env, assignment_id=env.course.project_id)
    llm = FakeLLM(lambda kw: _scores(rubric, [10, 10, 10])).install(env.monkeypatch)
    env.monkeypatch.setattr("app.services.pdf_service.extract_text_from_pdf", lambda path: "Our report: random forest wins.")
    stub_autograder(env.monkeypatch, env.Session)
    _run(env, env.course.project_sub_id)
    assert "=== WRITTEN REPORT ===\nOur report: random forest wins." in llm.calls[0]["messages"][0]["content"]


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLM(error=RuntimeError("API down")),
        FakeLLM(payload={"scores": "not json"}),
        FakeLLM(payload={"wrong": {}}),
    ],
    ids=["raises", "malformed", "no-scores"],
)
def test_llm_failure_leaves_criteria_not_scored_and_the_run_succeeds(env, llm):
    _author(env)
    llm.install(env.monkeypatch)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    _run(env, sub)  # asserts SUCCESS

    view = _view(env, sub)
    assert [c["status"] for c in view["criteria"]] == ["not_scored"] * 3
    assert all(c["effective_score"] is None and c["error"] for c in view["criteria"])
    assert view["not_scored"] == 3 and view["total"] == 0
    # The run's own results are saved.
    detail = _ok(env.client.get(f"/api/submissions/{sub}"))
    assert detail["runs"][0]["status"] == "SUCCESS" and detail["code_review"] is not None


def test_missing_api_key_means_not_scored(env):
    _author(env)
    env.monkeypatch.setattr(get_settings(), "anthropic_api_key", None)
    llm = FakeLLM(payload={}).install(env.monkeypatch)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    _run(env, sub)
    assert llm.calls == []
    assert "ANTHROPIC_API_KEY" in _view(env, sub)["criteria"][0]["error"]


def test_partial_answer_scores_what_it_can(env):
    rubric = _author(env)
    payload = _scores(rubric, [10, 20, 5])
    del payload["scores"][f"c{rubric['criteria'][2]['id']}"]
    payload["scores"][f"c{rubric['criteria'][1]['id']}"]["score"] = "lots"
    FakeLLM(payload=payload).install(env.monkeypatch)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    _run(env, sub)
    assert [c["status"] for c in _view(env, sub)["criteria"]] == ["scored", "not_scored", "not_scored"]


def test_a_failed_rescore_keeps_the_last_score(env):
    rubric = _author(env)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    FakeLLM(lambda kw: _scores(rubric, [20, 40, 10])).install(env.monkeypatch)
    _run(env, sub)
    FakeLLM(error=RuntimeError("API down")).install(env.monkeypatch)
    _run(env, sub)
    view = _view(env, sub)
    assert [c["effective_score"] for c in view["criteria"]] == [20, 40, 10]
    assert all(c["last_attempt_failed"] for c in view["criteria"])


def test_rescore_job_scores_without_rerunning(env):
    from app.tasks import jobs
    from app.tasks.queue import claim_next, run_job

    rubric = _author(env)
    stub_autograder(env.monkeypatch, env.Session, fixed_llm=False)
    sub = env.course.hw2_sub_ids[1]
    FakeLLM(error=RuntimeError("API down")).install(env.monkeypatch)
    _run(env, sub)
    assert _view(env, sub)["not_scored"] == 3

    FakeLLM(lambda kw: _scores(rubric, [1, 2, 3])).install(env.monkeypatch)
    env.monkeypatch.setattr(jobs, "execute_notebook", lambda *a, **k: pytest.fail("notebook re-run"))
    _ok(env.client.post(f"/api/submissions/{sub}/custom-rubric/score"))
    with env.Session() as db:
        job = claim_next(db, "test")
        assert job.name == "app.tasks.jobs.score_custom_rubric"
        run_job(db, job)
        assert db.get(Job, job.id).status == "succeeded"
    assert [c["effective_score"] for c in _view(env, sub)["criteria"]] == [1, 2, 3]

    # Assignment-wide: only submissions with an executed notebook are queued.
    assert _ok(env.client.post(_rubric_url(env) + "/score"))["queued"] == 1
    # No executed notebook yet: nothing to score.
    assert env.client.post(f"/api/submissions/{env.course.hw2_sub_ids[0]}/custom-rubric/score").status_code == 400


# ---------------------------------------------------------------------------
# Overrides and the gradebook
# ---------------------------------------------------------------------------


def test_overrides_win_and_survive_reruns(env):
    rubric = _author(env)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    FakeLLM(lambda kw: _scores(rubric, [10, 20, 5])).install(env.monkeypatch)
    _run(env, sub)

    c0, c1 = rubric["criteria"][0]["id"], rubric["criteria"][1]["id"]
    url = f"/api/submissions/{sub}/custom-rubric/{c0}/override"
    view = _ok(env.client.put(url, json={"score": 28, "note": "Explained in the report"}))
    assert view["criteria"][0]["effective_score"] == 28 and view["criteria"][0]["source"] == "override"
    assert view["criteria"][0]["llm_score"] == 10
    assert view["criteria"][0]["override"]["note"] == "Explained in the report"
    assert env.client.put(url, json={"score": 31}).status_code == 400  # above max 30
    assert env.client.put(url, json={"score": -1}).status_code == 422

    # Re-running the notebook re-scores, but the override still wins.
    FakeLLM(lambda kw: _scores(rubric, [3, 44, 7])).install(env.monkeypatch)
    _run(env, sub)
    view = _view(env, sub)
    assert [c["effective_score"] for c in view["criteria"]] == [28, 44, 7]
    assert view["criteria"][0]["llm_score"] == 3

    # Overriding a not-scored criterion counts too; clearing goes back to the LLM.
    _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{c1}/override", json={"score": 0}))
    assert _view(env, sub)["criteria"][1]["effective_score"] == 0
    _ok(env.client.delete(f"/api/submissions/{sub}/custom-rubric/{c1}/override"))
    assert _view(env, sub)["criteria"][1]["effective_score"] == 44

    # Editing the rubric keeps overrides of kept criteria; deleting a criterion drops its rows.
    current = _ok(env.client.get(_rubric_url(env)))["rubric"]["criteria"]
    _author(env, [current[0], current[2]])
    with env.Session() as db:
        assert db.scalar(select(func.count()).select_from(CriterionOverride).where(CriterionOverride.criterion_id == c0)) == 1
        assert db.scalar(select(func.count()).select_from(CriterionResult).where(CriterionResult.criterion_id == c1)) == 0


def test_gradebook_total_comes_from_the_custom_rubric(env):
    before = _row(env, "Alice")
    assert before["hw2"] == GOLDEN["before"][0]["hw2"]
    rubric = _author(env)

    # Alice's HW2 has run_ratio penalty 0.8 (seeded run) and no criterion scores yet: 0.
    assert _row(env, "Alice")["hw2"] == 0
    sub = env.course.hw2_sub_ids[0]
    for crit, score in zip(rubric["criteria"], (30, 25, 15)):
        _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{crit['id']}/override", json={"score": score}))
    row = _row(env, "Alice")
    assert row["hw2"] == round(70 * 0.8, 2)  # 70/100 points, times the run-ratio penalty
    assert _view(env, sub)["component_score"] == row["hw2"]
    # The curve doesn't apply: the uncurved final moves by the same amount.
    assert row["final"] - before["final"] == pytest.approx(row["final_uncurved"] - before["final_uncurved"], abs=1)
    # Bob's HW2 has no scores and no run (penalty 1): 0, not his fixed-rubric score.
    assert _row(env, "Bob")["hw2"] == 0
    # The project (no rubric) is untouched.
    assert row["project_code"] == GOLDEN["before"][0]["project_code"]

    # A manual grade still wins over everything.
    with env.Session() as db:
        db.get(Submission, sub).manual_grade = 91.0
        db.commit()
    assert _row(env, "Alice")["hw2"] == 91.0
    with env.Session() as db:
        db.get(Submission, sub).manual_grade = None
        db.commit()

    # Deleting the rubric restores the fixed rubric's score exactly.
    _ok(env.client.delete(_rubric_url(env)))
    assert _row(env, "Alice") == before


def test_project_code_from_custom_rubric(env):
    rubric = _author(env, [{"name": "Pipeline", "max_points": 40}], assignment_id=env.course.project_id)
    sub = env.course.project_sub_id
    _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{rubric['criteria'][0]['id']}/override", json={"score": 30}))
    row = _row(env, "Bob")
    assert row["project_code"] == round(75 * 0.6, 2)
    assert row["project_report"] == GOLDEN["before"][1]["project_report"]


def _student_token(env, name):
    from app.models.entities import Student
    from app.services.peer_review import new_review_token

    with env.Session() as db:
        enrollment = db.scalar(
            select(Enrollment).join(Student, Student.id == Enrollment.student_id).where(Student.name == name)
        )
        enrollment.review_token = new_review_token()
        db.commit()
        return enrollment.review_token


def _student_rubrics(env, token):
    return _ok(env.client.get(f"/api/r/{token}"))["rubrics"]


def test_student_payload_shows_criteria_only_before_release(env):
    rubric = _author(env)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    FakeLLM(lambda kw: _scores(rubric, [12, 34, 5])).install(env.monkeypatch)
    _run(env, sub)
    with env.Session() as db:
        db.get(Submission, sub).feedback_student = "Good work"
        db.commit()
    token = _student_token(env, "Bob")

    # Nothing released (and the project, released, has no rubric).
    from app.services.student_grades import set_released

    with env.Session() as db:
        set_released(db, env.course.id, "project", True)
    (entry,) = _student_rubrics(env, token)
    assert entry["released"] is False and entry["name"] == "HW2"
    assert entry["criteria"] == [
        {"name": c["name"], "description": c["description"], "max_points": c["max_points"]} for c in CRITERIA
    ]
    dumped = json.dumps(entry)
    assert "evidence" not in dumped and "Good work" not in dumped and "total" not in entry


def test_student_payload_shows_scores_and_rationales_once_released(env):
    from app.services.student_grades import set_released

    rubric = _author(env)
    stub_autograder(env.monkeypatch, env.Session)
    sub = env.course.hw2_sub_ids[1]
    payload = _scores(rubric, [12, 34, 5])
    del payload["scores"][f"c{rubric['criteria'][1]['id']}"]  # left unscored
    FakeLLM(payload=payload).install(env.monkeypatch)
    _run(env, sub)
    c2 = rubric["criteria"][2]["id"]
    _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{c2}/override", json={"score": 18, "note": "private note"}))
    with env.Session() as db:
        db.get(Submission, sub).feedback_student = "Good work"
        db.commit()
        set_released(db, env.course.id, "hw2", True)

    (entry,) = _student_rubrics(env, _student_token(env, "Bob"))
    assert entry["released"] is True and entry["feedback"] == "Good work"
    assert [(c["name"], c["max_points"], c["score"], c["rationale"]) for c in entry["criteria"]] == [
        ("Data cleaning", 30, 12, "[cell 2] evidence"),
        ("Models", 50, None, ""),  # not scored
        ("Plots", 20, 18, "[cell 4] evidence"),  # override wins
    ]
    assert entry["criteria"][0]["description"] == CRITERIA[0]["description"]
    assert entry["total"] == 30 and entry["max_total"] == 100
    assert "private note" not in json.dumps(entry)

    # Alice is in the same assignment with her own submission: no scores yet.
    (alice,) = _student_rubrics(env, _student_token(env, "Alice"))
    assert [c["score"] for c in alice["criteria"]] == [None, None, None] and alice["feedback"] == ""

    # Hiding the release again hides the scores.
    with env.Session() as db:
        set_released(db, env.course.id, "hw2", False)
    assert "score" not in _student_rubrics(env, _student_token(env, "Bob"))[0]["criteria"][0]


def test_new_criteria_never_inherit_old_overrides(env):
    """SQLite can reuse the id of a deleted criterion; its results and
    overrides are deleted with it, so a new criterion starts clean. Copying
    or replacing a rubric starts clean too."""
    rubric = _author(env)
    sub = env.course.hw2_sub_ids[0]
    last = rubric["criteria"][-1]["id"]
    _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{last}/override", json={"score": 7}))
    rubric = _author(env, rubric["criteria"][:2])
    rubric = _author(env, [*rubric["criteria"], {"name": "Fresh", "max_points": 20}])
    assert _view(env, sub)["criteria"][2]["override"] is None

    first = rubric["criteria"][0]["id"]
    _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{first}/override", json={"score": 5}))
    _author(env, assignment_id=env.course.project_id)
    _ok(env.client.post(_rubric_url(env) + "/copy", json={"source_assignment_id": env.course.project_id}))
    assert all(c["override"] is None for c in _view(env, sub)["criteria"])
    _ok(env.client.delete(_rubric_url(env)))
    _author(env)
    assert all(c["override"] is None for c in _view(env, sub)["criteria"])
    with env.Session() as db:
        assert db.scalar(select(func.count()).select_from(CriterionOverride)) == 0


def test_deleting_a_submission_removes_its_criterion_rows(env):
    rubric = _author(env)
    sub = env.course.hw2_sub_ids[0]
    _ok(env.client.put(f"/api/submissions/{sub}/custom-rubric/{rubric['criteria'][0]['id']}/override", json={"score": 3}))
    _ok(env.client.delete(f"/api/submissions/{sub}"))
    with env.Session() as db:
        assert db.scalar(select(func.count()).select_from(CriterionOverride)) == 0


# ---------------------------------------------------------------------------
# No custom rubric: the fixed pipeline, unchanged
# ---------------------------------------------------------------------------


def test_without_a_rubric_scoring_is_exactly_as_before(env):
    """Same seed, same stubbed run as tests/fixtures/fixed_rubric_golden.json,
    which was produced on main before custom rubrics existed. A rubric on
    another course must not leak in either."""
    llm = FakeLLM(payload={}).install(env.monkeypatch)
    stub_autograder(env.monkeypatch, env.Session)
    with env.Session() as db:
        other = Course(code="Z", name="Z", year=2026, semester="Z")
        db.add(other)
        db.flush()
        other_hw2 = Assignment(course_id=other.id, workcode=2, name="HW2", assignment_type="HW2")
        db.add(other_hw2)
        db.commit()
        other_url = _rubric_url(env, other_hw2.id, other.id)
    _ok(env.client.put(other_url, json={"criteria": CRITERIA}))

    with env.Session() as db:
        assert json.loads(json.dumps(compute_gradebook_rows(db, env.course.id), default=str)) == GOLDEN["before"]
        r1 = queue_run(db, env.course.hw2_sub_ids[1])
        r2 = queue_run(db, env.course.project_sub_id)

    from app.tasks import jobs

    runs = [jobs.run_notebook(r1), jobs.run_notebook(r2)]
    assert [{**r, "run_id": None} for r in runs] == [{**r, "run_id": None} for r in GOLDEN["runs"]]
    with env.Session() as db:
        assert json.loads(json.dumps(compute_gradebook_rows(db, env.course.id), default=str)) == GOLDEN["after"]
        for key, sub_id in (("hw2", env.course.hw2_sub_ids[1]), ("project", env.course.project_sub_id)):
            snap = json.loads(json.dumps(fixed_pipeline_snapshot(db, sub_id)))
            assert snap == GOLDEN[key]
        assert db.scalar(select(func.count()).select_from(CriterionResult)) == 0
    assert llm.calls == []
    assert _ok(env.client.get(f"/api/submissions/{env.course.hw2_sub_ids[1]}"))["custom_rubric"] is None


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_round_trips(tmp_path):
    """0025 upgrades, downgrades to 0024 and upgrades again, on SQLite and (when
    TEST_DATABASE_URL is set) on Postgres."""
    urls = [f"sqlite:///{tmp_path / 'm.sqlite3'}"]
    if os.environ.get("TEST_DATABASE_URL"):
        from sqlalchemy import create_engine, text

        from app.core.config import sqlalchemy_database_url

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

        alembic("upgrade", "head")
        assert "0025_custom_rubrics (head)" in alembic("current")
        alembic("downgrade", "0024_lessons")
        assert "0024_lessons" in alembic("current")
        alembic("upgrade", "head")
        assert "0025_custom_rubrics (head)" in alembic("current")
