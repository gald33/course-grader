"""Guided lessons domain logic: installing and publishing lesson versions,
student progress (pinned to a version, revision-checked), answer attempts and
their feedback, experiment records, commitments and final-test results,
completion, and the instructor's insights. API handlers stay thin and call in
here.

Answer keys never leave the server except as feedback: students get content
through sanitize_for_student() and see answer-key text only via feedback_for(),
for a question they answered or revealed. Completion is computed from evidence
(attempts, acknowledgements, experiments, commitments), never reported by the
client; viewing a step is "viewed", never "completed".
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from posixpath import dirname
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.lessons import (
    FIXTURES,
    ContentError,
    assets_root,
    canonical_hash,
    load_fixture,
    question_hash,
    sanitize_for_student,
    validate_content,
)
from app.lessons.schema import (
    MAX_DEPTH,
    MAX_TRAINING_EXAMPLES,
    MIN_TRAINING_EXAMPLES,
    Answer,
    AttemptInput,
    CommitmentInput,
    ExperimentInput,
    FinalInput,
    ProgressPatch,
    iter_blocks,
)
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
from app.services.peer_review import utcnow

MAX_EXPERIMENTS = 30
# Per student and lesson, so one student can't flood the instructor's
# insights: rows ever created (deleted experiments included), answers and
# reveals per question, commitments.
MAX_EXPERIMENT_ROWS = 100
MAX_ANSWERS_PER_QUESTION = 20
MAX_REVEALS_PER_QUESTION = 20
MAX_COMMITMENTS = 20
MAX_TEXT = 5000
MIN_EXPLANATION = 10
MIN_JUSTIFICATION = 10
MAX_DRAFT_KEYS = 200
MAX_DRAFT_KEY_CHARS = 100
MAX_DRAFT_CHARS = 20000
MAX_DRAFTS_BYTES = 200 * 1024
COLAB_HOSTS = ("colab.research.google.com", "drive.google.com")
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
RUN_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

# Student-facing messages (the lesson pages are Hebrew).
MSG = {
    "invalid": "ערך לא תקין",
    "number": "הזינו מספר",
    "invalid_values": "חלק מהערכים אינם תקינים — תקנו את השדות המסומנים",
    "lesson_not_found": "השיעור לא נמצא",
    "stale": "הנתונים עודכנו בלשונית או במכשיר אחר",
    "experiment_gone": "הריצה הזו נמחקה בלשונית או במכשיר אחר",
    "question_not_found": "השאלה לא נמצאה בשיעור",
    "request_id": "מזהה בקשה לא תקין",
    "request_reused": "מזהה הבקשה כבר שימש לפעולה אחרת",
    "answer_first": "קודם עונים לבד — אחר כך אפשר לראות את ההסבר",
    "step": "שלב לא מוכר בשיעור",
    "ack": "סימון לא מוכר בשיעור",
    "draft_key": "שם טיוטה לא תקין",
    "draft_long": "הטיוטה ארוכה מדי (עד 20,000 תווים)",
    "drafts_many": "יותר מדי טיוטות שמורות",
    "drafts_big": "הטיוטות השמורות גדולות מדי",
    "choice": "בחרו אחת מהאפשרויות",
    "explain": "כתבו הסבר קצר במילים שלכם (10 תווים לפחות)",
    "text_required": "כתבו תשובה לפני השליחה",
    "text_min": "כתבו לפחות {n} תווים",
    "too_long": "הטקסט ארוך מדי (עד 5,000 תווים)",
    "run_uuid": "מזהה ריצה לא תקין",
    "run_unknown": "הריצה שנבחרה לא נמצאה ביומן הניסויים שלכם",
    "depth_kind": "בחרו עומק מהרשימה",
    "depth_kind_required": "בחרו עומק",
    "depth_without_kind": "בחרו קודם את סוג העומק",
    "depth_required": f"הזינו עומק (מספר שלם בין 1 ל-{MAX_DEPTH})",
    "depth": f"העומק חייב להיות מספר שלם בין 1 ל-{MAX_DEPTH}",
    "depth_zero": "בקולאב 0 פירושו עומק ללא הגבלה — בחרו \"ללא הגבלה\" במקום 0",
    "depth_unlimited": "בעומק ללא הגבלה לא מזינים מספר",
    "training_examples": (
        f"מספר דוגמאות האימון חייב להיות מספר שלם בין {MIN_TRAINING_EXAMPLES} ל-{MAX_TRAINING_EXAMPLES}"
    ),
    "training_examples_required": f"הזינו את מספר דוגמאות האימון ({MIN_TRAINING_EXAMPLES}–{MAX_TRAINING_EXAMPLES})",
    "pct": "הזינו אחוז בין 0 ל-100",
    "pct_required": "הזינו את הדיוק באחוזים (0–100)",
    "empty_run": "כתבו לפחות השערה או הגדרות ריצה לפני השמירה",
    "too_many_experiments": f"אפשר לשמור עד {MAX_EXPERIMENTS} ריצות בשיעור",
    "too_many_experiment_rows": f"אפשר ליצור עד {MAX_EXPERIMENT_ROWS} ריצות בשיעור, כולל ריצות שנמחקו",
    "too_many_attempts": f"אפשר לשלוח עד {MAX_ANSWERS_PER_QUESTION} תשובות לשאלה הזו",
    "too_many_commitments": f"אפשר לשמור עד {MAX_COMMITMENTS} בחירות בשיעור",
    "run_reused": "מזהה הריצה כבר שימש בשיעור אחר",
    "experiment_not_found": "הריצה לא נמצאה",
    "justification": f"כתבו נימוק של {MIN_JUSTIFICATION} תווים לפחות",
    "commitment_not_found": "הבחירה לא נמצאה",
    "final_already_recorded": "תוצאת המבחן הסופי כבר נשמרה לבחירה הזו",
}


class LessonError(Exception):
    """Domain error with a stable code; `extra` goes into the error detail
    (fields, current, steps, errors)."""

    def __init__(self, code: str, message: str, status_code: int = 400, **extra: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.extra = extra


def invalid_values(fields: dict[str, str]) -> LessonError:
    return LessonError("invalid_values", MSG["invalid_values"], 422, fields=fields)


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# Content helpers (content is the stored fixture dict, answer keys included)
# ---------------------------------------------------------------------------


def content_of(version: LessonVersion) -> dict:
    return json.loads(version.content_json)


def step_keys(content: dict) -> list[str]:
    return [s["key"] for s in content["steps"]]


def ack_keys(content: dict) -> list[str]:
    keys: list[str] = []
    for step in content["steps"]:
        for block, _ in iter_blocks(step["blocks"]):
            if block["type"] == "ack" and block["key"] not in keys:
                keys.append(block["key"])
    return keys


def ordered_questions(content: dict) -> list[dict]:
    """Questions in the order the lesson shows them."""
    keys: list[str] = []
    for step in content["steps"]:
        for block, _ in iter_blocks(step["blocks"]):
            if block["type"] == "question" and block["question"] in content["questions"]:
                if block["question"] not in keys:
                    keys.append(block["question"])
    keys += [k for k in content["questions"] if k not in keys]
    return [content["questions"][k] for k in keys]


def asset_base(content: dict) -> str:
    """The directory the lesson's assets are served from, e.g. /lessons/lesson-2/v1."""
    dirs = sorted({dirname(a["path"]) for a in content.get("assets", {}).values()})
    if not dirs:
        return ""
    base = dirs[0]
    while any(d != base and not d.startswith(base.rstrip("/") + "/") for d in dirs):
        base = dirname(base)
    return base


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


def version_view(version: LessonVersion) -> dict:
    return {
        "id": version.id,
        "number": version.number,
        "content_hash": version.content_hash,
        "published_at": iso(version.published_at),
    }


def progress_view(progress: LessonProgress | None) -> dict | None:
    if progress is None:
        return None
    return {
        "revision": progress.revision,
        "current_step_key": progress.current_step_key,
        "viewed": json.loads(progress.viewed_json or "[]"),
        "acks": json.loads(progress.acks_json or "[]"),
        "drafts": json.loads(progress.drafts_json or "{}"),
        "started_at": iso(progress.started_at),
        "updated_at": iso(progress.updated_at),
        "completed_at": iso(progress.completed_at),
    }


def experiment_complete(row: LessonExperiment) -> bool:
    """Settings, all three results and an observation are recorded."""
    settings = row.depth_kind == "unlimited" or (row.depth_kind == "limited" and row.depth is not None)
    return (
        settings
        and row.training_examples is not None
        and row.train_accuracy is not None
        and row.validation_accuracy is not None
        and row.baseline_validation is not None
        and bool((row.observation or "").strip())
    )


def experiment_view(row: LessonExperiment, include_deleted: bool = False) -> dict:
    view = {
        "run_uuid": row.run_uuid,
        "revision": row.revision,
        "depth_kind": row.depth_kind,
        "depth": row.depth,
        "training_examples": row.training_examples,
        "train_accuracy": row.train_accuracy,
        "validation_accuracy": row.validation_accuracy,
        "baseline_validation": row.baseline_validation,
        "hypothesis": row.hypothesis,
        "observation": row.observation,
        "explanation": row.explanation,
        "provenance": row.provenance,
        "complete": experiment_complete(row),
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }
    if include_deleted:  # the instructor's view
        view["deleted_at"] = iso(row.deleted_at)
        # The prediction as first saved: a later edit (e.g. together with the
        # results) changes `hypothesis` but never this.
        view["first_hypothesis"] = row.first_hypothesis
        view["first_hypothesis_at"] = iso(row.first_hypothesis_at)
    return view


def commitment_view(row: LessonCommitment) -> dict:
    return {
        "id": row.id,
        "run_uuid": row.run_uuid,
        "depth_kind": row.depth_kind,
        "depth": row.depth,
        "training_examples": row.training_examples,
        "justification": row.justification,
        "committed_at": iso(row.committed_at),
        "after_final_seen": row.after_final_seen,
        "final": (
            {
                "accuracy": row.final_accuracy,
                "precision": row.final_precision,
                "recall": row.final_recall,
                "note": row.final_note,
                "recorded_at": iso(row.final_recorded_at),
            }
            if row.final_recorded_at is not None
            else None
        ),
    }


def _answer(row: LessonAttempt) -> dict | None:
    return json.loads(row.answer_json) if row.answer_json else None


# ---------------------------------------------------------------------------
# Feedback (the only way answer-key text reaches a student)
# ---------------------------------------------------------------------------


def is_correct(question: dict, answer: dict | None) -> bool | None:
    if question["type"] != "single_choice" or not answer or answer.get("choice") is None:
        return None
    return answer["choice"] in question["answer"]["correct"]


def feedback_for(question: dict, answer: dict | None, *, reveal: bool) -> dict:
    """Feedback for an answer, or for a reveal (answer = the latest answer,
    if any). Practice: a wrong answer gets only its option's message; a
    correct answer, a reveal, or any check-mode answer also gets the
    explanation and the correct options. Free text is never graded."""
    key = question["answer"]
    if question["type"] == "free_text":
        return {"correct": None, "sample_reasoning": list(key["sample_reasoning"]), "rubric": list(key["rubric"])}
    correct = is_correct(question, answer)
    feedback: dict = {"correct": correct}
    if correct is not None:
        feedback["message"] = key["feedback"].get(answer["choice"], "")
    if correct or reveal or question["mode"] == "check":
        feedback["explanation"] = key["explanation"]
        feedback["correct_options"] = list(key["correct"])
    return feedback


def question_state(question: dict, rows: list[LessonAttempt]) -> dict:
    """QuestionState for one student; rows are their attempts at it, oldest first."""
    answers = [r for r in rows if r.kind == "answer"]
    first = answers[0] if answers else None
    latest = answers[-1] if answers else None
    feedback = None
    if rows:
        feedback = feedback_for(question, _answer(latest) if latest else None, reveal=rows[-1].kind == "reveal")
    return {
        "attempts": len(answers),
        "revealed": any(r.kind == "reveal" for r in rows),
        "first": (
            {"answer": _answer(first), "correct": first.correct, "submitted_at": iso(first.submitted_at)}
            if first
            else None
        ),
        "latest": (
            {
                "answer": _answer(latest),
                "correct": latest.correct,
                "submitted_at": iso(latest.submitted_at),
                "attempt_number": latest.attempt_number,
            }
            if latest
            else None
        ),
        "feedback": feedback,
    }


def clean_answer(question: dict, answer: Answer) -> dict:
    """The answer as stored, or invalid_values."""
    fields: dict[str, str] = {}
    text = (answer.text or "").strip()
    if question["type"] == "single_choice":
        ids = [o["id"] for o in question["options"]]
        explain = question.get("explain") or "none"
        if answer.choice not in ids:
            fields["choice"] = MSG["choice"]
        if len(text) > MAX_TEXT:
            fields["text"] = MSG["too_long"]
        elif explain == "required" and len(text) < MIN_EXPLANATION:
            fields["text"] = MSG["explain"]
        clean = {"choice": answer.choice}
        if text and explain != "none":
            clean["text"] = text
    else:
        min_chars = max(1, question.get("min_chars") or 1)
        if not text:
            fields["text"] = MSG["text_required"]
        elif len(text) > MAX_TEXT:
            fields["text"] = MSG["too_long"]
        elif len(text) < min_chars:
            fields["text"] = MSG["text_min"].format(n=min_chars)
        clean = {"text": text}
    if fields:
        raise invalid_values(fields)
    return clean


# ---------------------------------------------------------------------------
# Completion (mirrors frontend/components/lessons/completion.ts)
# ---------------------------------------------------------------------------


@dataclass
class Evidence:
    viewed: set[str] = field(default_factory=set)
    acks: set[str] = field(default_factory=set)
    answered: set[str] = field(default_factory=set)  # questions with at least one answer
    complete_experiments: int = 0
    commitments: int = 0


def evidence_from(
    progress: LessonProgress | None,
    attempts: list[LessonAttempt],
    experiments: list[LessonExperiment],
    commitments: list[LessonCommitment],
) -> Evidence:
    return Evidence(
        viewed=set(json.loads(progress.viewed_json or "[]")) if progress else set(),
        acks=set(json.loads(progress.acks_json or "[]")) if progress else set(),
        answered={a.question_key for a in attempts if a.kind == "answer"},
        complete_experiments=sum(1 for e in experiments if e.deleted_at is None and experiment_complete(e)),
        commitments=len(commitments),
    )


def _rule_done(rule: dict, ev: Evidence) -> bool:
    kind = rule["type"]
    if kind == "answered":
        return rule["question"] in ev.answered
    if kind == "ack":
        return rule["key"] in ev.acks
    if kind == "experiments":
        return ev.complete_experiments >= rule["min_complete"]
    if kind == "commitment":
        return ev.commitments > 0
    return False


def compute_steps(content: dict, ev: Evidence) -> dict[str, dict]:
    steps = {}
    for step in content["steps"]:
        rules = step["completion"]
        done = sum(1 for rule in rules if _rule_done(rule, ev))
        steps[step["key"]] = {
            "viewed": step["key"] in ev.viewed,
            "completed": bool(rules) and done == len(rules),
            "done": done,
            "total": len(rules),
        }
    return steps


def required_progress(content: dict, steps: dict[str, dict]) -> tuple[int, int]:
    required = [s["key"] for s in content["steps"] if not s.get("optional")]
    return sum(1 for k in required if steps[k]["completed"]), len(required)


def optional_completed(content: dict, steps: dict[str, dict]) -> int:
    return sum(1 for s in content["steps"] if s.get("optional") and steps[s["key"]]["completed"])


def empty_steps(content: dict) -> dict[str, dict]:
    return compute_steps(content, Evidence())


# ---------------------------------------------------------------------------
# Instructor: install, publish, settings
# ---------------------------------------------------------------------------


def _versions(db: Session, lesson_id: int) -> list[LessonVersion]:
    return list(db.scalars(select(LessonVersion).where(LessonVersion.lesson_id == lesson_id).order_by(LessonVersion.number)))


def _fixture(key: str, check_assets: bool = True) -> dict:
    """The fixture's validated content, or LessonError listing its problems."""
    if key not in FIXTURES:
        raise LessonError("unknown_fixture", f"No lesson fixture '{key}'", 404)
    try:
        raw = load_fixture(key)
        validate_content(raw, assets_root() if check_assets else None)
    except ContentError as exc:
        raise LessonError("invalid_content", "The lesson content has errors", 422, errors=exc.errors) from None
    return raw


def fixture_hash(key: str) -> str | None:
    """Hash of the shipped fixture when it is valid (assets aside), else None."""
    try:
        return canonical_hash(_fixture(key, check_assets=False))
    except LessonError:
        return None


@dataclass
class InstallPlan:
    action: str  # create | update_draft | new_version | unchanged
    slug: str
    title: str
    course_code: str
    content: dict
    content_hash: str
    lesson: Lesson | None
    version: LessonVersion | None  # the version to update (update_draft) or that already matches (unchanged)
    version_number: int

    def describe(self) -> str:
        if self.action == "create":
            return f"create lesson '{self.slug}' as a draft with version 1"
        if self.action == "update_draft":
            return f"update draft version {self.version_number} of lesson '{self.slug}' in place"
        if self.action == "new_version":
            return f"add draft version {self.version_number} to lesson '{self.slug}' (published versions stay as they are)"
        return f"nothing: lesson '{self.slug}' version {self.version_number} already has this content"


def plan_install(db: Session, course: Course, fixture_key: str, allow_course_mismatch: bool = False) -> InstallPlan:
    """What installing the fixture into the course would do. Writes nothing."""
    raw = _fixture(fixture_key)
    if raw["course_code"] != course.code and not allow_course_mismatch:
        raise LessonError(
            "course_mismatch",
            f"This lesson is for course {raw['course_code']}; the selected course is {course.code} "
            f"({course.name}, {course.year} {course.semester})",
            409,
        )
    digest = canonical_hash(raw)
    lesson = db.scalar(select(Lesson).where(Lesson.course_id == course.id, Lesson.slug == raw["slug"]))
    versions = _versions(db, lesson.id) if lesson else []
    latest = versions[-1] if versions else None
    if latest is None:
        action, number = "create", 1
    elif latest.content_hash == digest:
        action, number = "unchanged", latest.number
    elif latest.status == "draft":
        action, number = "update_draft", latest.number
    else:
        action, number = "new_version", latest.number + 1
    return InstallPlan(
        action=action,
        slug=raw["slug"],
        title=raw["title"],
        course_code=raw["course_code"],
        content=raw,
        content_hash=digest,
        lesson=lesson,
        version=latest if action in ("update_draft", "unchanged") else None,
        version_number=number,
    )


def install_fixture(
    db: Session, course: Course, fixture_key: str, allow_course_mismatch: bool = False
) -> tuple[Lesson, InstallPlan]:
    """Idempotent: creates the lesson as a draft if missing; then updates the
    draft version in place, adds a new draft version after a published one, or
    does nothing when the content is unchanged. Never touches student data."""
    plan = plan_install(db, course, fixture_key, allow_course_mismatch)
    now = utcnow()
    lesson = plan.lesson
    if lesson is None:
        last = db.scalar(select(func.max(Lesson.position)).where(Lesson.course_id == course.id))
        lesson = Lesson(
            course_id=course.id,
            slug=plan.slug,
            title=plan.title,
            position=0 if last is None else last + 1,
            status="draft",
            fixture_key=fixture_key,
            colab_url="",
            created_at=now,
            updated_at=now,
        )
        db.add(lesson)
        db.flush()
    content_json = json.dumps(plan.content, ensure_ascii=False)
    if plan.action == "update_draft":
        plan.version.content_json = content_json
        plan.version.content_hash = plan.content_hash
        plan.version.schema_version = plan.content["schema_version"]
    elif plan.action in ("create", "new_version"):
        db.add(
            LessonVersion(
                lesson_id=lesson.id,
                number=plan.version_number,
                status="draft",
                content_json=content_json,
                content_hash=plan.content_hash,
                schema_version=plan.content["schema_version"],
                created_at=now,
            )
        )
    if plan.action != "unchanged" or lesson.fixture_key != fixture_key:
        lesson.fixture_key = fixture_key
        lesson.updated_at = now
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise LessonError("conflict", "Another install of this lesson ran at the same time; try again", 409) from None
    db.refresh(lesson)
    return lesson, plan


def publish_version(db: Session, lesson: Lesson, version_id: int) -> Lesson:
    """Publish (or re-activate) a version: students who haven't started get it;
    students with progress stay on the version they started."""
    version = db.get(LessonVersion, version_id)
    if version is None or version.lesson_id != lesson.id:
        raise LessonError("version_not_found", "Version not found", 404)
    try:
        validate_content(json.loads(version.content_json), assets_root())
    except ContentError as exc:
        raise LessonError("invalid_content", "The lesson content has errors", 422, errors=exc.errors) from None
    now = utcnow()
    if version.status != "published":
        version.status = "published"
        version.published_at = now
    lesson.active_version_id = version.id
    lesson.status = "published"
    lesson.updated_at = now
    db.commit()
    db.refresh(lesson)
    return lesson


def clean_colab_url(value: str) -> str:
    url = value.strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        parts, port = None, None
    if (
        parts is None
        or len(url) > 1000
        or any(ch.isspace() for ch in url)
        or parts.scheme != "https"
        or parts.hostname not in COLAB_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port is not None
    ):
        raise LessonError(
            "invalid_colab_url", "Use an https:// link on colab.research.google.com or drive.google.com", 422
        )
    return url


def update_lesson(
    db: Session,
    lesson: Lesson,
    title: str | None = None,
    colab_url: str | None = None,
    status: str | None = None,
    position: int | None = None,
) -> Lesson:
    """Settings. status: "draft" hides a published lesson from students
    (unpublish; progress is kept), "archived" retires it. Publishing goes
    through publish_version()."""
    clean_title = title.strip() if title is not None else None
    if clean_title is not None and not 1 <= len(clean_title) <= 255:
        raise LessonError("invalid_title", "The lesson needs a title (up to 255 characters)", 422)
    if status is not None and status not in ("draft", "archived"):
        raise LessonError("invalid_status", "Status must be draft or archived; publish a version instead", 422)
    clean_url = clean_colab_url(colab_url) if colab_url is not None else None
    if clean_title is not None:
        lesson.title = clean_title
    if clean_url is not None:
        lesson.colab_url = clean_url
    if status is not None:
        lesson.status = status
    if position is not None:
        lesson.position = position
    lesson.updated_at = utcnow()
    db.commit()
    db.refresh(lesson)
    return lesson


def lesson_summary(db: Session, lesson: Lesson, fixture_hashes: dict[str, str | None] | None = None) -> dict:
    versions = _versions(db, lesson.id)
    active = next((v for v in versions if v.id == lesson.active_version_id), None)
    latest = versions[-1] if versions else None
    draft = latest if latest is not None and latest.status == "draft" else None
    if fixture_hashes is not None and lesson.fixture_key in fixture_hashes:
        f_hash = fixture_hashes[lesson.fixture_key]
    else:
        f_hash = fixture_hash(lesson.fixture_key) if lesson.fixture_key in FIXTURES else None
        if fixture_hashes is not None:
            fixture_hashes[lesson.fixture_key] = f_hash
    return {
        "id": lesson.id,
        "slug": lesson.slug,
        "title": lesson.title,
        "status": lesson.status,
        "position": lesson.position,
        "colab_url": lesson.colab_url,
        "fixture_key": lesson.fixture_key,
        "active_version": version_view(active) if active else None,
        "draft_version": (
            {"id": draft.id, "number": draft.number, "content_hash": draft.content_hash, "created_at": iso(draft.created_at)}
            if draft
            else None
        ),
        "versions": [
            {
                "id": v.id,
                "number": v.number,
                "status": v.status,
                "content_hash": v.content_hash,
                "created_at": iso(v.created_at),
                "published_at": iso(v.published_at),
            }
            for v in versions
        ],
        "fixture_hash": f_hash,
        "fixture_update_available": bool(f_hash and latest is not None and f_hash != latest.content_hash),
    }


def course_lessons(db: Session, course_id: int) -> list[dict]:
    hashes: dict[str, str | None] = {}
    lessons = db.scalars(select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.position, Lesson.id))
    return [lesson_summary(db, lesson, hashes) for lesson in lessons]


def fixtures_overview(db: Session, course: Course) -> list[dict]:
    out = []
    for key in FIXTURES:
        entry: dict = {
            "key": key,
            "slug": None,
            "title": None,
            "course_code": None,
            "matches_course": False,
            "installed_lesson_id": None,
            "content_hash": None,
            "valid": False,
            "errors": [],
        }
        try:
            raw = load_fixture(key)
        except ContentError as exc:
            entry["errors"] = exc.errors
            out.append(entry)
            continue
        for name in ("slug", "title", "course_code"):
            entry[name] = raw.get(name) if isinstance(raw.get(name), str) else None
        entry["content_hash"] = canonical_hash(raw)
        entry["matches_course"] = entry["course_code"] == course.code
        try:
            validate_content(raw, assets_root())
            entry["valid"] = True
        except ContentError as exc:
            entry["errors"] = exc.errors
        if entry["slug"]:
            entry["installed_lesson_id"] = db.scalar(
                select(Lesson.id).where(Lesson.course_id == course.id, Lesson.slug == entry["slug"])
            )
        out.append(entry)
    return out


def _reference_version(db: Session, lesson: Lesson, version_id: int | None = None) -> LessonVersion | None:
    """A specific version of the lesson, or the active one, or the latest."""
    if version_id is not None:
        version = db.get(LessonVersion, version_id)
        if version is None or version.lesson_id != lesson.id:
            raise LessonError("version_not_found", "Version not found", 404)
        return version
    if lesson.active_version_id is not None:
        return db.get(LessonVersion, lesson.active_version_id)
    versions = _versions(db, lesson.id)
    return versions[-1] if versions else None


def _version_or_latest(db: Session, lesson: Lesson, version_id: int | None) -> LessonVersion:
    if version_id is not None:
        return _reference_version(db, lesson, version_id)
    versions = _versions(db, lesson.id)
    if not versions:
        raise LessonError("version_not_found", "The lesson has no versions yet", 404)
    return versions[-1]


def preview_payload(db: Session, lesson: Lesson, version_id: int | None = None) -> dict:
    """What a student would get, for any version (default: the latest), with
    no student state. Writes nothing."""
    version = _version_or_latest(db, lesson, version_id)
    content = content_of(version)
    course = db.get(Course, lesson.course_id)
    return {
        "mode": "preview",
        "lesson": {"id": lesson.id, "slug": lesson.slug, "title": lesson.title, "status": lesson.status},
        "version": version_view(version),
        "content": sanitize_for_student(content),
        "colab_url": lesson.colab_url or None,
        "asset_base": asset_base(content),
        "student": None,
        "course": {"name": course.name if course else "", "code": course.code if course else ""},
        "progress": None,
        "steps": empty_steps(content),
        "questions": {},
        "experiments": [],
        "commitments": [],
    }


def preview_evaluate(
    db: Session,
    lesson: Lesson,
    version_id: int | None,
    question_key: str,
    answer: Answer | None,
    reveal: bool,
    prior_answers: int,
) -> dict:
    """Feedback by exactly the student rules, for the instructor preview. Writes nothing."""
    question = content_of(_version_or_latest(db, lesson, version_id))["questions"].get(question_key)
    if question is None:
        raise LessonError("question_not_found", "Question not found in this version", 404)
    if reveal:
        if question["mode"] == "check" and prior_answers <= 0:
            raise LessonError("answer_first", MSG["answer_first"], 409)
        choice = answer.choice if answer is not None else None
        valid = question["type"] == "single_choice" and choice in [o["id"] for o in question["options"]]
        clean = {"choice": choice} if valid else None
    else:
        if answer is None:
            raise invalid_values({"answer": MSG["text_required"]})
        clean = clean_answer(question, answer)
    feedback = feedback_for(question, clean, reveal=reveal)
    return {"feedback": feedback, "correct": feedback["correct"]}


# ---------------------------------------------------------------------------
# Student: lessons, progress
# ---------------------------------------------------------------------------


def published_lessons(db: Session, course_id: int) -> list[Lesson]:
    return list(
        db.scalars(
            select(Lesson)
            .where(Lesson.course_id == course_id, Lesson.status == "published", Lesson.active_version_id.is_not(None))
            .order_by(Lesson.position, Lesson.id)
        )
    )


def lesson_links(db: Session, course_id: int) -> list[dict]:
    """Entry points for the student's course page."""
    return [{"slug": lesson.slug, "title": lesson.title} for lesson in published_lessons(db, course_id)]


def student_lesson(db: Session, enrollment: Enrollment, slug: str) -> Lesson:
    """A published lesson of the student's course. Anything else (draft,
    archived, another course's, nonexistent) is the same 404."""
    lesson = db.scalar(select(Lesson).where(Lesson.course_id == enrollment.course_id, Lesson.slug == slug))
    if lesson is None or lesson.status != "published" or lesson.active_version_id is None:
        raise LessonError("lesson_not_found", MSG["lesson_not_found"], 404)
    return lesson


def _progress(db: Session, enrollment_id: int, lesson_id: int) -> LessonProgress | None:
    return db.scalar(
        select(LessonProgress).where(LessonProgress.enrollment_id == enrollment_id, LessonProgress.lesson_id == lesson_id)
    )


def _version_for(db: Session, lesson: Lesson, progress: LessonProgress | None) -> LessonVersion:
    """The pinned version once the student has progress, else the active one."""
    return db.get(LessonVersion, progress.version_id if progress else lesson.active_version_id)


def _attempts(db: Session, enrollment_id: int, lesson_id: int, question_key: str | None = None) -> list[LessonAttempt]:
    query = select(LessonAttempt).where(LessonAttempt.enrollment_id == enrollment_id, LessonAttempt.lesson_id == lesson_id)
    if question_key is not None:
        query = query.where(LessonAttempt.question_key == question_key)
    return list(db.scalars(query.order_by(LessonAttempt.id)))


def _experiments(db: Session, enrollment_id: int, lesson_id: int, include_deleted: bool = False) -> list[LessonExperiment]:
    query = select(LessonExperiment).where(
        LessonExperiment.enrollment_id == enrollment_id, LessonExperiment.lesson_id == lesson_id
    )
    if not include_deleted:
        query = query.where(LessonExperiment.deleted_at.is_(None))
    return list(db.scalars(query.order_by(LessonExperiment.created_at, LessonExperiment.id)))


def _commitments(db: Session, enrollment_id: int, lesson_id: int) -> list[LessonCommitment]:
    return list(
        db.scalars(
            select(LessonCommitment)
            .where(LessonCommitment.enrollment_id == enrollment_id, LessonCommitment.lesson_id == lesson_id)
            .order_by(LessonCommitment.committed_at, LessonCommitment.id)
        )
    )


def _evidence(db: Session, enrollment_id: int, lesson_id: int, progress: LessonProgress | None) -> Evidence:
    return evidence_from(
        progress,
        _attempts(db, enrollment_id, lesson_id),
        _experiments(db, enrollment_id, lesson_id),
        _commitments(db, enrollment_id, lesson_id),
    )


def _steps_and_completion(
    db: Session, enrollment_id: int, lesson_id: int, progress: LessonProgress | None, content: dict
) -> dict[str, dict]:
    """Step statuses; sets completed_at (once) when every required step is done.
    completed_at is history ("first completed at") and is never cleared; a
    status label comes from the current evidence instead (lesson_status)."""
    steps = compute_steps(content, _evidence(db, enrollment_id, lesson_id, progress))
    done, total = required_progress(content, steps)
    if progress is not None and progress.completed_at is None and done == total:
        progress.completed_at = utcnow()
        db.commit()
    return steps


def ensure_progress(db: Session, enrollment: Enrollment, lesson: Lesson) -> LessonProgress:
    """The student's progress row, created (and so pinned to the active
    version) on their first save of any kind. Revision 0 until the first
    progress write, so a client that hasn't saved progress yet still sends 0."""
    progress = _progress(db, enrollment.id, lesson.id)
    if progress is not None:
        return progress
    now = utcnow()
    progress = LessonProgress(
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        version_id=lesson.active_version_id,
        viewed_json="[]",
        acks_json="[]",
        drafts_json="{}",
        revision=0,
        started_at=now,
        updated_at=now,
    )
    db.add(progress)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # created concurrently
        progress = _progress(db, enrollment.id, lesson.id)
        if progress is None:
            raise
    return progress


def lesson_status(progress: LessonProgress | None, done: int, total: int) -> str:
    """not_started / in_progress / completed, from the current evidence: a
    student who finished and later removed evidence (un-ticked an ack,
    deleted a run) is in progress again, although completed_at stays set."""
    if progress is None:
        return "not_started"
    return "completed" if done == total else "in_progress"


def student_lessons(db: Session, enrollment: Enrollment) -> list[dict]:
    out = []
    for lesson in published_lessons(db, enrollment.course_id):
        progress = _progress(db, enrollment.id, lesson.id)
        content = content_of(_version_for(db, lesson, progress))
        steps = compute_steps(content, _evidence(db, enrollment.id, lesson.id, progress))
        done, total = required_progress(content, steps)
        status = lesson_status(progress, done, total)
        out.append(
            {
                "slug": lesson.slug,
                "title": lesson.title,
                "guiding_question": content["guiding_question"],
                "status": status,
                "required_done": done,
                "required_total": total,
                "current_step_key": progress.current_step_key if progress else None,
            }
        )
    return out


def student_payload(db: Session, enrollment: Enrollment, lesson: Lesson) -> dict:
    """LessonPayload for the student. Writes nothing."""
    progress = _progress(db, enrollment.id, lesson.id)
    version = _version_for(db, lesson, progress)
    content = content_of(version)
    attempts = _attempts(db, enrollment.id, lesson.id)
    experiments = _experiments(db, enrollment.id, lesson.id)
    commitments = _commitments(db, enrollment.id, lesson.id)
    by_question: dict[str, list[LessonAttempt]] = defaultdict(list)
    for row in attempts:
        by_question[row.question_key].append(row)
    course = db.get(Course, enrollment.course_id)
    student = db.get(Student, enrollment.student_id)
    return {
        "mode": "student",
        "lesson": {"id": lesson.id, "slug": lesson.slug, "title": lesson.title, "status": lesson.status},
        "version": version_view(version),
        "content": sanitize_for_student(content),
        "colab_url": lesson.colab_url or None,
        "asset_base": asset_base(content),
        "student": {"name": student.name if student else ""},
        "course": {"name": course.name if course else "", "code": course.code if course else ""},
        "progress": progress_view(progress),
        "steps": compute_steps(content, evidence_from(progress, attempts, experiments, commitments)),
        "questions": {key: question_state(q, by_question.get(key, [])) for key, q in content["questions"].items()},
        "experiments": [experiment_view(e) for e in experiments],
        "commitments": [commitment_view(c) for c in commitments],
    }


def _stale_progress(db: Session, enrollment: Enrollment, lesson: Lesson) -> LessonError:
    db.expire_all()
    progress = _progress(db, enrollment.id, lesson.id)
    content = content_of(_version_for(db, lesson, progress))
    steps = compute_steps(content, _evidence(db, enrollment.id, lesson.id, progress))
    return LessonError("stale", MSG["stale"], 409, current=progress_view(progress), steps=steps)


def _ordered(keys: set[str], order: list[str]) -> list[str]:
    return [k for k in order if k in keys]


def patch_progress(db: Session, enrollment: Enrollment, lesson: Lesson, patch: ProgressPatch) -> dict:
    """Merge a progress write: viewed and acks are sets, drafts are set or
    deleted per key. expected_revision must be the current revision (0 before
    the first progress write); otherwise 409 stale with the current state."""
    progress = _progress(db, enrollment.id, lesson.id)
    if patch.expected_revision != (progress.revision if progress else 0):
        raise _stale_progress(db, enrollment, lesson)
    version = _version_for(db, lesson, progress)
    content = content_of(version)
    steps_order, acks_order = step_keys(content), ack_keys(content)

    fields: dict[str, str] = {}
    if patch.current_step_key is not None and patch.current_step_key not in steps_order:
        fields["current_step_key"] = MSG["step"]
    if any(k not in steps_order for k in patch.viewed_add):
        fields["viewed_add"] = MSG["step"]
    if any(k not in acks_order for k in patch.acks_add):
        fields["acks_add"] = MSG["ack"]
    if any(k not in acks_order for k in patch.acks_remove):
        fields["acks_remove"] = MSG["ack"]
    drafts: dict[str, str] = json.loads(progress.drafts_json or "{}") if progress else {}
    for key, value in patch.drafts.items():
        if not key.strip() or len(key) > MAX_DRAFT_KEY_CHARS:
            fields["drafts"] = MSG["draft_key"]
        elif value is None:
            drafts.pop(key, None)
        elif len(value) > MAX_DRAFT_CHARS:
            fields[f"drafts.{key}"] = MSG["draft_long"]
        else:
            drafts[key] = value
    if "drafts" not in fields:
        if len(drafts) > MAX_DRAFT_KEYS:
            fields["drafts"] = MSG["drafts_many"]
        elif len(json.dumps(drafts, ensure_ascii=False).encode("utf-8")) > MAX_DRAFTS_BYTES:
            fields["drafts"] = MSG["drafts_big"]
    if fields:
        raise invalid_values(fields)

    viewed = set(json.loads(progress.viewed_json or "[]")) if progress else set()
    acks = set(json.loads(progress.acks_json or "[]")) if progress else set()
    values = {
        "current_step_key": patch.current_step_key or (progress.current_step_key if progress else None),
        "viewed_json": json.dumps(_ordered(viewed | set(patch.viewed_add), steps_order)),
        "acks_json": json.dumps(_ordered((acks | set(patch.acks_add)) - set(patch.acks_remove), acks_order)),
        "drafts_json": json.dumps(drafts, ensure_ascii=False),
        "revision": patch.expected_revision + 1,
        "updated_at": utcnow(),
    }
    if progress is None:
        progress = LessonProgress(
            enrollment_id=enrollment.id, lesson_id=lesson.id, version_id=version.id, started_at=values["updated_at"], **values
        )
        db.add(progress)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # another tab saved first
            raise _stale_progress(db, enrollment, lesson) from None
    else:
        result = db.execute(
            update(LessonProgress)
            .where(LessonProgress.id == progress.id, LessonProgress.revision == patch.expected_revision)
            .values(**values)
        )
        if result.rowcount != 1:
            db.rollback()
            raise _stale_progress(db, enrollment, lesson)
        db.commit()
        db.refresh(progress)
    steps = _steps_and_completion(db, enrollment.id, lesson.id, progress, content)
    return {"progress": progress_view(progress), "steps": steps}


# ---------------------------------------------------------------------------
# Student: attempts and reveals
# ---------------------------------------------------------------------------


def _check_request_id(request_id: str) -> None:
    if not REQUEST_ID.match(request_id or ""):
        raise invalid_values({"request_id": MSG["request_id"]})


def _attempt_by_request(db: Session, enrollment_id: int, request_id: str) -> LessonAttempt | None:
    return db.scalar(
        select(LessonAttempt).where(LessonAttempt.enrollment_id == enrollment_id, LessonAttempt.request_id == request_id)
    )


def _attempt_result(db: Session, enrollment: Enrollment, lesson: Lesson, question_key: str, write: bool = True) -> dict:
    progress = _progress(db, enrollment.id, lesson.id)
    content = content_of(_version_for(db, lesson, progress))
    if write:
        steps = _steps_and_completion(db, enrollment.id, lesson.id, progress, content)
    else:
        steps = compute_steps(content, _evidence(db, enrollment.id, lesson.id, progress))
    return {
        "question_key": question_key,
        "question": question_state(
            content["questions"][question_key], _attempts(db, enrollment.id, lesson.id, question_key)
        ),
        "steps": steps,
        "completed_at": iso(progress.completed_at) if progress else None,
    }


def _replay(db: Session, enrollment: Enrollment, lesson: Lesson, row: LessonAttempt, question_key: str, kind: str) -> dict:
    """A retried request: the stored result, never a second row."""
    if row.lesson_id != lesson.id or row.question_key != question_key or row.kind != kind:
        raise LessonError("request_reused", MSG["request_reused"], 409)
    return _attempt_result(db, enrollment, lesson, question_key, write=False)


def _record_attempt(db: Session, enrollment: Enrollment, lesson: Lesson, row: LessonAttempt) -> dict:
    progress = ensure_progress(db, enrollment, lesson)
    row.version_id = progress.version_id
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # the same request arrived twice at once
        existing = _attempt_by_request(db, enrollment.id, row.request_id)
        if existing is None:
            raise
        return _replay(db, enrollment, lesson, existing, row.question_key, row.kind)
    return _attempt_result(db, enrollment, lesson, row.question_key)


def _question(db: Session, enrollment: Enrollment, lesson: Lesson, question_key: str) -> dict:
    """The question in the version this student is (or will be) pinned to."""
    content = content_of(_version_for(db, lesson, _progress(db, enrollment.id, lesson.id)))
    question = content["questions"].get(question_key)
    if question is None:
        raise LessonError("question_not_found", MSG["question_not_found"], 404)
    return question


def submit_attempt(db: Session, enrollment: Enrollment, lesson: Lesson, payload: AttemptInput) -> dict:
    """Append an answer. Every submission is a new attempt (the first is never
    overwritten); a retried request_id returns the original result."""
    _check_request_id(payload.request_id)
    existing = _attempt_by_request(db, enrollment.id, payload.request_id)
    if existing is not None:
        return _replay(db, enrollment, lesson, existing, payload.question_key, "answer")
    question = _question(db, enrollment, lesson, payload.question_key)
    clean = clean_answer(question, payload.answer)
    prior = _attempts(db, enrollment.id, lesson.id, payload.question_key)
    answers = sum(1 for r in prior if r.kind == "answer")
    if answers >= MAX_ANSWERS_PER_QUESTION:
        raise LessonError("too_many_attempts", MSG["too_many_attempts"], 409)
    row = LessonAttempt(
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        step_key=question["step"],
        question_key=question["key"],
        question_hash=question_hash(question),
        request_id=payload.request_id,
        attempt_number=answers + 1,
        kind="answer",
        answer_json=json.dumps(clean, ensure_ascii=False),
        correct=is_correct(question, clean),
        after_feedback=bool(prior),
        submitted_at=utcnow(),
    )
    return _record_attempt(db, enrollment, lesson, row)


def reveal(db: Session, enrollment: Enrollment, lesson: Lesson, question_key: str, request_id: str) -> dict:
    """Record that the student asked to see the reasoning. Practice questions
    any time (recorded, so "revealed before answering" is visible to the
    instructor); check questions only after a first individual answer."""
    _check_request_id(request_id)
    existing = _attempt_by_request(db, enrollment.id, request_id)
    if existing is not None:
        return _replay(db, enrollment, lesson, existing, question_key, "reveal")
    question = _question(db, enrollment, lesson, question_key)
    prior = _attempts(db, enrollment.id, lesson.id, question_key)
    answers = sum(1 for r in prior if r.kind == "answer")
    if question["mode"] == "check" and answers == 0:
        raise LessonError("answer_first", MSG["answer_first"], 409)
    if sum(1 for r in prior if r.kind == "reveal") >= MAX_REVEALS_PER_QUESTION:
        # Plenty of reveals on record: show the reasoning again, record nothing.
        result = _attempt_result(db, enrollment, lesson, question_key, write=False)
        latest = next((r for r in reversed(prior) if r.kind == "answer"), None)
        result["question"]["feedback"] = feedback_for(question, _answer(latest) if latest else None, reveal=True)
        return result
    row = LessonAttempt(
        enrollment_id=enrollment.id,
        lesson_id=lesson.id,
        step_key=question["step"],
        question_key=question["key"],
        question_hash=question_hash(question),
        request_id=request_id,
        attempt_number=answers,
        kind="reveal",
        answer_json=None,
        correct=None,
        after_feedback=bool(prior),
        submitted_at=utcnow(),
    )
    return _record_attempt(db, enrollment, lesson, row)


# ---------------------------------------------------------------------------
# Student: experiments
# ---------------------------------------------------------------------------


def _whole(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and float(value).is_integer()
    )


def _clean_run_uuid(value: str | None, fields: dict[str, str], name: str = "run_uuid") -> str | None:
    if value is None or not RUN_UUID.match(value):
        fields[name] = MSG["run_uuid"]
        return None
    return value.lower()


def _clean_settings(
    fields: dict[str, str], depth_kind: str | None, depth: float | None, training_examples: float | None, required: bool
) -> tuple[str | None, int | None, int | None]:
    """depth_kind / depth / training_examples, checked together: a limited
    depth is 1..50, unlimited has no number (Colab's 0), examples 20..720."""
    kind = clean_depth = examples = None
    if depth_kind is None:
        if required:
            fields["depth_kind"] = MSG["depth_kind_required"]
        elif depth is not None:
            fields["depth"] = MSG["depth_without_kind"]
    elif depth_kind not in ("limited", "unlimited"):
        fields["depth_kind"] = MSG["depth_kind"]
    elif depth_kind == "limited":
        if depth is None:
            fields["depth"] = MSG["depth_required"]
        elif depth == 0:
            fields["depth"] = MSG["depth_zero"]
        elif not _whole(depth) or not 1 <= depth <= MAX_DEPTH:
            fields["depth"] = MSG["depth"]
        else:
            kind, clean_depth = "limited", int(depth)
    elif depth is not None:
        fields["depth"] = MSG["depth_unlimited"]
    else:
        kind = "unlimited"
    if training_examples is None:
        if required:
            fields["training_examples"] = MSG["training_examples_required"]
    elif not _whole(training_examples) or not MIN_TRAINING_EXAMPLES <= training_examples <= MAX_TRAINING_EXAMPLES:
        fields["training_examples"] = MSG["training_examples"]
    else:
        examples = int(training_examples)
    return kind, clean_depth, examples


def _fraction(fields: dict[str, str], name: str, pct: float | None, required: bool = False) -> float | None:
    """A percentage 0..100 from the UI, stored once as a fraction 0..1."""
    if pct is None:
        if required:
            fields[name] = MSG["pct_required"]
        return None
    if isinstance(pct, bool) or not math.isfinite(pct) or not 0 <= pct <= 100:
        fields[name] = MSG["pct"]
        return None
    return round(pct / 100, 6)


def _text(fields: dict[str, str], name: str, value: str | None, min_chars: int = 0, short: str = "") -> str:
    text = (value or "").strip()
    if len(text) > MAX_TEXT:
        fields[name] = MSG["too_long"]
    elif len(text) < min_chars:
        fields[name] = short
    return text


def _experiments_result(db: Session, enrollment: Enrollment, lesson: Lesson) -> dict:
    progress = _progress(db, enrollment.id, lesson.id)
    content = content_of(_version_for(db, lesson, progress))
    steps = _steps_and_completion(db, enrollment.id, lesson.id, progress, content)
    return {
        "experiments": [experiment_view(e) for e in _experiments(db, enrollment.id, lesson.id)],
        "steps": steps,
        "completed_at": iso(progress.completed_at) if progress else None,
    }


def _stale_experiment(db: Session, enrollment: Enrollment, run_uuid: str) -> LessonError:
    db.expire_all()
    row = db.scalar(
        select(LessonExperiment).where(LessonExperiment.enrollment_id == enrollment.id, LessonExperiment.run_uuid == run_uuid)
    )
    if row is None or row.deleted_at is not None:
        return LessonError("stale", MSG["experiment_gone"] if row else MSG["stale"], 409, current=None)
    return LessonError("stale", MSG["stale"], 409, current=experiment_view(row))


def save_experiment(db: Session, enrollment: Enrollment, lesson: Lesson, run_uuid: str, payload: ExperimentInput) -> dict:
    """Create (expected_revision null) or edit (expected_revision = the
    record's revision) one experiment record. Invalid values save nothing."""
    fields: dict[str, str] = {}
    run = _clean_run_uuid(run_uuid, fields)
    kind, depth, examples = _clean_settings(
        fields, payload.depth_kind, payload.depth, payload.training_examples, required=False
    )
    values = {
        "depth_kind": kind,
        "depth": depth,
        "training_examples": examples,
        "train_accuracy": _fraction(fields, "train_accuracy_pct", payload.train_accuracy_pct),
        "validation_accuracy": _fraction(fields, "validation_accuracy_pct", payload.validation_accuracy_pct),
        "baseline_validation": _fraction(fields, "baseline_validation_pct", payload.baseline_validation_pct),
        "hypothesis": _text(fields, "hypothesis", payload.hypothesis),
        "observation": _text(fields, "observation", payload.observation),
        "explanation": _text(fields, "explanation", payload.explanation),
    }
    if not fields and all(v in (None, "") for v in values.values()):
        fields["hypothesis"] = MSG["empty_run"]
    if fields:
        raise invalid_values(fields)

    row = db.scalar(
        select(LessonExperiment).where(LessonExperiment.enrollment_id == enrollment.id, LessonExperiment.run_uuid == run)
    )
    if row is not None and row.lesson_id != lesson.id:
        raise LessonError("run_reused", MSG["run_reused"], 409)
    now = utcnow()
    # The first prediction saved for this run is kept as it was.
    first = {"first_hypothesis": values["hypothesis"], "first_hypothesis_at": now} if values["hypothesis"] else {}
    if row is None:
        if payload.expected_revision is not None:
            raise _stale_experiment(db, enrollment, run)
        total, deleted = db.execute(
            select(func.count(), func.count(LessonExperiment.deleted_at)).where(
                LessonExperiment.enrollment_id == enrollment.id, LessonExperiment.lesson_id == lesson.id
            )
        ).one()
        if total - deleted >= MAX_EXPERIMENTS:
            raise LessonError("too_many_experiments", MSG["too_many_experiments"], 409)
        if total >= MAX_EXPERIMENT_ROWS:
            raise LessonError("too_many_experiments", MSG["too_many_experiment_rows"], 409)
        progress = ensure_progress(db, enrollment, lesson)
        db.add(
            LessonExperiment(
                enrollment_id=enrollment.id,
                lesson_id=lesson.id,
                version_id=progress.version_id,
                run_uuid=run,
                provenance="student_entered",
                revision=1,
                created_at=now,
                updated_at=now,
                **values,
                **first,
            )
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()  # created by another tab with the same run id
            raise _stale_experiment(db, enrollment, run) from None
    else:
        if row.deleted_at is not None or payload.expected_revision != row.revision:
            raise _stale_experiment(db, enrollment, run)
        result = db.execute(
            update(LessonExperiment)
            .where(
                LessonExperiment.id == row.id,
                LessonExperiment.revision == payload.expected_revision,
                LessonExperiment.deleted_at.is_(None),
            )
            .values(
                revision=payload.expected_revision + 1,
                updated_at=now,
                **values,
                **(first if row.first_hypothesis is None else {}),
            )
        )
        if result.rowcount != 1:
            db.rollback()
            raise _stale_experiment(db, enrollment, run)
        db.commit()
    return _experiments_result(db, enrollment, lesson)


def delete_experiment(db: Session, enrollment: Enrollment, lesson: Lesson, run_uuid: str, expected_revision: int) -> dict:
    """Soft delete: gone for the student, kept (with deleted_at) for the
    instructor. Deleting an already deleted record is a no-op."""
    fields: dict[str, str] = {}
    run = _clean_run_uuid(run_uuid, fields)
    if fields:
        raise invalid_values(fields)
    row = db.scalar(
        select(LessonExperiment).where(LessonExperiment.enrollment_id == enrollment.id, LessonExperiment.run_uuid == run)
    )
    if row is None or row.lesson_id != lesson.id:
        raise LessonError("experiment_not_found", MSG["experiment_not_found"], 404)
    if row.deleted_at is None:
        if expected_revision != row.revision:
            raise _stale_experiment(db, enrollment, run)
        result = db.execute(
            update(LessonExperiment)
            .where(
                LessonExperiment.id == row.id,
                LessonExperiment.revision == expected_revision,
                LessonExperiment.deleted_at.is_(None),
            )
            .values(deleted_at=utcnow())
        )
        if result.rowcount != 1:
            db.rollback()
            raise _stale_experiment(db, enrollment, run)
        db.commit()
    return _experiments_result(db, enrollment, lesson)


# ---------------------------------------------------------------------------
# Student: commitments and final results
# ---------------------------------------------------------------------------


def _commitments_result(db: Session, enrollment: Enrollment, lesson: Lesson) -> dict:
    progress = _progress(db, enrollment.id, lesson.id)
    content = content_of(_version_for(db, lesson, progress))
    steps = _steps_and_completion(db, enrollment.id, lesson.id, progress, content)
    return {
        "commitments": [commitment_view(c) for c in _commitments(db, enrollment.id, lesson.id)],
        "steps": steps,
        "completed_at": iso(progress.completed_at) if progress else None,
    }


def commit(db: Session, enrollment: Enrollment, lesson: Lesson, payload: CommitmentInput) -> dict:
    """Save the chosen settings and why, before the final test. Never edits an
    earlier commitment; one made after a final result was recorded is flagged."""
    _check_request_id(payload.request_id)
    existing = db.scalar(
        select(LessonCommitment).where(
            LessonCommitment.enrollment_id == enrollment.id, LessonCommitment.request_id == payload.request_id
        )
    )
    if existing is not None:
        if existing.lesson_id != lesson.id:
            raise LessonError("request_reused", MSG["request_reused"], 409)
        return _commitments_result(db, enrollment, lesson)
    count = db.scalar(
        select(func.count())
        .select_from(LessonCommitment)
        .where(LessonCommitment.enrollment_id == enrollment.id, LessonCommitment.lesson_id == lesson.id)
    )
    if count >= MAX_COMMITMENTS:
        raise LessonError("too_many_commitments", MSG["too_many_commitments"], 409)
    fields: dict[str, str] = {}
    kind, depth, examples = _clean_settings(
        fields, payload.depth_kind, payload.depth, payload.training_examples, required=True
    )
    run = None
    if payload.run_uuid:
        run = _clean_run_uuid(payload.run_uuid, fields)
        own = run and db.scalar(
            select(LessonExperiment.id).where(
                LessonExperiment.enrollment_id == enrollment.id,
                LessonExperiment.lesson_id == lesson.id,
                LessonExperiment.run_uuid == run,
                LessonExperiment.deleted_at.is_(None),
            )
        )
        if run and not own:
            fields["run_uuid"] = MSG["run_unknown"]
    justification = _text(
        fields, "justification", payload.justification, min_chars=MIN_JUSTIFICATION, short=MSG["justification"]
    )
    if fields:
        raise invalid_values(fields)
    progress = ensure_progress(db, enrollment, lesson)
    finals = db.scalar(
        select(func.count())
        .select_from(LessonCommitment)
        .where(
            LessonCommitment.enrollment_id == enrollment.id,
            LessonCommitment.lesson_id == lesson.id,
            LessonCommitment.final_recorded_at.is_not(None),
        )
    )
    db.add(
        LessonCommitment(
            enrollment_id=enrollment.id,
            lesson_id=lesson.id,
            version_id=progress.version_id,
            request_id=payload.request_id,
            run_uuid=run,
            depth_kind=kind,
            depth=depth,
            training_examples=examples,
            justification=justification,
            committed_at=utcnow(),
            after_final_seen=finals > 0,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()  # the same request arrived twice at once
    return _commitments_result(db, enrollment, lesson)


def record_final(
    db: Session, enrollment: Enrollment, lesson: Lesson, commitment_id: int, payload: FinalInput
) -> dict:
    """The final-test result for one of the student's commitments, once."""
    row = db.get(LessonCommitment, commitment_id)
    if row is None or row.enrollment_id != enrollment.id or row.lesson_id != lesson.id:
        raise LessonError("commitment_not_found", MSG["commitment_not_found"], 404)
    if row.final_recorded_at is not None:
        raise LessonError("final_already_recorded", MSG["final_already_recorded"], 409)
    fields: dict[str, str] = {}
    values = {
        "final_accuracy": _fraction(fields, "final_accuracy_pct", payload.final_accuracy_pct, required=True),
        "final_precision": _fraction(fields, "final_precision_pct", payload.final_precision_pct),
        "final_recall": _fraction(fields, "final_recall_pct", payload.final_recall_pct),
        "final_note": _text(fields, "final_note", payload.final_note),
    }
    if fields:
        raise invalid_values(fields)
    result = db.execute(
        update(LessonCommitment)
        .where(LessonCommitment.id == row.id, LessonCommitment.final_recorded_at.is_(None))
        .values(final_recorded_at=utcnow(), **values)
    )
    if result.rowcount != 1:
        db.rollback()
        raise LessonError("final_already_recorded", MSG["final_already_recorded"], 409)
    db.commit()
    return _commitments_result(db, enrollment, lesson)


# ---------------------------------------------------------------------------
# Instructor: insights, drilldown, review flags, export
# ---------------------------------------------------------------------------


@dataclass
class _Activity:
    """One enrolled student's activity in a lesson."""

    enrollment: Enrollment
    student: Student
    progress: LessonProgress | None
    attempts: list[LessonAttempt]
    experiments: list[LessonExperiment]  # deleted ones included
    commitments: list[LessonCommitment]

    def last_activity(self) -> datetime | None:
        stamps = [self.progress.updated_at] if self.progress else []
        stamps += [a.submitted_at for a in self.attempts]
        stamps += [t for e in self.experiments for t in (e.updated_at, e.deleted_at) if t]
        stamps += [t for c in self.commitments for t in (c.committed_at, c.final_recorded_at) if t]
        return max(stamps) if stamps else None


def _course_activity(db: Session, lesson: Lesson) -> list[_Activity]:
    """Every enrollment of the course (not only students who opened the
    lesson), sorted by name."""
    rows = db.execute(
        select(Enrollment, Student)
        .join(Student, Student.id == Enrollment.student_id)
        .where(Enrollment.course_id == lesson.course_id)
    ).all()
    progress = {p.enrollment_id: p for p in db.scalars(select(LessonProgress).where(LessonProgress.lesson_id == lesson.id))}
    attempts: dict[int, list[LessonAttempt]] = defaultdict(list)
    for a in db.scalars(select(LessonAttempt).where(LessonAttempt.lesson_id == lesson.id).order_by(LessonAttempt.id)):
        attempts[a.enrollment_id].append(a)
    experiments: dict[int, list[LessonExperiment]] = defaultdict(list)
    for e in db.scalars(
        select(LessonExperiment)
        .where(LessonExperiment.lesson_id == lesson.id)
        .order_by(LessonExperiment.created_at, LessonExperiment.id)
    ):
        experiments[e.enrollment_id].append(e)
    commitments: dict[int, list[LessonCommitment]] = defaultdict(list)
    for c in db.scalars(
        select(LessonCommitment)
        .where(LessonCommitment.lesson_id == lesson.id)
        .order_by(LessonCommitment.committed_at, LessonCommitment.id)
    ):
        commitments[c.enrollment_id].append(c)
    out = [
        _Activity(
            enrollment=enrollment,
            student=student,
            progress=progress.get(enrollment.id),
            attempts=attempts.get(enrollment.id, []),
            experiments=experiments.get(enrollment.id, []),
            commitments=commitments.get(enrollment.id, []),
        )
        for enrollment, student in rows
    ]
    out.sort(key=lambda a: (a.student.name.casefold(), a.student.id))
    return out


class _Contents:
    """Parsed content per version id, loaded once per request."""

    def __init__(self, db: Session):
        self.db = db
        self.cache: dict[int, dict] = {}

    def get(self, version_id: int) -> dict:
        if version_id not in self.cache:
            self.cache[version_id] = content_of(self.db.get(LessonVersion, version_id))
        return self.cache[version_id]


@dataclass
class _StudentProgress:
    steps: dict[str, dict]
    content: dict | None  # the version the steps were computed on
    done: int
    total: int


def _student_progress(activity: _Activity, contents: _Contents, reference: LessonVersion | None) -> _StudentProgress:
    """Step statuses on the student's pinned version (or, before they start,
    the version they would start on) and their required done/total."""
    version_id = activity.progress.version_id if activity.progress else (reference.id if reference else None)
    if version_id is None:
        return _StudentProgress({}, None, 0, 0)
    content = contents.get(version_id)
    live = [e for e in activity.experiments if e.deleted_at is None]
    steps = compute_steps(content, evidence_from(activity.progress, activity.attempts, live, activity.commitments))
    done, total = required_progress(content, steps)
    return _StudentProgress(steps, content, done, total)


def _status(activity: _Activity, mine: _StudentProgress) -> str:
    return lesson_status(activity.progress, mine.done, mine.total)


def _first_correct_count(activity: _Activity) -> int:
    """Questions whose first answer was right before any feedback: a question
    the student revealed before answering never counts."""
    firsts: dict[str, LessonAttempt] = {}
    for a in activity.attempts:  # oldest first
        firsts.setdefault(a.question_key, a)
    return sum(1 for a in firsts.values() if a.kind == "answer" and a.correct is True)


def _question_stats(content: dict, students: list[_Activity]) -> list[dict]:
    """First-attempt evidence per question. answered / first_correct /
    first_incorrect count by question key over every version (correctness is
    stored per attempt). A first answer given after revealing the reasoning
    is not independent evidence: it counts in answered and
    answered_after_reveal only. The option bars count only answers given to
    this exact question (same question hash), so an option id that changed
    meaning in another version is never shown under this version's text;
    the rest are other_version_answers. Written text is listed for each
    student's first and latest answer (and any flagged one); the drilldown
    has every attempt."""
    out = []
    for q in ordered_questions(content):
        key = q["key"]
        digest = question_hash(q)
        stats = {
            "key": key,
            "step": q["step"],
            "type": q["type"],
            "mode": q["mode"],
            "prompt": q["prompt"],
            "answered": 0,
            "unanswered": 0,
            "first_correct": 0,
            "first_incorrect": 0,
            "attempts_after_feedback": 0,
            "revealed_before_answer": 0,
            "answered_after_reveal": 0,
            "eventually_correct_after_wrong_first": 0,
            "other_version_answers": 0,
        }
        first_counts: dict[str, int] = defaultdict(int)
        all_counts: dict[str, int] = defaultdict(int)
        texts = []
        for activity in students:
            rows = [a for a in activity.attempts if a.question_key == key]
            answers = [a for a in rows if a.kind == "answer"]
            revealed_first = bool(rows) and rows[0].kind == "reveal"
            if revealed_first:
                stats["revealed_before_answer"] += 1
            if not answers:
                stats["unanswered"] += 1
                continue
            stats["answered"] += 1
            stats["attempts_after_feedback"] += sum(1 for a in answers if a.after_feedback)
            first = answers[0]
            if revealed_first:
                stats["answered_after_reveal"] += 1
            elif first.correct is True:
                stats["first_correct"] += 1
            elif first.correct is False:
                stats["first_incorrect"] += 1
                if any(a.correct for a in answers[1:]):
                    stats["eventually_correct_after_wrong_first"] += 1
            for i, a in enumerate(answers):
                answer = _answer(a) or {}
                if answer.get("choice") is not None:
                    if a.question_hash != digest:
                        stats["other_version_answers"] += 1
                    else:
                        all_counts[answer["choice"]] += 1
                        if i == 0 and not revealed_first:
                            first_counts[answer["choice"]] += 1
                if answer.get("text") and (i in (0, len(answers) - 1) or a.review_flag):
                    texts.append(
                        {
                            "attempt_id": a.id,
                            "student_id": activity.student.id,
                            "name": activity.student.name,
                            "text": answer["text"],
                            "choice": answer.get("choice"),
                            "submitted_at": iso(a.submitted_at),
                            "attempt_number": a.attempt_number,
                            "flagged": a.review_flag,
                        }
                    )
        key_info = q.get("answer") or {}
        stats["options"] = [
            {
                "id": o["id"],
                "text": o["text"],
                "correct": o["id"] in key_info.get("correct", []),
                "misconception": key_info.get("misconceptions", {}).get(o["id"]),
                "first_count": first_counts.get(o["id"], 0),
                "all_count": all_counts.get(o["id"], 0),
            }
            for o in q.get("options", [])
        ]
        stats["free_text"] = texts
        out.append(stats)
    return out


def insights(db: Session, lesson: Lesson, include_test: bool = False) -> dict:
    """Where the class is and where understanding breaks down. Aggregates
    leave out withdrawn students and (unless include_test) test students;
    every enrolled student is listed, by name (never ranked by time). Steps
    and questions are those of the live version (what a student starting now
    gets: the active published one, or the latest draft before any publish);
    see _question_stats for how attempts on other versions count."""
    reference = _reference_version(db, lesson)  # what a student starting now gets
    contents = _Contents(db)
    ref_content = contents.get(reference.id) if reference else {"steps": [], "questions": {}}
    activities = _course_activity(db, lesson)
    totals = {"enrolled": 0, "not_started": 0, "in_progress": 0, "completed": 0, "excluded_test": 0, "withdrawn": 0}
    step_counts = {s["key"]: {"viewed": 0, "completed": 0} for s in ref_content["steps"]}
    included: list[_Activity] = []
    students = []
    for activity in activities:
        enrollment = activity.enrollment
        mine = _student_progress(activity, contents, reference)
        steps, content = mine.steps, mine.content or ref_content
        status = _status(activity, mine)
        if enrollment.withdrawn_at is not None:
            totals["withdrawn"] += 1
        elif enrollment.is_test and not include_test:
            totals["excluded_test"] += 1
        else:
            included.append(activity)
            totals["enrolled"] += 1
            totals[status] += 1
            for key, counts in step_counts.items():
                if steps.get(key, {}).get("viewed"):
                    counts["viewed"] += 1
                if steps.get(key, {}).get("completed"):
                    counts["completed"] += 1
        answers = [a for a in activity.attempts if a.kind == "answer"]
        text_questions = {k for k, q in content.get("questions", {}).items() if q["type"] == "free_text"}
        students.append(
            {
                "student_id": activity.student.id,
                "name": activity.student.name,
                "is_test": enrollment.is_test,
                "withdrawn": enrollment.withdrawn_at is not None,
                "status": status,
                "version_number": (
                    db.get(LessonVersion, activity.progress.version_id).number if activity.progress else None
                ),
                "current_step_key": activity.progress.current_step_key if activity.progress else None,
                "viewed_steps": sum(1 for s in steps.values() if s["viewed"]),
                "completed_required": mine.done,
                "required_total": mine.total,
                "optional_completed": optional_completed(content, steps) if steps else 0,
                "last_activity_at": iso(activity.last_activity()),
                "experiments": sum(1 for e in activity.experiments if e.deleted_at is None),
                "committed": bool(activity.commitments),
                "final_recorded": any(c.final_recorded_at is not None for c in activity.commitments),
                "revised_after_final": any(c.after_final_seen for c in activity.commitments),
                "free_text_answers": sum(1 for a in answers if a.question_key in text_questions),
                "flagged": sum(1 for a in activity.attempts if a.review_flag),
            }
        )
    return {
        "lesson": lesson_summary(db, lesson),
        "totals": totals,
        "steps": [
            {
                "key": s["key"],
                "letter": s["letter"],
                "title": s["title"],
                "optional": bool(s.get("optional")),
                "viewed": step_counts[s["key"]]["viewed"],
                "completed": step_counts[s["key"]]["completed"],
            }
            for s in ref_content["steps"]
        ],
        "students": students,
        "questions": _question_stats(ref_content, included),
    }


def student_detail(db: Session, lesson: Lesson, student_id: int) -> dict:
    """One student's path through the lesson: every attempt, experiment
    (deleted ones too) and commitment, oldest first. status is from the
    current evidence (lesson_status). question_changed marks an attempt made
    against a different definition of the question than the live version's
    (the one insights shows), so its choice must not be read with the live
    option texts and misconception tags."""
    enrollment = db.scalar(
        select(Enrollment).where(Enrollment.course_id == lesson.course_id, Enrollment.student_id == student_id)
    )
    if enrollment is None:
        raise LessonError("not_enrolled", "Student is not enrolled in this course", 404)
    student = db.get(Student, student_id)
    progress = _progress(db, enrollment.id, lesson.id)
    reference = _reference_version(db, lesson)
    version = db.get(LessonVersion, progress.version_id) if progress else reference
    attempts = _attempts(db, enrollment.id, lesson.id)
    experiments = _experiments(db, enrollment.id, lesson.id, include_deleted=True)
    commitments = _commitments(db, enrollment.id, lesson.id)
    contents = _Contents(db)
    steps = None
    status = "not_started"
    if version is not None:
        content = contents.get(version.id)
        live = [e for e in experiments if e.deleted_at is None]
        steps = compute_steps(content, evidence_from(progress, attempts, live, commitments))
        status = lesson_status(progress, *required_progress(content, steps))
    live_hashes = (
        {k: question_hash(q) for k, q in contents.get(reference.id)["questions"].items()} if reference else {}
    )
    return {
        "student": {
            "id": student.id,
            "name": student.name,
            "is_test": enrollment.is_test,
            "withdrawn": enrollment.withdrawn_at is not None,
        },
        "status": status,
        "progress": progress_view(progress),
        "version_number": version.number if progress and version else None,
        "steps": steps,
        "attempts": [
            {
                "id": a.id,
                "question_key": a.question_key,
                "step_key": a.step_key,
                "kind": a.kind,
                "attempt_number": a.attempt_number,
                "answer": _answer(a),
                "correct": a.correct,
                "after_feedback": a.after_feedback,
                "submitted_at": iso(a.submitted_at),
                "review_flag": a.review_flag,
                "question_changed": live_hashes.get(a.question_key) != a.question_hash,
            }
            for a in attempts
        ],
        "experiments": [experiment_view(e, include_deleted=True) for e in experiments],
        "commitments": [commitment_view(c) for c in commitments],
    }


def flag_attempt(db: Session, lesson: Lesson, attempt_id: int, flagged: bool) -> dict:
    row = db.get(LessonAttempt, attempt_id)
    if row is None or row.lesson_id != lesson.id:
        raise LessonError("attempt_not_found", "Attempt not found", 404)
    row.review_flag = flagged
    db.commit()
    return {"id": row.id, "review_flag": row.review_flag}


def _csv_cell(value: Any) -> Any:
    # Keep spreadsheet apps from running a name as a formula.
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_csv(db: Session, lesson: Lesson) -> str:
    """Per-student CSV (UTF-8 with BOM, so Excel shows Hebrew names)."""
    reference = _reference_version(db, lesson)
    contents = _Contents(db)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "name",
            "status",
            "required_done",
            "required_total",
            "experiments",
            "committed",
            "first_attempt_correct",
            "last_activity",
            "test_student",
            "withdrawn",
        ]
    )
    for activity in _course_activity(db, lesson):
        mine = _student_progress(activity, contents, reference)
        writer.writerow(
            [
                _csv_cell(activity.student.name),
                _status(activity, mine),
                mine.done,
                mine.total,
                sum(1 for e in activity.experiments if e.deleted_at is None),
                "yes" if activity.commitments else "no",
                _first_correct_count(activity),
                iso(activity.last_activity()) or "",
                "yes" if activity.enrollment.is_test else "no",
                "yes" if activity.enrollment.withdrawn_at is not None else "no",
            ]
        )
    return "﻿" + buf.getvalue()
