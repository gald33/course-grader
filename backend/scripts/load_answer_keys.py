"""Load the instructor's private answer-key file into one explicitly chosen
course, in any database (the hosted one included):

    python scripts/load_answer_keys.py --course-id 7 --file ~/private/keys.json --dry-run
    python scripts/load_answer_keys.py --course-id 7 --file ~/private/keys.json

DATABASE_URL decides the database (printed, password masked). The file's
format and checks are those of the instructor upload (app/services/
answer_keys.py): every key is validated against the course's lessons first,
and one bad entry stores nothing. Keys that fit a lesson's latest version
but not a published one (students on it couldn't be checked) are listed and
refused unless --confirm-published-breaks. Re-running is safe: unchanged
keys are left alone. Prints counts, never a key; nothing is written next to the file.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.models.entities import Course  # noqa: E402
from app.services import answer_keys  # noqa: E402


def main(argv: list[str] | None = None, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load private answer keys into a course.")
    parser.add_argument("--course-id", type=int, required=True, help="target course id (never guessed)")
    parser.add_argument("--file", type=Path, required=True, help="the private answer-key JSON file")
    parser.add_argument("--dry-run", action="store_true", help="validate and report; write nothing")
    parser.add_argument(
        "--confirm-published-breaks",
        action="store_true",
        help="store keys even when a published version they don't fit could no longer check those questions",
    )
    args = parser.parse_args(argv)
    try:
        data = json.loads(args.file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"Can't read {args.file}: {type(exc).__name__}", file=sys.stderr)
        return 2
    if session_factory is None:
        from app.db.session import SessionLocal as session_factory

    with session_factory() as db:
        print(f"Database: {db.get_bind().url.render_as_string(hide_password=True)}")
        course = db.get(Course, args.course_id)
        if course is None:
            print(f"No course with id {args.course_id}.", file=sys.stderr)
            return 2
        print(f"Course {course.id}: code {course.code}, {course.name}, {course.year} semester {course.semester}")
        try:
            result = answer_keys.import_keys(
                db,
                course,
                data,
                source="script",
                dry_run=args.dry_run,
                confirm_published_breaks=args.confirm_published_breaks,
            )
        except answer_keys.BreaksPublishedVersion as exc:
            print("These keys don't fit a published version students may be on; nothing was stored:", file=sys.stderr)
            for item in exc.breaks:
                print(f"  - {item}", file=sys.stderr)
            print("Re-run with --confirm-published-breaks to store them anyway.", file=sys.stderr)
            return 3
        except answer_keys.KeyImportError as exc:
            print("The file has errors; nothing was stored:", file=sys.stderr)
            for error in exc.errors:
                print(f"  - {error}", file=sys.stderr)
            return 1
    verb = "Would store" if args.dry_run else "Stored"
    print(
        f"{verb} {result['keys']} key(s) for {len(result['lessons'])} lesson(s): "
        f"{result['added']} new, {result['replaced']} replaced, {result['unchanged']} unchanged. "
        f"Instructor contact: {result['instructor_contact']}."
    )
    if result["older_versions_not_fitting"]:
        print(
            "Older versions these keys don't fit (those questions can't be checked there): "
            + ", ".join(result["older_versions_not_fitting"])
        )
    if result["published_versions_not_fitting"]:
        print("  of which published (students may be on them): " + ", ".join(result["published_versions_not_fitting"]))
    if result["not_in_file"]:
        print(f"Not in the file (left as they are): {', '.join(result['not_in_file'])}")
    if args.dry_run:
        print("Dry run: nothing written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
