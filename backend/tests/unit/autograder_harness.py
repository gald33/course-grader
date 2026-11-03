"""Drives the autograder job (run_notebook) against a test database with the
notebook execution and the fixed-rubric LLM call stubbed out, and seeds a
small course for gradebook checks.

Uses only what existed before custom rubrics, so the same seeding and run
reproduce the fixed pipeline's results on older code (the regression test's
expected values come from running it there)."""

from __future__ import annotations

from types import SimpleNamespace

import nbformat
from sqlalchemy import select

from app.models.entities import (
    Artifact,
    Assignment,
    ColabSnapshot,
    Course,
    Enrollment,
    NotebookRun,
    RubricDimensionScore,
    Student,
    Submission,
    SubmissionMember,
)
from app.services import storage
from app.services.notebook_runner import NotebookExecutionResult, serialize_notebook

FIXED_LLM_SCORES = {
    "processing_description": {"score": 3, "rationale": "הסבר חלקי על העיבוד"},
    "models_quality": {"score": 4, "rationale": "בחירת מודלים סבירה"},
}


def sample_notebook() -> nbformat.NotebookNode:
    nb = nbformat.v4.new_notebook()
    nb.cells = [
        nbformat.v4.new_markdown_cell("# Titanic survival\nWe drop rows with missing age because they are few."),
        nbformat.v4.new_code_cell(
            "import pandas as pd\n"
            "import matplotlib.pyplot as plt\n"
            "# load the data\n"
            "df = pd.read_csv('data.csv')\n"
            "df = df.dropna()\n"
            "df['Age'].hist()\n"
            "plt.show()",
            outputs=[nbformat.v4.new_output("stream", name="stdout", text="891 rows\n")],
        ),
        nbformat.v4.new_code_cell(
            "from sklearn.linear_model import LogisticRegression\n"
            "from sklearn.ensemble import RandomForestClassifier\n"
            "from sklearn.tree import DecisionTreeClassifier\n"
            "# compare three models\n"
            "for m in [LogisticRegression(), RandomForestClassifier(), DecisionTreeClassifier()]:\n"
            "    m.fit(X_train, y_train)\n"
            "    print(m.score(X_test, y_test))",
            outputs=[
                nbformat.v4.new_output("error", ename="NameError", evalue="name 'X_train' is not defined", traceback=[])
            ],
        ),
    ]
    return nb


def stub_autograder(monkeypatch, session_factory, *, fixed_llm=True) -> None:
    """Point the job module at the test database and stub what needs a kernel
    or the network."""
    from app.tasks import jobs

    nb = sample_notebook()
    monkeypatch.setattr(jobs, "SessionLocal", session_factory)
    monkeypatch.setattr(jobs, "_stage_data_files", lambda db, submission_id, target_dir: None)
    monkeypatch.setattr(
        jobs, "auto_install_missing", lambda path: SimpleNamespace(discovered=[], attempts=[], log="")
    )
    monkeypatch.setattr(
        jobs,
        "execute_notebook",
        lambda path, total_timeout_seconds, penalty_power: NotebookExecutionResult(
            ok_cells=1,
            failed_cells=1,
            run_ratio=0.5,
            penalty_multiplier=round(0.5**penalty_power, 6),
            timed_out=False,
            error_summary="NameError",
            executed_notebook=nb,
            html="<html></html>",
            logs="",
        ),
    )

    def fixed_review(notebook_text):
        if not fixed_llm:
            raise jobs.LLMCodeReviewError("disabled in tests")
        return SimpleNamespace(model="stub", scores=FIXED_LLM_SCORES, usage={})

    monkeypatch.setattr(jobs, "review_code_dimensions", fixed_review)


def queue_run(db, submission_id: int) -> int:
    """A fetched snapshot of the sample notebook and a queued run for it."""
    location = storage.save(f"snapshots/{submission_id}/nb.ipynb", serialize_notebook(sample_notebook()), "application/x-ipynb+json")
    art = Artifact(submission_id=submission_id, kind="colab_snapshot", filename="nb.ipynb", path=location)
    db.add(art)
    db.flush()
    snap = ColabSnapshot(submission_id=submission_id, url="https://colab.research.google.com/x", status="PUBLIC_FETCHED", artifact_id=art.id)
    db.add(snap)
    db.flush()
    run = NotebookRun(submission_id=submission_id, snapshot_id=snap.id, status="QUEUED")
    db.add(run)
    db.commit()
    return run.id


def seed_course(db) -> SimpleNamespace:
    """Two students; one HW2 submission each and a shared PROJECT, with
    fixed-rubric scores, a run (penalty) and a non-identity curve."""
    from app.services.scoring import CODE_DIMENSIONS, REPORT_DIMENSIONS, default_curve_mapping, save_curve_revision

    course = Course(code="AI", name="Applied AI", year=2026, semester="A", attendance_threshold=80)
    db.add(course)
    db.flush()
    hw2 = Assignment(course_id=course.id, workcode=2, name="HW2", assignment_type="HW2")
    project = Assignment(course_id=course.id, workcode=3, name="Project", assignment_type="PROJECT")
    db.add_all([hw2, project])
    db.flush()

    students = []
    for nid, name in (("100000001", "Alice"), ("100000002", "Bob")):
        s = Student(national_id=nid, name=name)
        db.add(s)
        db.flush()
        db.add(Enrollment(course_id=course.id, student_id=s.id, attendance_percent=90.0))
        students.append(s)

    hw2_subs = []
    for i, s in enumerate(students):
        sub = Submission(course_id=course.id, assignment_id=hw2.id, group_identifier=s.national_id)
        db.add(sub)
        db.flush()
        db.add(SubmissionMember(submission_id=sub.id, student_id=s.id))
        for j, dim in enumerate(CODE_DIMENSIONS):
            raw = float((i + j) % 6)
            db.add(RubricDimensionScore(submission_id=sub.id, component="hw2_code", dimension_key=dim.key, raw_score=raw, adjusted_score=raw))
        hw2_subs.append(sub)

    proj = Submission(course_id=course.id, assignment_id=project.id, group_identifier="team")
    db.add(proj)
    db.flush()
    for s in students:
        db.add(SubmissionMember(submission_id=proj.id, student_id=s.id))
    for j, dim in enumerate(CODE_DIMENSIONS):
        db.add(RubricDimensionScore(submission_id=proj.id, component="project_code", dimension_key=dim.key, raw_score=float(j % 5 + 1), adjusted_score=0))
    for j, dim in enumerate(REPORT_DIMENSIONS):
        db.add(RubricDimensionScore(submission_id=proj.id, component="project_report", dimension_key=dim.key, raw_score=float(j % 4 + 2), adjusted_score=0))
    db.add(Artifact(submission_id=proj.id, kind="project_report_pdf", filename="r.pdf", path="/nonexistent/r.pdf"))
    db.commit()

    # Runs set the penalty: HW2 of Alice ran 80% of its cells, the project 60%.
    for sub, pm in ((hw2_subs[0], 0.8), (proj, 0.6)):
        snap = ColabSnapshot(submission_id=sub.id, url="https://colab.research.google.com/x", status="PUBLIC_FETCHED")
        db.add(snap)
        db.flush()
        db.add(NotebookRun(submission_id=sub.id, snapshot_id=snap.id, status="SUCCESS", penalty_multiplier=pm, run_ratio=pm))
    db.commit()

    mapping = default_curve_mapping()
    for cfg in mapping.values():
        cfg["points"] = [0, 1.5, 2.5, 3.5, 4.5, 5]
    save_curve_revision(db, course.id, mapping, "test curve")
    from app.services.scoring import recalculate_submission_adjusted_scores

    for sub_id in db.scalars(select(Submission.id).where(Submission.course_id == course.id)):
        recalculate_submission_adjusted_scores(db, course.id, sub_id)
    return SimpleNamespace(
        id=course.id,
        hw2_id=hw2.id,
        project_id=project.id,
        hw2_sub_ids=[s.id for s in hw2_subs],
        project_sub_id=proj.id,
    )


def fixed_pipeline_snapshot(db, submission_id: int) -> dict:
    """What the fixed pipeline stored for a submission."""
    sub = db.get(Submission, submission_id)
    rows = db.scalars(
        select(RubricDimensionScore)
        .where(RubricDimensionScore.submission_id == submission_id)
        .order_by(RubricDimensionScore.component, RubricDimensionScore.dimension_key)
    ).all()
    return {
        "scores": [(r.component, r.dimension_key, r.raw_score, round(r.adjusted_score, 6), r.approved) for r in rows],
        "code_review_json": sub.code_review_json,
    }
