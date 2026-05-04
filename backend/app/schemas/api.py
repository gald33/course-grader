from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class CourseCreate(BaseModel):
    code: str
    name: str
    year: int
    semester: str
    attendance_threshold: float = 80


class CourseRead(BaseModel):
    id: int
    code: str
    name: str
    year: int
    semester: str
    attendance_threshold: float

    model_config = {"from_attributes": True}


class AttendanceThresholdUpdate(BaseModel):
    threshold: float = Field(ge=0, le=100)


class SnapshotCreate(BaseModel):
    url: HttpUrl


class SnapshotRead(BaseModel):
    id: int
    submission_id: int
    url: str
    status: str
    content_hash: str | None = None
    fetched_at: datetime | None = None
    artifact_id: int | None = None
    error_message: str = ""

    model_config = {"from_attributes": True}


class RunCreate(BaseModel):
    mode: str = Field(default="snapshot", pattern="^(snapshot|latest)$")
    snapshot_id: int | None = None


class RunRead(BaseModel):
    id: int
    submission_id: int
    snapshot_id: int
    status: str
    mode: str
    ok_cells: int
    failed_cells: int
    run_ratio: float
    penalty_multiplier: float
    error_summary: str
    executed_notebook_artifact_id: int | None = None
    executed_html_artifact_id: int | None = None
    log_artifact_id: int | None = None
    is_pinned: bool
    started_at: datetime | None = None
    ended_at: datetime | None = None

    model_config = {"from_attributes": True}


class RubricDimensionIn(BaseModel):
    component: str
    dimension_key: str
    raw_score: float = Field(ge=0, le=5)


class RubricBulkUpdate(BaseModel):
    dimensions: list[RubricDimensionIn]


class RubricDimensionRead(BaseModel):
    component: str
    dimension_key: str
    raw_score: float
    adjusted_score: float


class OverrideCreate(BaseModel):
    student_id: int
    submission_id: int | None = None
    component: str
    delta: float
    reason: str = Field(min_length=1)


class PresentationImportResult(BaseModel):
    imported_rows: int
    bonus_updates: int


class CurveDimension(BaseModel):
    points: list[float] = Field(min_length=6, max_length=6)
    tunable: bool = True


class CurveRevisionIn(BaseModel):
    note: str = ""
    mapping: dict[str, CurveDimension]


class CurveRevisionRead(BaseModel):
    id: int
    revision_number: int
    note: str
    mapping: dict[str, CurveDimension]
    created_at: datetime


class SubmissionRequirements(BaseModel):
    """Per-assignment-type completeness check.

    HW1 — needs a PDF file.
    HW2 — needs a Colab URL we can fetch.
    PROJECT — needs both a PDF file and a Colab URL.

    The `missing_report_flag` / `missing_data_flag` are manual grader overrides
    — useful when a file exists but doesn't actually contain the expected
    report/data, or when the auto-check is wrong.
    """

    needs_pdf: bool
    needs_colab: bool
    has_pdf: bool
    has_colab_url: bool
    has_fetched_colab: bool
    missing_report_flag: bool = False
    missing_data_flag: bool = False
    missing_code_flag: bool = False
    missing: list[str]
    complete: bool
    overridden_by_manual_grade: bool = False


class MissingFlagsUpdate(BaseModel):
    missing_report_flag: bool | None = None
    missing_data_flag: bool | None = None
    missing_code_flag: bool | None = None


class ManualGradeUpdate(BaseModel):
    """Set or clear a manual final grade for this submission.

    When set (0–100), this overrides the rubric-derived component score for
    every member of this submission's group. Pass null to clear.
    """

    manual_grade: float | None = None


class SubmissionRead(BaseModel):
    id: int
    course_id: int
    assignment_id: int
    assignment_type: str
    workcode: int
    group_identifier: str
    member_student_ids: list[int]
    member_ids: list[str]
    member_names: list[str]
    originality_score_filename: float | None
    originality_score_pdf: float | None
    originality_mismatch: bool
    pinned_run_id: int | None
    last_run_status: str | None = None
    last_run_ratio: float | None = None
    has_colab_url: bool = False
    rubric_filled: int = 0
    rubric_total: int = 0
    requirements: SubmissionRequirements | None = None
    manual_grade: float | None = None


class ArtifactRead(BaseModel):
    id: int
    kind: str
    filename: str
    mime_type: str | None
    size_bytes: int


class SubmissionDetail(BaseModel):
    submission: SubmissionRead
    snapshots: list[SnapshotRead]
    runs: list[RunRead]
    rubric: list[RubricDimensionRead]
    private_notes: str
    student_feedback: str
    consistency_summary: str
    consistency_flags: list[str]
    report_pdf_artifact_id: int | None
    executed_html_artifact_id: int | None
    artifacts: list[ArtifactRead] = []


class NotesUpdate(BaseModel):
    notes_private: str = ""
    feedback_student: str = ""


class GradebookRow(BaseModel):
    enrollment_id: int
    student_id: int
    national_id: str
    name: str
    attendance_exempt: bool
    attendance_percent: float | None
    attendance_score: float
    hw1: float
    hw2: float
    project_code: float
    project_report: float
    initial_talk: float
    final_talk: float
    project_base: float
    bonus_points: float
    project_with_bonus: float
    final: float
    overrides: dict[str, float]


class GradebookResponse(BaseModel):
    rows: list[GradebookRow]


class AttendanceExemptUpdate(BaseModel):
    attendance_exempt: bool


class BonusUpdate(BaseModel):
    bonus_points: float
