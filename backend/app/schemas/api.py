from __future__ import annotations

from datetime import date, datetime

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
    archived_at: datetime | None = None

    model_config = {"from_attributes": True}


class CourseUpdate(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    year: int | None = Field(default=None, ge=2000, le=2100)
    semester: str | None = Field(default=None, min_length=1, max_length=64)


class SubmissionMembersUpdate(BaseModel):
    student_ids: list[int] = Field(min_length=1)


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
    # Manual writes default to approved=True (the grader actively chose this
    # score). LLM auto-apply explicitly passes False.
    approved: bool = True


class RubricBulkUpdate(BaseModel):
    dimensions: list[RubricDimensionIn]


class RubricApprovalUpdate(BaseModel):
    component: str
    dimension_key: str
    approved: bool


class RubricDimensionRead(BaseModel):
    component: str
    dimension_key: str
    raw_score: float
    adjusted_score: float
    approved: bool = True


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


class FinalDistribution(BaseModel):
    mean: float
    sigma: float


class CurveRevisionRead(BaseModel):
    id: int
    revision_number: int
    note: str
    mapping: dict[str, CurveDimension]
    final_distribution: FinalDistribution | None = None
    shared_bonus: float = 0.0
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


class LLMReviewDimension(BaseModel):
    score: int
    rationale: str


class LLMReviewRead(BaseModel):
    model: str
    dimensions: dict[str, LLMReviewDimension]
    feedback_he: str
    usage: dict[str, int] = {}


class CodeReviewDimension(BaseModel):
    """Per-dimension explanation for the code rubric (auto or LLM-sourced)."""

    score: float
    rationale: str
    source: str  # "auto" | "claude"


class CodeReviewRead(BaseModel):
    component: str  # "hw2_code" | "project_code"
    dimensions: dict[str, CodeReviewDimension]


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
    llm_review: LLMReviewRead | None = None
    code_review: CodeReviewRead | None = None


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
    presentation: float
    final_talk: float
    project_base: float
    bonus_points: float
    project_with_bonus: float
    final: float
    final_uncurved: float
    overrides: dict[str, float]


class GradebookResponse(BaseModel):
    rows: list[GradebookRow]


class AttendanceExemptUpdate(BaseModel):
    attendance_exempt: bool


# ---------------------------------------------------------------------------
# Peer review
# ---------------------------------------------------------------------------


class SessionUpdate(BaseModel):
    held_on: date | None = None
    title: str | None = None


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    project_title: str = Field(default="", max_length=255)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    project_title: str | None = Field(default=None, max_length=255)


class TeamSettingsIn(BaseModel):
    teams_open: bool | None = None
    max_team_size: int | None = Field(default=None, ge=1, le=50)
    teams_deadline: datetime | None = None
    clear_teams_deadline: bool = False


class StudentTeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    project_title: str = Field(default="", max_length=255)


class StudentTeamJoin(BaseModel):
    code: str = Field(min_length=4, max_length=16)


class StudentTeamUpdate(BaseModel):
    team_id: int | None = None


class RubricCriterionIn(BaseModel):
    key: str = ""
    label: str
    description: str = ""
    weight: float = 1.0
    counts: bool = True
    max: float | None = None  # number score 0..max instead of the scale


class RubricScalePointIn(BaseModel):
    value: int
    label: str = ""


class RubricPromptIn(BaseModel):
    key: str = ""
    label: str
    required: bool = False


class RubricSave(BaseModel):
    criteria: list[RubricCriterionIn]
    scale: list[RubricScalePointIn]
    prompts: list[RubricPromptIn] = Field(default_factory=list)
    instructions: str = ""


class RoundSessionIn(BaseModel):
    number: int = Field(ge=1, le=99)
    capacity: int = Field(ge=0, le=50)


class RoundUpdate(BaseModel):
    title: str | None = None
    sessions: list[RoundSessionIn] | None = None
    selection_deadline: datetime | None = None
    clear_selection_deadline: bool = False
    review_deadline: datetime | None = None
    clear_review_deadline: bool = False
    target_mean: float | None = Field(default=None, ge=0, le=100)
    target_std: float | None = Field(default=None, ge=0, le=50)
    missing_review_policy: str | None = Field(default=None, pattern="^(missing|zero)$")
    link_required: bool | None = None
    participation_factor: bool | None = None
    llm_enabled: bool | None = None


class SessionReviewToggle(BaseModel):
    open: bool


class PresentationUpdate(BaseModel):
    move: bool = False
    session_number: int | None = None
    postpone: bool = False
    reason: str = ""
    demo_url: str | None = Field(default=None, max_length=2000)
    materials_text: str | None = Field(default=None, max_length=20000)
    review_open: bool | None = None


class SwapRequest(BaseModel):
    a_id: int
    b_id: int
    reason: str = ""


class ReviewExclusion(BaseModel):
    excluded: bool
    reason: str = ""


class ExemptionUpdate(BaseModel):
    student_id: int
    presentation_ids: list[int] | None = None
    session_number: int | None = None
    exempt: bool
    reason: str = ""


class StudentReviewIn(BaseModel):
    scores: dict[str, int | float]
    responses: dict[str, str] = Field(default_factory=dict)


class StudentSessionChoice(BaseModel):
    session_number: int


class StudentMaterialsIn(BaseModel):
    demo_url: str | None = Field(default=None, max_length=2000)
    materials_text: str | None = Field(default=None, max_length=20000)


class StudentTeamIn(BaseModel):
    project_title: str = Field(max_length=255)


class InstructorSessionIn(BaseModel):
    token: str


class UploadedFileIn(BaseModel):
    """A file the browser uploaded straight to Storage (signed upload URL)."""

    key: str = Field(min_length=1, max_length=512)
    filename: str = Field(default="", max_length=255)


class PracticeRoundIn(BaseModel):
    title: str = Field(default="Practice round (not graded)", max_length=255)
    open_now: bool = True
