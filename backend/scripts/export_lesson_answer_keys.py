"""One-time export of a lesson's answer keys out of the public repository,
into a private file the operator then loads into the database
(scripts/load_answer_keys.py or the instructor upload).

Lesson 2's keys used to be committed in backend/app/lessons/content/
lesson-2.json; they were removed from the file, but remain in git history.

    python scripts/export_lesson_answer_keys.py                     # lesson 2's keys, from git b03bb04
    python scripts/export_lesson_answer_keys.py --from-git <rev>    # another commit
    python scripts/export_lesson_answer_keys.py --from-file old-lesson-2.json
    python scripts/export_lesson_answer_keys.py --from-db --course-id 7 --slug from-data-to-prediction

The default output, data/private/<slug>.answer-keys.json at the repository
root, is gitignored (as is any *.answer-keys.json); an output inside the
working tree that git would track is refused. The file is written with
owner-only permissions and never overwritten without --force. Prints counts,
never a key.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

# The last main commit whose lesson-2.json still embeds the keys.
DEFAULT_REV = "b03bb04"
FIXTURE_PATH = "backend/app/lessons/content/lesson-2.json"
PRIVATE_DIR = REPO / "data" / "private"


def keys_file(content: dict) -> dict:
    """The private file (answer_keys format) for one lesson's embedded keys."""
    keys = {k: {"answer": q["answer"]} for k, q in content.get("questions", {}).items() if "answer" in q}
    return {"course": content.get("course_code"), "lessons": {content["slug"]: keys}}


def _from_git(rev: str) -> dict:
    res = subprocess.run(["git", "show", f"{rev}:{FIXTURE_PATH}"], cwd=REPO, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"git show {rev}:{FIXTURE_PATH} failed: {res.stderr.strip()}")
    return json.loads(res.stdout)


def _from_db(course_id: int, slug: str, session_factory: Callable[[], Session] | None) -> dict:
    from app.models.entities import Lesson, LessonVersion

    if session_factory is None:
        from app.db.session import SessionLocal as session_factory
    with session_factory() as db:
        print(f"Database: {db.get_bind().url.render_as_string(hide_password=True)}")
        lesson = db.scalar(select(Lesson).where(Lesson.course_id == course_id, Lesson.slug == slug))
        if lesson is None:
            raise SystemExit(f"No lesson '{slug}' in course {course_id}.")
        versions = db.scalars(
            select(LessonVersion).where(LessonVersion.lesson_id == lesson.id).order_by(LessonVersion.number.desc())
        )
        for version in versions:
            content = json.loads(version.content_json)
            if any("answer" in q for q in content.get("questions", {}).values()):
                print(f"Using version {version.number} of '{slug}'.")
                return content
    raise SystemExit(f"No version of '{slug}' embeds answer keys.")


def tracked_by_git(path: Path) -> bool:
    """Whether git would track a file at this path (inside the working tree
    and not ignored)."""
    try:
        path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return False
    res = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=REPO, capture_output=True)
    return res.returncode != 0


def main(argv: list[str] | None = None, session_factory: Callable[[], Session] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a lesson's answer keys to a private file.")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--from-git", metavar="REV", help=f"read {FIXTURE_PATH} at this commit (default {DEFAULT_REV})")
    source.add_argument("--from-file", type=Path, help="read a lesson JSON file that embeds keys")
    source.add_argument("--from-db", action="store_true", help="read the latest installed version that embeds keys")
    parser.add_argument("--course-id", type=int, help="with --from-db")
    parser.add_argument("--slug", default="from-data-to-prediction", help="with --from-db")
    parser.add_argument("--out", type=Path, help="output file (default data/private/<slug>.answer-keys.json)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing output file")
    args = parser.parse_args(argv)

    if args.from_db:
        if args.course_id is None:
            parser.error("--from-db needs --course-id")
        content = _from_db(args.course_id, args.slug, session_factory)
    elif args.from_file:
        content = json.loads(args.from_file.read_text(encoding="utf-8"))
    else:
        content = _from_git(args.from_git or DEFAULT_REV)
    data = keys_file(content)
    count = len(data["lessons"][content["slug"]])
    if not count:
        print("The source embeds no answer keys; nothing written.", file=sys.stderr)
        return 1
    out = args.out or PRIVATE_DIR / f"{content['slug']}.answer-keys.json"
    if tracked_by_git(out):
        print(f"Refusing to write {out}: git would track it. Use a path outside the repository.", file=sys.stderr)
        return 2
    if out.exists() and not args.force:
        print(f"{out} exists; pass --force to overwrite.", file=sys.stderr)
        return 2
    out.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.chmod(out, 0o600)
    print(f"Wrote {count} answer key(s) for '{content['slug']}' (course {data['course']}) to {out}.")
    print("Load them with: python scripts/load_answer_keys.py --course-id <id> --file <that file>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
