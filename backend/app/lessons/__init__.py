"""Guided lessons: the content schema (schema.py) and the authored lesson
fixtures shipped with the app (content/*.json).

A fixture is installed into a course as a draft lesson version (the instructor
API's install, or scripts/seed_lesson.py), previewed, then published.
"""

from __future__ import annotations

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
    "ContentError",
    "LessonContent",
    "assets_root",
    "canonical_hash",
    "load_fixture",
    "parse_content_json",
    "question_hash",
    "sanitize_for_student",
    "validate_content",
]
