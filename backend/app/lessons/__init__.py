"""Guided lessons: the content schema (schema.py) and the authored lesson
fixtures shipped with the app (content/*.json).

A fixture is installed into a course as a draft lesson version (the instructor
API's install, or scripts/seed_lesson.py), previewed, then published.

A course plan (content/course-<code>/plan.json, built from a course-content
handoff by scripts/build_course_plan.py; see course_plan.py) adds one draft
lesson fixture per session, registered here as "<code>-<slug>".

Fixtures carry no answer keys: those are private and live in the database
(app/services/answer_keys.py).

Authoring rules for a revision of a fixture that students may already have
answered: keep step, question, ack and option ids stable, and never change
what an existing option id *means* (to replace an option, add a new id and
drop the old one). Students stay pinned to the version they started; the
instructor's option bars count only answers given to the identical question
(same question hash) and report the rest as answers to another version.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.lessons.schema import (
    ContentError,
    LessonContent,
    canonical_hash,
    parse_content_json,
    question_hash,
    sanitize_for_student,
    validate_content,
)

CONTENT_DIR = Path(__file__).parent / "content"
FIXTURES: dict[str, Path] = {"lesson-2": CONTENT_DIR / "lesson-2.json"}

# Course plans by course code, and their lesson fixtures (fixture key -> plan).
PLANS: dict[str, Path] = {}
PLAN_FIXTURES: dict[str, str] = {}
for _plan in sorted(CONTENT_DIR.glob("course-*/plan.json")):
    _code = _plan.parent.name.removeprefix("course-")
    PLANS[_code] = _plan
    for _lesson in sorted(_plan.parent.glob("lesson-*.json")):
        FIXTURES[f"{_code}-{_lesson.stem}"] = _lesson
        PLAN_FIXTURES[f"{_code}-{_lesson.stem}"] = _code


def load_plan(code: str) -> dict:
    """The course plan for a course code. KeyError for an unknown code."""
    return json.loads(PLANS[code].read_text(encoding="utf-8"))

# The site's static files (frontend/public), where lesson assets are served
# from. Only present in a full checkout: the hosted API bundle has no frontend,
# so asset files are checked when this exists and skipped otherwise.
_PARENTS = Path(__file__).resolve().parents  # lessons, app, backend, repo root
ASSETS_ROOT = _PARENTS[min(3, len(_PARENTS) - 1)] / "frontend" / "public"


def assets_root() -> Path | None:
    return ASSETS_ROOT if ASSETS_ROOT.is_dir() else None


def load_fixture(key: str) -> dict:
    """The raw (unvalidated) fixture JSON. KeyError for an unknown key;
    ContentError when the file is missing or not valid JSON."""
    path = FIXTURES[key]
    if not path.is_file():
        raise ContentError([f"fixture file {path.name} is missing"])
    return parse_content_json(path.read_text(encoding="utf-8"))


__all__ = [
    "ASSETS_ROOT",
    "FIXTURES",
    "PLANS",
    "PLAN_FIXTURES",
    "ContentError",
    "LessonContent",
    "assets_root",
    "canonical_hash",
    "load_fixture",
    "load_plan",
    "parse_content_json",
    "question_hash",
    "sanitize_for_student",
    "validate_content",
]
