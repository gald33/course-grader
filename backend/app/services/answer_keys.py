"""Private answer keys: loading them from the instructor's private file into
the database, and merging them into lesson content on the server.

This repository is public, so no answer key is committed: lesson fixtures
carry questions without keys, and each course's keys sit in
lesson_answer_keys, keyed by lesson slug + question key. They are loaded from
a private JSON file, either through the instructor-only upload
(POST /api/courses/{id}/answer-keys) or with scripts/load_answer_keys.py
against any database. The same file may carry the instructor's contact
email, stored on the course and never sent to students.

The private file, in the shape the instructor's file has (all-or-nothing:
one bad entry and nothing is stored):

    {
      "course": "42052",                      # optional; must match the course code
      "instructor_email": "...",              # optional
      "lessons": {
        "<lesson slug>": {
          "<check key>": {"correct_choice_id": "b", "feedback_he": "..."},
          "<question key>": {"answer": {<a ChoiceAnswerKey or FreeTextAnswerKey>}}
        }
      }
    }

Slugs and keys are those of the lesson content (for the 42052 plan:
content/course-42052/lessons/*.json, slug and steps[].check.key). feedback_he
is one text, shown with the right option after an answer. The richer {"answer": ...} entries are what
scripts/export_lesson_answer_keys.py writes for lesson 2. An unknown slug or
key is an error; questions the file leaves out are reported, not refused (a
file may update a few keys).

Keys reach students only as feedback after an answer (see feedback_for in
app/services/lessons.py); sanitize_for_student() strips them from content.
A lesson version that embeds its own key (installed before keys moved out)
keeps it: merging fills only questions without one.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lessons import FIXTURES, ContentError, load_fixture
from app.lessons.schema import answer_key_problems, needs_answer_key
from app.models.entities import Course, CoursePlanSession, Lesson, LessonAnswerKey, LessonVersion
from app.services.peer_review import utcnow

EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{1,63}$")
MAX_ENTRIES = 2000
SOURCES = ("upload", "script")


class KeyImportError(Exception):
    """Every problem found in a private file. Messages name paths and keys,
    never a key's value."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass
class _Entry:
    slug: str
    question_key: str
    where: str
    raw: Any


@dataclass
class _Parsed:
    entries: list[_Entry] = field(default_factory=list)
    instructor_email: str | None = None


# ---------------------------------------------------------------------------
# Merging (used by app/services/lessons.py)
# ---------------------------------------------------------------------------


def keys_for(db: Session, course_id: int, slug: str) -> dict[str, dict]:
    """The stored keys of one lesson, by question key."""
    rows = db.scalars(
        select(LessonAnswerKey).where(LessonAnswerKey.course_id == course_id, LessonAnswerKey.lesson_slug == slug)
    )
    return {row.question_key: json.loads(row.answer_json) for row in rows}


def merge_keys(content: dict, keys: dict[str, dict]) -> tuple[dict, list[str]]:
    """The content with each question that has no embedded key given its
    stored one (a new dict; `content` is not changed), and the questions
    whose stored key doesn't fit this version (say the options changed after
    the keys were loaded). Those are left without a key: a question that
    can't be checked is shown as such, never marked wrong against an option
    that no longer exists."""
    questions = {}
    mismatched = []
    for qkey, question in content.get("questions", {}).items():
        if "answer" not in question and qkey in keys:
            if answer_key_problems(question, keys[qkey]):
                mismatched.append(qkey)
            else:
                question = {**question, "answer": keys[qkey]}
        questions[qkey] = question
    return {**content, "questions": questions}, mismatched


def with_keys(content: dict, keys: dict[str, dict]) -> dict:
    """merge_keys without the list of mismatched keys."""
    return merge_keys(content, keys)[0]


def missing_keys(content: dict) -> list[str]:
    """Questions that can't be checked: they need a key and have none."""
    return [k for k, q in content.get("questions", {}).items() if needs_answer_key(q) and "answer" not in q]


# ---------------------------------------------------------------------------
# Parsing the private file
# ---------------------------------------------------------------------------


def _parse(data: Any) -> tuple[_Parsed, list[str]]:
    """The file's entries and email, and the problems with its structure."""
    if not isinstance(data, dict):
        raise KeyImportError(["the file must be a JSON object"])
    errors: list[str] = []
    parsed = _Parsed()
    for name in data:
        if name not in ("course", "instructor_email", "lessons"):
            errors.append(f"unknown top-level field '{name}'")

    email = data.get("instructor_email")
    if email is not None:
        if not isinstance(email, str) or len(email) > 320 or not EMAIL.match(email.strip()):
            errors.append("instructor email: not an email address")
        else:
            parsed.instructor_email = email.strip()

    lessons = data.get("lessons")
    if lessons is not None:
        if not isinstance(lessons, dict):
            errors.append("lessons: expected an object of lesson slug -> questions")
        else:
            for slug, questions in lessons.items():
                if not isinstance(questions, dict):
                    errors.append(f"lessons.{slug}: expected an object of question key -> key")
                    continue
                for qkey, raw in questions.items():
                    parsed.entries.append(_Entry(slug, qkey, f"lessons.{slug}.{qkey}", raw))
    if lessons is None and parsed.instructor_email is None:
        errors.append("the file has no lessons or instructor email")
    if len(parsed.entries) > MAX_ENTRIES:
        errors.append(f"more than {MAX_ENTRIES} keys")
    seen: set[tuple[str, str]] = set()
    for entry in parsed.entries:
        pair = (entry.slug, entry.question_key)
        if pair in seen:
            errors.append(f"{entry.where}: '{entry.slug}' / '{entry.question_key}' is given more than once")
        seen.add(pair)
    return parsed, errors


def _to_key(entry: _Entry, question: dict) -> tuple[dict | None, list[str]]:
    """The entry as a stored answer key, or the problems with it."""
    raw = entry.raw
    if not isinstance(raw, dict):
        return None, [f"{entry.where}: expected an object"]
    if "answer" in raw:
        if set(raw) != {"answer"}:
            return None, [f"{entry.where}: 'answer' can't be combined with other fields"]
        return raw["answer"], []
    allowed = {"correct_choice_id", "feedback_he"}
    if set(raw) - allowed or "correct_choice_id" not in raw:
        return None, [f"{entry.where}: expected correct_choice_id (and feedback_he) or answer"]
    if question.get("type") != "single_choice":
        return None, [f"{entry.where}: correct_choice_id given for a question that is not single choice"]
    correct = raw["correct_choice_id"]
    if not isinstance(correct, str):
        return None, [f"{entry.where}: correct_choice_id must be a string"]
    key: dict = {"correct": [correct], "feedback": {}, "misconceptions": {}}
    feedback = raw.get("feedback_he")
    if isinstance(feedback, str):
        if feedback.strip():
            key["explanation"] = feedback.strip()
    elif feedback is not None:
        return None, [f"{entry.where}: feedback_he must be a text"]
    return key, []


def _definitions(db: Session, course: Course, slug: str, cache: dict[str, list[tuple[str, dict]]]) -> list[tuple[str, dict]]:
    """Every definition of the lesson's content a key would serve, latest
    first, labelled: each installed version ("version N"), or, before the
    lesson is installed, the bundled fixture with that slug for this
    course's code ("the lesson file")."""
    if slug in cache:
        return cache[slug]
    lesson = db.scalar(select(Lesson).where(Lesson.course_id == course.id, Lesson.slug == slug))
    found: list[tuple[str, dict]] = []
    if lesson is not None:
        versions = db.scalars(
            select(LessonVersion).where(LessonVersion.lesson_id == lesson.id).order_by(LessonVersion.number.desc())
        )
        found = [(f"version {v.number}", json.loads(v.content_json)) for v in versions]
    if not found:
        for key in FIXTURES:
            try:
                raw = load_fixture(key)
            except ContentError:
                continue
            if raw.get("slug") == slug and raw.get("course_code") == course.code:
                found.append(("the lesson file", raw))
    cache[slug] = found
    return found


def import_keys(db: Session, course: Course, data: Any, source: str, dry_run: bool = False) -> dict:
    """Validate the private file against the course's lessons and store every
    key in it (insert or replace), plus the instructor email if given. All or
    nothing: any problem raises KeyImportError and stores nothing. The summary
    counts keys; it never repeats one."""
    if source not in SOURCES:
        raise ValueError(source)
    parsed, errors = _parse(data)
    code = data.get("course")
    if code is not None and str(code) != course.code:
        errors.append(f"course: the file is for another course, not {course.code}")
    cache: dict[str, list[tuple[str, dict]]] = {}
    keys: dict[tuple[str, str], dict] = {}
    older_mismatch: list[str] = []
    for entry in parsed.entries:
        definitions = _definitions(db, course, entry.slug, cache)
        if not definitions:
            errors.append(f"{entry.where}: no lesson '{entry.slug}' in course {course.code}")
            continue
        questions = [
            (label, d["questions"][entry.question_key])
            for label, d in definitions
            if entry.question_key in d.get("questions", {})
        ]
        if not questions:
            errors.append(f"{entry.where}: lesson '{entry.slug}' has no question '{entry.question_key}'")
            continue
        # The key must fit the latest definition of the question. An older
        # version it doesn't fit (its options changed) is reported: that
        # version can't check the question until its own key is fixed, and
        # it never marks an answer against an option it doesn't have.
        (_label, latest), older = questions[0], questions[1:]
        key, problems = _to_key(entry, latest)
        if key is not None:
            problems += [f"{entry.where}: {p}" for p in answer_key_problems(latest, key)]
        if problems:
            errors += list(dict.fromkeys(problems))
            continue
        for label, question in older:
            if "answer" not in question and answer_key_problems(question, key):
                older_mismatch.append(f"{entry.slug}/{entry.question_key} ({label})")
        keys[(entry.slug, entry.question_key)] = key
    if errors:
        raise KeyImportError(errors)
    not_in_file = _not_in_file(db, course, {e.slug for e in parsed.entries}, set(keys), cache)

    existing = {
        (row.lesson_slug, row.question_key): row
        for row in db.scalars(select(LessonAnswerKey).where(LessonAnswerKey.course_id == course.id))
    }
    counts = {"added": 0, "replaced": 0, "unchanged": 0}
    now = utcnow()
    for (slug, qkey), key in keys.items():
        text = json.dumps(key, ensure_ascii=False, sort_keys=True)
        row = existing.get((slug, qkey))
        if row is None:
            counts["added"] += 1
            if not dry_run:
                db.add(
                    LessonAnswerKey(
                        course_id=course.id,
                        lesson_slug=slug,
                        question_key=qkey,
                        answer_json=text,
                        source=source,
                        created_at=now,
                        updated_at=now,
                    )
                )
        elif row.answer_json == text:
            counts["unchanged"] += 1
        else:
            counts["replaced"] += 1
            if not dry_run:
                row.answer_json, row.source, row.updated_at = text, source, now
    contact = "not in file"
    if parsed.instructor_email is not None:
        contact = "unchanged" if course.instructor_email == parsed.instructor_email else "set"
        if not dry_run:
            course.instructor_email = parsed.instructor_email
    if dry_run:
        db.rollback()
    else:
        db.commit()
    lessons = sorted({slug for slug, _ in keys})
    return {
        "keys": len(keys),
        **counts,
        "lessons": lessons,
        "not_in_file": not_in_file,
        # Older versions whose options a key doesn't fit: "<slug>/<key> (version N)".
        "older_versions_not_fitting": older_mismatch,
        "instructor_contact": contact,
        "dry_run": dry_run,
    }


def _not_in_file(
    db: Session, course: Course, slugs: set[str], given: set[tuple[str, str]], cache: dict[str, list[tuple[str, dict]]]
) -> list[str]:
    """What the file leaves out: "<slug>/<key>" for each question of a lesson
    in the file that needs a key and isn't given, and "<slug>" for each
    lesson of the course's imported plan that the file doesn't mention."""
    out = []
    for slug in sorted(slugs):
        needed: dict[str, None] = {}
        for _label, definition in cache.get(slug, []):
            for qkey, q in definition.get("questions", {}).items():
                if needs_answer_key(q):
                    needed.setdefault(qkey)
        out += [f"{slug}/{qkey}" for qkey in needed if (slug, qkey) not in given]
    planned = db.scalars(select(CoursePlanSession.lesson_slug).where(CoursePlanSession.course_id == course.id))
    out += sorted({slug for slug in planned if slug not in slugs})
    return out


# ---------------------------------------------------------------------------
# Instructor status
# ---------------------------------------------------------------------------


def key_status(db: Session, course: Course) -> dict:
    """Per installed lesson: how many of its questions can be checked, and
    which can't (no embedded and no stored key), for the latest version and
    the one students get. Counts and question keys only, never a key."""
    stored: dict[str, set[str]] = {}
    for row in db.scalars(select(LessonAnswerKey).where(LessonAnswerKey.course_id == course.id)):
        stored.setdefault(row.lesson_slug, set()).add(row.question_key)
    lessons = []
    for lesson in db.scalars(select(Lesson).where(Lesson.course_id == course.id).order_by(Lesson.position, Lesson.id)):
        lessons.append({"lesson_id": lesson.id, "slug": lesson.slug, **lesson_key_status(db, lesson)})
    return {
        "instructor_contact_set": bool(course.instructor_email),
        "stored_keys": sum(len(v) for v in stored.values()),
        "lessons": lessons,
    }


def lesson_key_status(db: Session, lesson: Lesson) -> dict:
    """needed / missing / mismatched for the lesson's latest version and its live one."""
    keys = keys_for(db, lesson.course_id, lesson.slug)
    versions = list(
        db.scalars(select(LessonVersion).where(LessonVersion.lesson_id == lesson.id).order_by(LessonVersion.number))
    )

    def status(version: LessonVersion | None) -> dict | None:
        if version is None:
            return None
        content, mismatched = merge_keys(json.loads(version.content_json), keys)
        needed = [k for k, q in content["questions"].items() if needs_answer_key(q)]
        # missing: no usable key (mismatched ones included); mismatched: a
        # stored key that doesn't fit this version and must be re-imported.
        return {
            "version_number": version.number,
            "needed": len(needed),
            "missing": missing_keys(content),
            "mismatched": mismatched,
        }

    live = next((v for v in versions if v.id == lesson.active_version_id), None)
    return {"latest": status(versions[-1] if versions else None), "live": status(live)}
