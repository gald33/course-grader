"""Importing a course plan (app/lessons/course_plan.py) into a course, and the
instructor's per-lesson readiness table.

Importing records the plan's sessions and installs each session's lesson as a
draft through the same install path as any lesson fixture: nothing is
published, nothing touches students, the grade formula or peer-review rounds,
and re-running it is safe (unchanged lessons are a no-op, changed ones go
into a draft version; the instructor's reviewed / live-verified marks stay).

Readiness keeps five states apart and never sums them into one "ready":
drafted (a lesson version exists), reviewed (the instructor marked it),
runnable (what the handoff says about runnable material), published (students
can open it) and live verified (the instructor checked it live, or the handoff
says it was taught).
"""

from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lessons import PLANS, load_plan
from app.models.entities import Course, CoursePlanSession, Lesson, LessonVersion
from app.services import answer_keys
from app.services import lessons as lessons_svc
from app.services.lessons import LessonError, iso
from app.services.peer_review import utcnow


def available_plans(course: Course) -> list[dict]:
    out = []
    for code in PLANS:
        plan = load_plan(code)
        out.append(
            {
                "code": code,
                "title": plan["title"],
                "academic_year": plan["academic_year"],
                "semester": plan["semester"],
                "session_count": plan["session_count"],
                "matches_course": code == course.code,
                "syllabus_grading": plan["syllabus_grading"],
            }
        )
    return out


def import_plan(db: Session, course: Course, plan_code: str, allow_course_mismatch: bool = False) -> dict:
    """Record the plan's sessions and install every session's lesson as a
    draft. Returns what each install did."""
    if plan_code not in PLANS:
        raise LessonError("unknown_plan", f"No course plan '{plan_code}'", 404)
    if plan_code != course.code and not allow_course_mismatch:
        raise LessonError(
            "course_mismatch",
            f"This plan is for course {plan_code}; the selected course is {course.code} "
            f"({course.name}, {course.year} {course.semester})",
            409,
        )
    plan = load_plan(plan_code)
    existing = {
        row.session_number: row
        for row in db.scalars(select(CoursePlanSession).where(CoursePlanSession.course_id == course.id))
    }
    now = utcnow()
    for session in plan["sessions"]:
        details = {
            **plan["lessons"][session["lesson_slug"]],
            "existing_fixture_keys": session["existing_fixture_keys"],
        }
        values = {
            "plan_code": plan_code,
            "title": session["title"],
            "lesson_slug": session["lesson_slug"],
            "fixture_key": session["fixture_key"],
            "presentation_round": session["presentation_round"],
            "final_presentation_part": session["final_presentation_part"],
            "formal_presentations": session["formal_presentations"],
            "planned_presenting_teams": session["planned_presenting_teams"],
            "details_json": json.dumps(details, ensure_ascii=False, sort_keys=True),
        }
        row = existing.get(session["session"])
        if row is None:
            db.add(
                CoursePlanSession(
                    course_id=course.id, session_number=session["session"], imported_at=now, updated_at=now, **values
                )
            )
        elif any(getattr(row, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(row, k, v)
            row.updated_at = now
    db.commit()
    installs = []
    for session in plan["sessions"]:
        lesson, install = lessons_svc.install_fixture(db, course, session["fixture_key"], allow_course_mismatch)
        installs.append({"session": session["session"], "slug": lesson.slug, "action": install.action})
    return {"installs": installs, **plan_view(db, course)}


def set_marks(db: Session, course: Course, number: int, reviewed: bool | None, live_verified: bool | None) -> dict:
    row = db.scalar(
        select(CoursePlanSession).where(CoursePlanSession.course_id == course.id, CoursePlanSession.session_number == number)
    )
    if row is None:
        raise LessonError("session_not_found", "No such session in this course's plan", 404)
    now = utcnow()
    if reviewed is not None:
        row.reviewed_at = (row.reviewed_at or now) if reviewed else None
    if live_verified is not None:
        row.live_verified_at = (row.live_verified_at or now) if live_verified else None
    row.updated_at = now
    db.commit()
    return plan_view(db, course)


def _runnable(readiness: dict, authored: dict | None = None) -> dict:
    """What the handoff says about runnable material, unless the lesson was
    authored in this repository with runnable material of its own (what was
    built and run there; the instructor has not reviewed it)."""
    if authored and authored.get("runnable"):
        return {"state": "built_not_reviewed", "note": authored["runnable"]}
    missing = [item for item in readiness.get("still_needed", []) if "runnable" in item or "demo" in item]
    if missing:
        return {"state": "not_built", "note": "; ".join(missing)}
    if readiness.get("status", "").startswith("prepared_assets"):
        return {"state": "prepared_not_rerun", "note": "assets prepared per the handoff; not re-run by this app"}
    return {"state": "unknown", "note": "the handoff does not say"}


def _lesson_state(db: Session, lesson: Lesson | None) -> dict | None:
    if lesson is None:
        return None
    versions = list(
        db.scalars(select(LessonVersion).where(LessonVersion.lesson_id == lesson.id).order_by(LessonVersion.number))
    )
    live = next((v for v in versions if v.id == lesson.active_version_id), None)
    return {
        "id": lesson.id,
        "slug": lesson.slug,
        "title": lesson.title,
        "status": lesson.status,
        "latest_version": versions[-1].number if versions else None,
        "published_version": live.number if live and lesson.status == "published" else None,
        "answer_keys": answer_keys.lesson_key_status(db, lesson),
    }


def plan_view(db: Session, course: Course) -> dict:
    """The imported plan's sessions with each lesson's readiness (instructor only)."""
    rows = list(
        db.scalars(
            select(CoursePlanSession)
            .where(CoursePlanSession.course_id == course.id)
            .order_by(CoursePlanSession.session_number)
        )
    )
    lessons = {l.slug: l for l in db.scalars(select(Lesson).where(Lesson.course_id == course.id))}
    by_fixture = {l.fixture_key: l for l in lessons.values() if l.fixture_key}
    sessions = []
    for row in rows:
        details = json.loads(row.details_json or "{}")
        readiness = details.get("readiness", {})
        lesson = _lesson_state(db, lessons.get(row.lesson_slug))
        sessions.append(
            {
                "session": row.session_number,
                "title": row.title,
                "presentation_round": row.presentation_round,
                "final_presentation_part": row.final_presentation_part,
                "formal_presentations": row.formal_presentations,
                "planned_presenting_teams": row.planned_presenting_teams,
                "lesson_slug": row.lesson_slug,
                "fixture_key": row.fixture_key,
                "lesson": lesson,
                "existing_lessons": [
                    _lesson_state(db, by_fixture[k]) for k in details.get("existing_fixture_keys", []) if k in by_fixture
                ],
                "content_status": details.get("content_status"),
                "checks": details.get("checks", []),
                "homework": details.get("homework"),
                "readiness": {
                    "drafted": bool(lesson and lesson["latest_version"]),
                    "reviewed_at": iso(row.reviewed_at),
                    "runnable": _runnable(readiness, details.get("authored")),
                    "published": bool(lesson and lesson["published_version"]),
                    "live_verified_at": iso(row.live_verified_at),
                    "handoff_says_taught": bool(readiness.get("published_or_taught_verified")),
                    "available": readiness.get("available", []),
                    "still_needed": readiness.get("still_needed", []),
                },
            }
        )
    return {
        "plan_code": rows[0].plan_code if rows else None,
        "plans": available_plans(course),
        "sessions": sessions,
    }
