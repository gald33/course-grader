"""Custom rubrics: authoring per assignment, and per-criterion overrides on a
submission. Instructor routes (the auth middleware guards every /api path
outside the student prefixes)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Assignment, AssignmentRubric, Course, RubricCriterion, Submission
from app.services import custom_rubrics
from app.tasks.jobs import score_custom_rubric
from app.tasks.queue import enqueue

router = APIRouter(prefix="/api", tags=["rubrics"])


class CriterionLevelIn(BaseModel):
    points: float = Field(ge=0, le=1000)
    description: str = Field(min_length=1, max_length=2000)


class CriterionIn(BaseModel):
    id: int | None = None
    name: str = Field(max_length=255)
    description: str = Field(default="", max_length=5000)
    max_points: float = Field(gt=0, le=1000)
    levels: list[CriterionLevelIn] = Field(default_factory=list, max_length=10)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Criterion name is required")
        return v

    @model_validator(mode="after")
    def _levels_within_max(self) -> CriterionIn:
        if any(level.points > self.max_points for level in self.levels):
            raise ValueError(f"Level points exceed the criterion's maximum ({self.max_points:g})")
        self.levels = sorted(self.levels, key=lambda level: -level.points)
        return self


class RubricIn(BaseModel):
    criteria: list[CriterionIn] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def _unique_ids(self) -> RubricIn:
        ids = [c.id for c in self.criteria if c.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("A criterion appears twice")
        return self


class CopyIn(BaseModel):
    source_assignment_id: int


class OverrideIn(BaseModel):
    score: float = Field(ge=0)
    note: str = Field(default="", max_length=2000)


def _assignment(db: Session, course_id: int, assignment_id: int) -> Assignment:
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    assignment = db.get(Assignment, assignment_id)
    if assignment is None or assignment.course_id != course_id:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


def _require_scorable(assignment: Assignment) -> None:
    if assignment.assignment_type not in custom_rubrics.RUBRIC_ASSIGNMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Custom rubrics are for autograded assignments (HW2, PROJECT)",
        )


def _state(db: Session, assignment: Assignment) -> dict:
    return {
        "assignment": {
            "id": assignment.id,
            "name": assignment.name,
            "assignment_type": assignment.assignment_type,
            "workcode": assignment.workcode,
        },
        "supported": assignment.assignment_type in custom_rubrics.RUBRIC_ASSIGNMENT_TYPES,
        "rubric": custom_rubrics.serialize_rubric(db, custom_rubrics.get_rubric(db, assignment.id)),
    }


@router.get("/courses/{course_id}/assignments/{assignment_id}/rubric")
def get_rubric(course_id: int, assignment_id: int, db: Session = Depends(get_db)) -> dict:
    return _state(db, _assignment(db, course_id, assignment_id))


@router.put("/courses/{course_id}/assignments/{assignment_id}/rubric")
def put_rubric(course_id: int, assignment_id: int, payload: RubricIn, db: Session = Depends(get_db)) -> dict:
    """Create or replace the rubric: the criteria in order. Criteria sent with
    their id keep their scores and overrides; criteria left out are deleted."""
    assignment = _assignment(db, course_id, assignment_id)
    _require_scorable(assignment)
    try:
        custom_rubrics.save_criteria(db, assignment, [c.model_dump() for c in payload.criteria])
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _state(db, assignment)


@router.delete("/courses/{course_id}/assignments/{assignment_id}/rubric")
def delete_rubric(course_id: int, assignment_id: int, db: Session = Depends(get_db)) -> dict:
    """Back to the fixed rubric. Deletes the criteria, their scores and overrides."""
    assignment = _assignment(db, course_id, assignment_id)
    if not custom_rubrics.delete_rubric(db, assignment.id):
        raise HTTPException(status_code=404, detail="This assignment has no custom rubric")
    return _state(db, assignment)


@router.post("/courses/{course_id}/assignments/{assignment_id}/rubric/copy")
def copy_rubric(course_id: int, assignment_id: int, payload: CopyIn, db: Session = Depends(get_db)) -> dict:
    """Replace this assignment's rubric with a copy of another assignment's
    (from any course: rubrics are reused across semesters)."""
    assignment = _assignment(db, course_id, assignment_id)
    _require_scorable(assignment)
    if payload.source_assignment_id == assignment.id:
        raise HTTPException(status_code=400, detail="Pick a different assignment to copy from")
    source = custom_rubrics.get_rubric(db, payload.source_assignment_id)
    if source is None or not source.criteria:
        raise HTTPException(status_code=404, detail="That assignment has no custom rubric")
    custom_rubrics.copy_rubric(db, assignment, source)
    return _state(db, assignment)


@router.post("/courses/{course_id}/assignments/{assignment_id}/rubric/score")
def score_assignment(course_id: int, assignment_id: int, db: Session = Depends(get_db)) -> dict:
    """Queue LLM scoring of every submission that has an executed notebook,
    without re-running the notebooks. Overrides are kept."""
    assignment = _assignment(db, course_id, assignment_id)
    rubric = custom_rubrics.get_rubric(db, assignment.id)
    if rubric is None or not rubric.criteria:
        raise HTTPException(status_code=400, detail="This assignment has no custom rubric")
    queued = 0
    for submission in db.scalars(select(Submission).where(Submission.assignment_id == assignment.id)):
        if custom_rubrics.grading_run(db, submission) is not None:
            enqueue(db, score_custom_rubric, submission.id)
            queued += 1
    return {"status": "queued", "queued": queued}


@router.get("/courses/{course_id}/rubric-sources")
def rubric_sources(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Assignments with a custom rubric, this course's first, to copy from."""
    if db.get(Course, course_id) is None:
        raise HTTPException(status_code=404, detail="Course not found")
    rows = db.execute(
        select(AssignmentRubric, Assignment, Course)
        .join(Assignment, AssignmentRubric.assignment_id == Assignment.id)
        .join(Course, Assignment.course_id == Course.id)
    ).all()
    out = []
    for rubric, assignment, course in rows:
        if not rubric.criteria:
            continue
        out.append(
            {
                "assignment_id": assignment.id,
                "assignment_name": assignment.name,
                "assignment_type": assignment.assignment_type,
                "course_id": course.id,
                "course_label": f"{course.code} {course.year}/{course.semester}",
                "criteria_count": len(rubric.criteria),
                "total_points": round(sum(c.max_points for c in rubric.criteria), 4),
            }
        )
    out.sort(key=lambda r: (r["course_id"] != course_id, -r["course_id"], r["assignment_type"], r["assignment_name"]))
    return out


# ---------------------------------------------------------------------------
# Per-submission
# ---------------------------------------------------------------------------


def _submission_criterion(db: Session, submission_id: int, criterion_id: int) -> tuple[Submission, RubricCriterion]:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    rubric = custom_rubrics.get_rubric(db, submission.assignment_id)
    criterion = db.get(RubricCriterion, criterion_id)
    if rubric is None or criterion is None or criterion.rubric_id != rubric.id:
        raise HTTPException(status_code=404, detail="Criterion not found for this submission")
    return submission, criterion


@router.put("/submissions/{submission_id}/custom-rubric/{criterion_id}/override")
def put_override(submission_id: int, criterion_id: int, payload: OverrideIn, db: Session = Depends(get_db)) -> dict:
    submission, criterion = _submission_criterion(db, submission_id, criterion_id)
    if payload.score > criterion.max_points:
        raise HTTPException(status_code=400, detail=f"Score must be between 0 and {criterion.max_points:g}")
    custom_rubrics.set_override(db, submission, criterion, payload.score, payload.note.strip())
    return custom_rubrics.submission_view(db, submission)


@router.delete("/submissions/{submission_id}/custom-rubric/{criterion_id}/override")
def delete_override(submission_id: int, criterion_id: int, db: Session = Depends(get_db)) -> dict:
    submission, criterion = _submission_criterion(db, submission_id, criterion_id)
    custom_rubrics.clear_override(db, submission, criterion)
    return custom_rubrics.submission_view(db, submission)


@router.post("/submissions/{submission_id}/custom-rubric/score")
def score_submission(submission_id: int, db: Session = Depends(get_db)) -> dict:
    """Queue LLM scoring of this submission's latest executed notebook."""
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    rubric = custom_rubrics.get_rubric(db, submission.assignment_id)
    if rubric is None or not rubric.criteria:
        raise HTTPException(status_code=400, detail="This assignment has no custom rubric")
    if custom_rubrics.grading_run(db, submission) is None:
        raise HTTPException(status_code=400, detail="Run the notebook first: there is no executed notebook to score")
    job_id = enqueue(db, score_custom_rubric, submission.id)
    return {"status": "queued", "job_id": job_id}
