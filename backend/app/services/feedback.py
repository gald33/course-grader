"""Feedback about the site itself, filed from the Feedback button on every
page, kept as org-core tickets-core tickets (SPEC §17; the record is
org_core/tickets/schema.sql, the tables are migration 0027).

Two sources, both people: `student` (from a student's own pages, under their
course link) and `instructor` (from the instructor pages). A student may send
without their name: then `reporter_ref` is null and nothing stored names them.
The student's course link token is a credential, so it is cut out of
everything the page sends, named or not.

The reporter picks one of three categories. "Something's broken" files as
kind `bug` and "an idea" as `feature_request`; "this is confusing" is left
unclassified (no kind), since it can be a bug, a question or a lesson that
needs rewording, and a person decides which. The category itself is kept in
`refs.category` either way.

The page's context (where it was sent from and on what) is bounded the same
way org-core's dashboard bounds it (asks.py): at most MAX_FACTS named
one-line facts, each cut at MAX_FACT_CHARS, and MAX_CONTEXT_CHARS in all.
A long value is cut, never refused, so a report always gets through.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Course, Enrollment, FeedbackTicket, FeedbackTicketNote

SOURCES = ("student", "instructor")
CATEGORIES = {"broken": ["bug"], "confusing": [], "idea": ["feature_request"]}
STATUSES = ("open", "handled", "needs_attention", "needs_more_info", "needs_followup", "wontfix", "closed")
KINDS = ("bug", "feature_request", "praise", "question", "unclear")

MIN_TEXT = 3
MAX_TEXT = 4000
MAX_FACTS = 24
MAX_FACT_CHARS = 400
MAX_CONTEXT_CHARS = 3000
MAX_NOTE = 8000
# Facts that say where in the site the report was sent from go to `refs`, beside the category; the rest
# (viewport, browser, language, time zone, the page's build) describe the device and go to `metadata`.
REF_FACTS = ("path", "title", "section", "tab", "lesson", "step", "assignment", "presentation")
_FACT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class FeedbackError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.replace(microsecond=0).isoformat() + "Z"


def bounded_context(raw: Any, redact: tuple[str, ...] = ()) -> dict[str, str]:
    """The page's facts, bounded: named one-line strings only, each cut, the whole capped, `redact` cut out."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    total = 0
    for name, value in raw.items():
        if len(out) >= MAX_FACTS:
            break
        if not isinstance(name, str) or not _FACT_NAME.match(name):
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            continue
        text = " ".join(str(value).split())
        for secret in redact:
            if secret:
                text = text.replace(secret, "…")
        text = text[:MAX_FACT_CHARS]
        if not text:
            continue
        if total + len(text) > MAX_CONTEXT_CHARS:
            text = text[: max(0, MAX_CONTEXT_CHARS - total)]
            if not text:
                break
        out[name] = text
        total += len(text)
    return out


def deployed_version() -> dict[str, str]:
    """The API build that took the report (tickets-core `version_source: vercel-deployment`)."""
    version = {"captured_at": _iso(_now()) or ""}
    for key, env in (
        ("git_sha", "VERCEL_GIT_COMMIT_SHA"),
        ("deployment", "VERCEL_DEPLOYMENT_ID"),
        ("url", "VERCEL_URL"),
        ("env", "VERCEL_ENV"),
    ):
        if os.environ.get(env):
            version[key] = os.environ[env]
    return version


def file_ticket(
    db: Session,
    *,
    source: str,
    category: str,
    text: str,
    context: Any = None,
    course_id: int | None = None,
    enrollment: Enrollment | None = None,
    anonymous: bool = False,
) -> FeedbackTicket:
    if source not in SOURCES:
        raise FeedbackError(422, "invalid_source", f"source must be one of {', '.join(SOURCES)}")
    if category not in CATEGORIES:
        raise FeedbackError(422, "invalid_category", f"category must be one of {', '.join(CATEGORIES)}")
    body = (text or "").strip()
    if len(body) < MIN_TEXT:
        raise FeedbackError(422, "text_too_short", "Write a few words about what happened")
    if len(body) > MAX_TEXT:
        raise FeedbackError(422, "text_too_long", f"Keep it under {MAX_TEXT} characters")
    if course_id is not None and db.get(Course, course_id) is None:
        raise FeedbackError(404, "unknown_course", "Unknown course")

    redact = (enrollment.review_token,) if enrollment is not None and enrollment.review_token else ()
    facts = bounded_context(context, redact=redact)
    refs: dict[str, Any] = {"category": category}
    meta: dict[str, Any] = {}
    for name, value in facts.items():
        (refs if name in REF_FACTS else meta)[name] = value
    if course_id is not None:
        refs["course_id"] = course_id

    reporter_ref: str | None
    if source == "student":
        if enrollment is None:
            raise FeedbackError(400, "no_enrollment", "A student's ticket needs their enrollment")
        meta["anonymous"] = bool(anonymous)
        reporter_ref = None if anonymous else f"enrollment:{enrollment.id}"
    else:
        reporter_ref = "instructor"

    now = _now()
    ticket = FeedbackTicket(
        id=str(uuid.uuid4()),
        source=source,
        reporter_ref=reporter_ref,
        course_id=course_id,
        feedback_text=body,
        status="open",
        kinds_json=json.dumps(CATEGORIES[category]),
        refs_json=json.dumps(refs, ensure_ascii=False),
        metadata_json=json.dumps(meta, ensure_ascii=False),
        deployed_version_json=json.dumps(deployed_version()),
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def ticket_row(ticket: FeedbackTicket) -> dict[str, Any]:
    """A ticket in tickets-core's words: what `org tickets --source api` reads from /api/admin/feedback."""
    return {
        "id": ticket.id,
        "source": ticket.source,
        "reporter_ref": ticket.reporter_ref,
        "course_id": ticket.course_id,
        "feedback_text": ticket.feedback_text,
        "status": ticket.status,
        "kinds": json.loads(ticket.kinds_json or "[]"),
        "refs": json.loads(ticket.refs_json or "{}"),
        "metadata": json.loads(ticket.metadata_json or "{}"),
        "sentiment_score": ticket.sentiment_score,
        "deployed_version": json.loads(ticket.deployed_version_json) if ticket.deployed_version_json else None,
        "created_at": _iso(ticket.created_at),
        "updated_at": _iso(ticket.updated_at),
    }


def note_row(note: FeedbackTicketNote) -> dict[str, Any]:
    return {
        "id": note.id,
        "ticket_id": note.ticket_id,
        "author": note.author,
        "note": note.note,
        "meta": json.loads(note.meta_json or "{}"),
        "created_at": _iso(note.created_at),
    }


def list_tickets(db: Session, *, limit: int, offset: int, status: str | None = None) -> list[dict[str, Any]]:
    q = select(FeedbackTicket)
    if status is not None:
        q = q.where(FeedbackTicket.status == status)
    q = q.order_by(FeedbackTicket.created_at.desc(), FeedbackTicket.id).limit(limit).offset(offset)
    return [ticket_row(t) for t in db.scalars(q)]


def _ticket(db: Session, ticket_id: str) -> FeedbackTicket:
    ticket = db.get(FeedbackTicket, ticket_id)
    if ticket is None:
        raise FeedbackError(404, "unknown_ticket", "Unknown ticket")
    return ticket


def get_ticket(db: Session, ticket_id: str) -> dict[str, Any]:
    return ticket_row(_ticket(db, ticket_id))


def list_notes(db: Session, ticket_id: str) -> list[dict[str, Any]]:
    _ticket(db, ticket_id)
    q = (
        select(FeedbackTicketNote)
        .where(FeedbackTicketNote.ticket_id == ticket_id)
        .order_by(FeedbackTicketNote.created_at, FeedbackTicketNote.id)
    )
    return [note_row(n) for n in db.scalars(q)]


def add_note(db: Session, ticket_id: str, *, author: str, note: str, meta: Any = None) -> dict[str, Any]:
    ticket = _ticket(db, ticket_id)
    author = (author or "").strip()
    body = (note or "").strip()
    if not author or len(author) > 128:
        raise FeedbackError(422, "invalid_author", "author is a role or a person's name, up to 128 characters")
    if not body or len(body) > MAX_NOTE:
        raise FeedbackError(422, "invalid_note", f"note is 1 to {MAX_NOTE} characters")
    now = _now()
    row = FeedbackTicketNote(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author=author,
        note=body,
        meta_json=json.dumps(meta if isinstance(meta, dict) else {}, ensure_ascii=False),
        created_at=now,
    )
    ticket.updated_at = now
    db.add(row)
    db.commit()
    db.refresh(row)
    return note_row(row)


def update_ticket(
    db: Session, ticket_id: str, *, status: str | None = None, kinds: list[str] | None = None
) -> dict[str, Any]:
    ticket = _ticket(db, ticket_id)
    if status is not None:
        if status not in STATUSES:
            raise FeedbackError(422, "invalid_status", f"status must be one of {', '.join(STATUSES)}")
        ticket.status = status
    if kinds is not None:
        bad = [k for k in kinds if k not in KINDS]
        if bad:
            raise FeedbackError(422, "invalid_kinds", f"kinds are a set of {', '.join(KINDS)}")
        ticket.kinds_json = json.dumps(sorted(set(kinds), key=KINDS.index))
    ticket.updated_at = _now()
    db.commit()
    db.refresh(ticket)
    return ticket_row(ticket)
