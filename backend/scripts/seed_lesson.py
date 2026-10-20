"""Install a guided-lesson fixture into one explicitly chosen course.

    python scripts/seed_lesson.py --course-id 7 --dry-run
    python scripts/seed_lesson.py --course-id 7            # install as a draft
    python scripts/seed_lesson.py --course-id 7 --publish  # install and publish

--course-id falls back to the LESSON_COURSE_ID environment variable; with
neither it refuses (the course is never guessed). It prints the database it is
connected to (from DATABASE_URL, password masked), the course it is about to
touch (id, code, name, year, semester) and what it will do, using the same
install logic as the instructor API (app/services/lessons.py): the lesson
is created as a draft, a changed fixture updates the draft or adds a new draft
version after a published one, and unchanged content is a no-op, so re-running
is safe. It never creates student activity. Exits non-zero on invalid content
or when the fixture is for a different course code (unless
--allow-course-mismatch).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.lessons import FIXTURES  # noqa: E402
from app.models.entities import Course, LessonVersion  # noqa: E402
from app.services import lessons as svc  # noqa: E402


def _args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install a guided-lesson fixture into a course.")
    parser.add_argument("--course-id", type=int, default=None, help="target course id (or LESSON_COURSE_ID)")
    parser.add_argument("--fixture", default="lesson-2", choices=sorted(FIXTURES), help="fixture key")
    parser.add_argument("--allow-course-mismatch", action="store_true", help="install although the course code differs")
    parser.add_argument("--publish", action="store_true", help="also publish the installed version")
    parser.add_argument("--dry-run", action="store_true", help="print what would happen; write nothing")
    return parser.parse_args(argv)


def _fail(exc: svc.LessonError) -> int:
    print(f"Error ({exc.code}): {exc.message}", file=sys.stderr)
    for error in exc.extra.get("errors", []):
        print(f"  - {error}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None, session_factory: Callable[[], Session] | None = None) -> int:
    args = _args(argv)
    course_id = args.course_id
    if course_id is None:
        value = os.environ.get("LESSON_COURSE_ID", "").strip()
        if not value.isdigit():
            print("Refusing to run: pass --course-id N or set LESSON_COURSE_ID (the course is never guessed).", file=sys.stderr)
            return 2
        course_id = int(value)
    if session_factory is None:
        from app.db.session import SessionLocal as session_factory

    with session_factory() as db:
        # Which database this is (password masked): DATABASE_URL decides, and
        # the fallback is a local SQLite file relative to the working directory.
        print(f"Database: {db.get_bind().url.render_as_string(hide_password=True)}")
        course = db.get(Course, course_id)
        if course is None:
            print(f"No course with id {course_id}.", file=sys.stderr)
            return 2
        print(f"Course {course.id}: code {course.code}, {course.name}, {course.year} semester {course.semester}")
        try:
            plan = svc.plan_install(db, course, args.fixture, args.allow_course_mismatch)
        except svc.LessonError as exc:
            return _fail(exc)
        if plan.course_code != course.code:
            print(f"Warning: fixture '{args.fixture}' is for course {plan.course_code}; installing anyway.")
        print(f"Fixture '{args.fixture}' (content sha256 {plan.content_hash}): will {plan.describe()}.")
        target = plan.version
        already_live = (
            target is not None
            and target.status == "published"
            and plan.lesson is not None
            and plan.lesson.active_version_id == target.id
            and plan.lesson.status == "published"
        )
        if args.publish:
            print(
                f"Version {plan.version_number} is already the published version."
                if already_live
                else f"Then: publish version {plan.version_number} (students who haven't started get it)."
            )
        if args.dry_run:
            print("Dry run: nothing written.")
            return 0

        try:
            lesson, plan = svc.install_fixture(db, course, args.fixture, args.allow_course_mismatch)
            if args.publish and not already_live:
                version = db.scalar(
                    select(LessonVersion).where(
                        LessonVersion.lesson_id == lesson.id, LessonVersion.number == plan.version_number
                    )
                )
                svc.publish_version(db, lesson, version.id)
        except svc.LessonError as exc:
            return _fail(exc)
        summary = svc.lesson_summary(db, lesson)
        versions = ", ".join(f"v{v['number']} {v['status']}" for v in summary["versions"])
        print(f"Lesson {lesson.id} '{lesson.slug}': status {lesson.status}; versions: {versions}.")
        if lesson.status != "published":
            print("Students can't see it until a version is published (instructor UI, or --publish).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
