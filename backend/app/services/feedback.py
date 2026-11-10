"""Feedback about the site itself, filed from the Feedback button on every
page, kept as org-core tickets-core tickets (SPEC §17; the record is
org_core/tickets/schema.sql, the tables are migration 0027).

Two sources, both people: `student` (from a student's own pages, under their
course link) and `instructor` (from the instructor pages). A student may send
without their name: then `reporter_ref` is null and nothing stored names them.
A course link token is a student's credential, so no ticket or note keeps
one, named or anonymous, whoever pasted it: every course link (/r/<token>) is
cut to /r/… in the text, the page's facts and notes, and a student's own token
is cut wherever it appears (scrub()).

The reporter picks one of three categories. "Something's broken" files as
kind `bug` and "an idea" as `feature_request`; "this is confusing" is left
unclassified (no kind), since it can be a bug, a question or a lesson that
needs rewording, and a person decides which. The category itself is kept in
`refs.category` either way.

An anonymous ticket is coarsened before anything is stored (the operator,
2026-11-10, on Reed's N2 on #52: "Coarsen it"): it keeps the day it was sent,
the page and the lesson, and never the time of day, the step, or anything
about the device or the build, which in a small class could tell who sent it
next to the instructor's per-student activity times. Its timestamps are stored
at midnight and returned as a bare date. A named ticket keeps full detail.

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
# What an anonymous ticket keeps of them: where in the site, never the step, and nothing about the device.
ANONYMOUS_FACTS = ("path", "title", "section", "tab", "lesson", "assignment", "presentation")
_FACT_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
# A course link: /r/<token>, the slashes plain or percent-encoded. Tokens are secrets.token_urlsafe(24), 32 URL-safe
# characters; the frontend treats 16 or more as one (feedback-button.tsx STUDENT_PATH), and so does this.
_COURSE_LINK = re.compile(r"(/|%2[fF])r(/|%2[fF])[A-Za-z0-9_-]{16,}")


def scrub(text: str, secrets: tuple[str, ...] = ()) -> str:
    """`text` with every course link's token cut out, and each of `secrets` (a student's own token) too."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "…")
    return _COURSE_LINK.sub(lambda m: f"{m.group(1)}r{m.group(2)}…", text)


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


def _day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _without_step(path: str) -> str:
    """A page's address without the step: no #fragment (the lesson player keeps the step there) and no step= query."""
    path = path.split("#", 1)[0]
    if "?" not in path:
        return path
    base, query = path.split("?", 1)
    kept = [p for p in query.split("&") if p and not p.startswith("step=")]
    return base + ("?" + "&".join(kept) if kept else "")


def _anonymous(ticket: FeedbackTicket) -> bool:
    try:
        return bool(json.loads(ticket.metadata_json or "{}").get("anonymous"))
    except ValueError:
        return False


def _stamp(ticket: FeedbackTicket) -> datetime:
    """When a change to `ticket` is recorded: now, or the day alone on an anonymous ticket."""
    now = _now()
    return _day(now) if _anonymous(ticket) else now


def bounded_context(raw: Any, redact: tuple[str, ...] = ()) -> dict[str, str]:
    """The page's facts, bounded: named one-line strings only, each cut, the whole capped, scrubbed (`redact` too)."""
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
        text = scrub(" ".join(str(value).split()), redact)[:MAX_FACT_CHARS]
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
    redact = (enrollment.review_token,) if enrollment is not None and enrollment.review_token else ()
    # Scrubbed before it is measured or stored: pasting the page's address is the natural thing to type here.
    body = scrub((text or "").strip(), redact)
    if len(body) < MIN_TEXT:
        raise FeedbackError(422, "text_too_short", "Write a few words about what happened")
    if len(body) > MAX_TEXT:
        raise FeedbackError(422, "text_too_long", f"Keep it under {MAX_TEXT} characters")
    if course_id is not None and db.get(Course, course_id) is None:
        raise FeedbackError(404, "unknown_course", "Unknown course")

    if source == "student" and enrollment is None:
        raise FeedbackError(400, "no_enrollment", "A student's ticket needs their enrollment")
    coarse = source == "student" and bool(anonymous)
    facts = bounded_context(context, redact=redact)
    if coarse:
        facts = {k: v for k, v in facts.items() if k in ANONYMOUS_FACTS}
        if "path" in facts:
            facts["path"] = _without_step(facts["path"])
    refs: dict[str, Any] = {"category": category}
    meta: dict[str, Any] = {}
    for name, value in facts.items():
        (refs if name in REF_FACTS else meta)[name] = value
    if course_id is not None:
        refs["course_id"] = course_id

    reporter_ref: str | None
    if source == "student":
        meta["anonymous"] = coarse
        reporter_ref = None if coarse else f"enrollment:{enrollment.id}"
    else:
        reporter_ref = "instructor"

    now = _day(_now()) if coarse else _now()
    version = {"captured_at": now.date().isoformat()} if coarse else deployed_version()
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
        deployed_version_json=json.dumps(version),
        created_at=now,
        updated_at=now,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def ticket_row(ticket: FeedbackTicket) -> dict[str, Any]:
    """A ticket in tickets-core's words: what `org tickets --source api` reads from /api/admin/feedback. An anonymous
    ticket's timestamps are a bare date (YYYY-MM-DD), which org-core's parse_moment reads as that day."""
    when = (lambda dt: dt.date().isoformat()) if _anonymous(ticket) else _iso
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
        "created_at": when(ticket.created_at),
        "updated_at": when(ticket.updated_at),
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
    body = scrub((note or "").strip())
    if not author or len(author) > 128:
        raise FeedbackError(422, "invalid_author", "author is a role or a person's name, up to 128 characters")
    if not body or len(body) > MAX_NOTE:
        raise FeedbackError(422, "invalid_note", f"note is 1 to {MAX_NOTE} characters")
    row = FeedbackTicketNote(
        id=str(uuid.uuid4()),
        ticket_id=ticket.id,
        author=author,
        note=body,
        meta_json=json.dumps(meta if isinstance(meta, dict) else {}, ensure_ascii=False),
        created_at=_now(),  # when the role wrote it, which says nothing about the reporter
    )
    ticket.updated_at = _stamp(ticket)
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
    ticket.updated_at = _stamp(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket_row(ticket)
