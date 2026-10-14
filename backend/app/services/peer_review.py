"""Peer review domain logic: schedule, rubric versions, review windows,
eligibility, and review submission. API handlers stay thin and call in here.

Every rule a student could try to bypass (own team, window, deadline,
duplicates, scale) is enforced here, server-side.
"""

from __future__ import annotations

import json
import random
import re
import secrets
from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.entities import (
    ClassSession,
    Course,
    Enrollment,
    PeerReview,
    PeerRubricVersion,
    Presentation,
    PresentationMove,
    ReviewObligation,
    ReviewRound,
    ReviewRoundRoster,
    Team,
    TeamMembership,
)

ROUND_KINDS = ("progress", "final")
MAX_RESPONSE_CHARS = 4000


class PeerReviewError(Exception):
    """Domain error with a stable code the student UI translates."""

    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def utcnow() -> datetime:
    return datetime.utcnow()


# ---------------------------------------------------------------------------
# Default course structure
# ---------------------------------------------------------------------------

DEFAULT_SESSIONS: dict[int, str] = {
    1: "Orientation",
    2: "Progress round 1",
    3: "Progress round 1",
    4: "Progress round 2",
    5: "Progress round 2",
    6: "Progress round 3",
    7: "Progress round 3",
    8: "Progress round 4",
    9: "Progress round 4",
    10: "Build time (postponed presentations)",
    11: "Build time (postponed presentations)",
    12: "Final presentations",
    13: "Final presentations",
}

DEFAULT_ROUNDS: list[dict] = [
    {"number": 1, "kind": "progress", "title": "Progress review 1", "sessions": [2, 3]},
    {"number": 2, "kind": "progress", "title": "Progress review 2", "sessions": [4, 5]},
    {"number": 3, "kind": "progress", "title": "Progress review 3", "sessions": [6, 7]},
    {"number": 4, "kind": "progress", "title": "Progress review 4", "sessions": [8, 9]},
    {"number": 5, "kind": "final", "title": "Final presentations", "sessions": [12, 13]},
]
DEFAULT_SESSION_CAPACITY = 4

# Student-facing text is Hebrew, like the rest of the student-facing output.
# Only criteria with counts=True enter the grade (here: the final score); the
# others are optional remarks shown to the team as feedback.
_DEFAULT_CRITERIA = [
    {
        "key": "final_score",
        "label": "ציון סופי",
        "description": "הציון שלך להצגה. רק הציון הזה נספר; שאר השדות הם הערות לצוות.",
        "weight": 1.0,
        "counts": True,
    },
    {
        "key": "problem_clarity",
        "label": "בהירות הבעיה והמשתמש/ת המיועד/ת",
        "description": "עד כמה ברור איזו בעיה הפרויקט פותר ועבור מי.",
        "weight": 1.0,
        "counts": False,
    },
    {
        "key": "usefulness",
        "label": "תועלת עבור המשתמש/ת",
        "description": "עד כמה הפתרון שימושי בפועל עבור המשתמש/ת שהוגדר/ה.",
        "weight": 1.0,
        "counts": False,
    },
    {
        "key": "functionality",
        "label": "פונקציונליות שהודגמה בשלב הנוכחי",
        "description": "מה עובד בפועל בהדגמה, ביחס לשלב שבו הצוות נמצא.",
        "weight": 1.0,
        "counts": False,
    },
    {
        "key": "testing",
        "label": "עדות לבדיקה והערכה מושכלת",
        "description": "האם הצוות בדק את הפתרון (עם משתמשים, נתונים או מדדים) והסיק מסקנות.",
        "weight": 1.0,
        "counts": False,
    },
]
_DEFAULT_SCALE = [
    {"value": 1, "label": "חלש"},
    {"value": 2, "label": "מתחת לציפיות"},
    {"value": 3, "label": "סביר"},
    {"value": 4, "label": "טוב"},
    {"value": 5, "label": "מצוין"},
]
_DEFAULT_PROMPTS = [
    {"key": "worked_well", "label": "מה עבד טוב?", "required": False},
    {"key": "improvement", "label": "הצעה אחת קונקרטית לשיפור", "required": False},
]
DEFAULT_INSTRUCTIONS = {
    "progress": (
        "זהו סבב התקדמות: העריכו את השלב שהצוות הציג והדגים היום – לא מוצר גמור. "
        "התייחסו למה שעובד בפועל, לכיוון ולהתקדמות."
    ),
    "final": "זוהי הצגת הסיום: העריכו את המוצר כפי שהוצג והודגם.",
}


def round_sessions(rnd: ReviewRound) -> list[dict]:
    try:
        data = json.loads(rnd.sessions_json or "[]")
    except (TypeError, ValueError):
        return []
    out = []
    for item in data:
        try:
            out.append({"number": int(item["number"]), "capacity": max(0, int(item.get("capacity", 0)))})
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(out, key=lambda s: s["number"])


def setup_default_schedule(db: Session, course: Course) -> None:
    """Create the 13 sessions and 5 rounds if missing. Idempotent."""
    existing_sessions = {s.number for s in db.scalars(select(ClassSession).where(ClassSession.course_id == course.id))}
    for number, title in DEFAULT_SESSIONS.items():
        if number not in existing_sessions:
            db.add(ClassSession(course_id=course.id, number=number, title=title))

    existing_rounds = {r.number for r in db.scalars(select(ReviewRound).where(ReviewRound.course_id == course.id))}
    for spec in DEFAULT_ROUNDS:
        if spec["number"] in existing_rounds:
            continue
        db.add(
            ReviewRound(
                course_id=course.id,
                number=spec["number"],
                kind=spec["kind"],
                title=spec["title"],
                sessions_json=json.dumps(
                    [{"number": n, "capacity": DEFAULT_SESSION_CAPACITY} for n in spec["sessions"]]
                ),
            )
        )
    for kind in ROUND_KINDS:
        latest_rubric(db, course.id, kind, create=True)
    db.flush()
    for rnd in db.scalars(select(ReviewRound).where(ReviewRound.course_id == course.id)):
        sync_round_presentations(db, rnd)
    db.commit()


def sync_round_presentations(db: Session, rnd: ReviewRound) -> int:
    """Give every team of the course a presentation in the round."""
    have = {p.team_id for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id))}
    created = 0
    for team in db.scalars(select(Team).where(Team.course_id == rnd.course_id)):
        if team.id not in have:
            db.add(Presentation(round_id=rnd.id, team_id=team.id))
            created += 1
    db.flush()
    return created


# ---------------------------------------------------------------------------
# Rubrics
# ---------------------------------------------------------------------------


def latest_rubric(db: Session, course_id: int, kind: str, create: bool = False) -> PeerRubricVersion | None:
    rubric = db.scalar(
        select(PeerRubricVersion)
        .where(PeerRubricVersion.course_id == course_id, PeerRubricVersion.kind == kind)
        .order_by(PeerRubricVersion.version.desc())
        .limit(1)
    )
    if rubric is None and create:
        rubric = PeerRubricVersion(
            course_id=course_id,
            kind=kind,
            version=1,
            criteria_json=json.dumps(_DEFAULT_CRITERIA, ensure_ascii=False),
            scale_json=json.dumps(_DEFAULT_SCALE, ensure_ascii=False),
            prompts_json=json.dumps(_DEFAULT_PROMPTS, ensure_ascii=False),
            instructions=DEFAULT_INSTRUCTIONS[kind],
        )
        db.add(rubric)
        db.flush()
    return rubric


def rubric_payload(rubric: PeerRubricVersion) -> dict:
    return {
        "id": rubric.id,
        "kind": rubric.kind,
        "version": rubric.version,
        "criteria": json.loads(rubric.criteria_json),
        "scale": json.loads(rubric.scale_json),
        "prompts": json.loads(rubric.prompts_json),
        "instructions": rubric.instructions,
        "frozen": rubric.frozen_at is not None,
    }


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9_]+", "_", value.strip().lower()).strip("_")
    return slug or fallback


def validate_rubric(criteria: list[dict], scale: list[dict], prompts: list[dict]) -> tuple[list, list, list]:
    if not criteria:
        raise PeerReviewError("invalid_rubric", "A rubric needs at least one criterion")
    clean_criteria = []
    seen: set[str] = set()
    for i, c in enumerate(criteria):
        label = str(c.get("label", "")).strip()
        if not label:
            raise PeerReviewError("invalid_rubric", f"Criterion {i + 1} needs a label")
        key = _slug(str(c.get("key") or ""), f"criterion_{i + 1}")
        if key in seen:
            raise PeerReviewError("invalid_rubric", f"Duplicate criterion key '{key}'")
        seen.add(key)
        try:
            weight = float(c.get("weight", 1.0))
        except (TypeError, ValueError):
            raise PeerReviewError("invalid_rubric", f"Criterion '{label}' has an invalid weight")
        if weight <= 0:
            raise PeerReviewError("invalid_rubric", f"Criterion '{label}' needs a positive weight")
        clean_criteria.append(
            {
                "key": key,
                "label": label,
                "description": str(c.get("description", "")).strip(),
                "weight": weight,
                "counts": bool(c.get("counts", True)),
            }
        )
    if not any(c["counts"] for c in clean_criteria):
        raise PeerReviewError("invalid_rubric", "At least one criterion must count toward the score")

    clean_scale = []
    for s in scale:
        try:
            value = int(s["value"])
        except (KeyError, TypeError, ValueError):
            raise PeerReviewError("invalid_rubric", "Scale points need integer values")
        clean_scale.append({"value": value, "label": str(s.get("label", "")).strip()})
    clean_scale.sort(key=lambda s: s["value"])
    values = [s["value"] for s in clean_scale]
    if len(values) < 2 or len(set(values)) != len(values) or values[0] < 1:
        raise PeerReviewError("invalid_rubric", "The scale needs at least two distinct positive values")

    clean_prompts = []
    seen_prompts: set[str] = set()
    for i, p in enumerate(prompts):
        label = str(p.get("label", "")).strip()
        if not label:
            raise PeerReviewError("invalid_rubric", f"Text prompt {i + 1} needs a label")
        key = _slug(str(p.get("key") or ""), f"prompt_{i + 1}")
        if key in seen_prompts:
            raise PeerReviewError("invalid_rubric", f"Duplicate prompt key '{key}'")
        seen_prompts.add(key)
        clean_prompts.append({"key": key, "label": label, "required": bool(p.get("required", False))})
    return clean_criteria, clean_scale, clean_prompts


def save_rubric(
    db: Session,
    course_id: int,
    kind: str,
    criteria: list[dict],
    scale: list[dict],
    prompts: list[dict],
    instructions: str,
) -> PeerRubricVersion:
    """Edit the draft rubric of a kind. A frozen version is never touched:
    editing it creates the next version, used by rounds opened later."""
    if kind not in ROUND_KINDS:
        raise PeerReviewError("invalid_rubric", f"Unknown rubric kind '{kind}'")
    criteria, scale, prompts = validate_rubric(criteria, scale, prompts)
    current = latest_rubric(db, course_id, kind, create=True)
    assert current is not None
    if current.frozen_at is not None:
        current = PeerRubricVersion(course_id=course_id, kind=kind, version=current.version + 1)
        db.add(current)
    current.criteria_json = json.dumps(criteria, ensure_ascii=False)
    current.scale_json = json.dumps(scale, ensure_ascii=False)
    current.prompts_json = json.dumps(prompts, ensure_ascii=False)
    current.instructions = instructions.strip()
    db.commit()
    db.refresh(current)
    return current


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


def active_membership(db: Session, course_id: int, student_id: int) -> TeamMembership | None:
    return db.scalar(
        select(TeamMembership).where(
            TeamMembership.course_id == course_id,
            TeamMembership.student_id == student_id,
            TeamMembership.end_at.is_(None),
        )
    )


def active_team_id(db: Session, course_id: int, student_id: int) -> int | None:
    m = active_membership(db, course_id, student_id)
    return m.team_id if m else None


def set_student_team(db: Session, course_id: int, student_id: int, team_id: int | None) -> None:
    """Move a student. The previous membership is ended, never rewritten."""
    current = active_membership(db, course_id, student_id)
    if current and current.team_id == team_id:
        return
    if current:
        current.end_at = utcnow()
        db.flush()
    if team_id is not None:
        team = db.get(Team, team_id)
        if team is None or team.course_id != course_id:
            raise PeerReviewError("not_found", "Team not found", 404)
        db.add(TeamMembership(course_id=course_id, team_id=team_id, student_id=student_id))
    db.commit()
    refresh_practice_rounds(db, course_id)


def active_members(db: Session, team_id: int) -> list[int]:
    return list(
        db.scalars(
            select(TeamMembership.student_id).where(
                TeamMembership.team_id == team_id, TeamMembership.end_at.is_(None)
            )
        )
    )


# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------


def session_load(db: Session, rnd: ReviewRound) -> Counter:
    return Counter(
        p.session_number
        for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id))
        if p.session_number is not None
    )


def _record_move(
    db: Session, presentation: Presentation, to_session: int | None, kind: str, actor: str, reason: str
) -> None:
    from_session = presentation.session_number
    if from_session == to_session:
        return
    if from_session is not None and presentation.original_session_number is None:
        presentation.original_session_number = from_session
    presentation.session_number = to_session
    db.add(
        PresentationMove(
            presentation_id=presentation.id,
            from_session=from_session,
            to_session=to_session,
            kind=kind,
            actor=actor,
            reason=reason,
        )
    )


def volunteer_for_session(db: Session, student_id: int, presentation: Presentation, session_number: int) -> None:
    rnd = presentation.round
    if rnd.status != "scheduling":
        raise PeerReviewError("selection_closed", "Session selection is not open for this round", 409)
    if rnd.selection_deadline and utcnow() >= rnd.selection_deadline:
        raise PeerReviewError("selection_closed", "The selection deadline has passed", 409)
    if active_team_id(db, rnd.course_id, student_id) != presentation.team_id:
        raise PeerReviewError("not_your_team", "You can only choose a date for your own team", 403)
    if presentation.assignment_source == "instructor":
        raise PeerReviewError("locked", "The instructor has fixed this presentation's date", 409)
    capacities = {s["number"]: s["capacity"] for s in round_sessions(rnd)}
    if session_number not in capacities:
        raise PeerReviewError("invalid_session", "That session is not part of this round")
    load = session_load(db, rnd)
    if presentation.session_number != session_number and load[session_number] >= capacities[session_number]:
        raise PeerReviewError("capacity_full", "That session is full", 409)
    _record_move(db, presentation, session_number, "volunteer", "student", "")
    presentation.assignment_source = "volunteer"
    db.commit()


def random_assign(db: Session, rnd: ReviewRound, rng: random.Random | None = None) -> tuple[int, int]:
    """Place unassigned presentations into sessions with free capacity,
    filling the emptiest session first. Returns (assigned, left_over)."""
    rng = rng or random.SystemRandom()
    sessions = round_sessions(rnd)
    load = session_load(db, rnd)
    unassigned = [
        p
        for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id).order_by(Presentation.id))
        if p.session_number is None
    ]
    rng.shuffle(unassigned)
    assigned = 0
    for p in unassigned:
        free = {s["number"]: s["capacity"] - load[s["number"]] for s in sessions}
        free = {n: f for n, f in free.items() if f > 0}
        if not free:
            break
        best = max(free.values())
        target = rng.choice(sorted(n for n, f in free.items() if f == best))
        _record_move(db, p, target, "random", "instructor", "Random assignment of unassigned teams")
        p.assignment_source = "random"
        load[target] += 1
        assigned += 1
    db.commit()
    return assigned, len(unassigned) - assigned


def move_presentation(
    db: Session, presentation: Presentation, to_session: int | None, reason: str, postpone: bool = False
) -> None:
    """Instructor override or postponement. Only the session changes; the
    presentation keeps its round, reviews, and obligations."""
    if to_session is not None and not 1 <= to_session <= 99:
        raise PeerReviewError("invalid_session", "Invalid session number")
    moved = presentation.session_number != to_session
    _record_move(db, presentation, to_session, "postpone" if postpone else "override", "instructor", reason)
    presentation.assignment_source = "instructor"
    if postpone:
        presentation.status = "postponed"
    if moved:
        # Reviews reopen when the team actually presents in the new session.
        presentation.review_open = False
    db.commit()


def swap_presentations(db: Session, a: Presentation, b: Presentation, reason: str) -> None:
    if a.round_id != b.round_id:
        raise PeerReviewError("invalid_swap", "Only presentations in the same round can be swapped")
    if a.id == b.id:
        raise PeerReviewError("invalid_swap", "Pick two different presentations")
    a_session, b_session = a.session_number, b.session_number
    for p, target in ((a, b_session), (b, a_session)):
        if p.session_number != target:
            p.review_open = False
        _record_move(db, p, target, "swap", "instructor", reason)
        p.assignment_source = "instructor"
    db.commit()


# ---------------------------------------------------------------------------
# Review windows
# ---------------------------------------------------------------------------


def open_selection(db: Session, rnd: ReviewRound) -> None:
    if rnd.status != "draft":
        raise PeerReviewError("invalid_state", "Selection can only be opened from draft", 409)
    sync_round_presentations(db, rnd)
    rnd.status = "scheduling"
    db.commit()


def freeze_rubric(db: Session, rnd: ReviewRound) -> PeerRubricVersion:
    if rnd.rubric_version_id is not None and rnd.rubric_version is not None:
        return rnd.rubric_version
    rubric = latest_rubric(db, rnd.course_id, rnd.kind, create=True)
    assert rubric is not None
    if rubric.frozen_at is None:
        rubric.frozen_at = utcnow()
    rnd.rubric_version_id = rubric.id
    db.flush()
    db.refresh(rnd)
    return rubric


def snapshot_round(db: Session, rnd: ReviewRound) -> dict:
    """Snapshot each enrolled student's team and create their review
    obligations (every presentation in the round except their own team's).
    Idempotent: a student's snapshotted team never changes once set, and
    existing obligations are kept. A student who had no team when the round
    opened gets the team they have now (and stops owing a review of it)."""
    sync_round_presentations(db, rnd)
    roster = {r.student_id: r for r in db.scalars(select(ReviewRoundRoster).where(ReviewRoundRoster.round_id == rnd.id))}
    for row in roster.values():
        if row.team_id is None:
            row.team_id = active_team_id(db, rnd.course_id, row.student_id)
            if row.team_id is not None:
                own = select(Presentation.id).where(Presentation.round_id == rnd.id, Presentation.team_id == row.team_id)
                reviewed = select(PeerReview.presentation_id).where(PeerReview.reviewer_student_id == row.student_id)
                for ob in db.scalars(
                    select(ReviewObligation).where(
                        ReviewObligation.round_id == rnd.id,
                        ReviewObligation.student_id == row.student_id,
                        ReviewObligation.presentation_id.in_(own),
                        ReviewObligation.presentation_id.not_in(reviewed),
                    )
                ):
                    db.delete(ob)
    added_students = 0
    for enrollment in db.scalars(select(Enrollment).where(Enrollment.course_id == rnd.course_id)):
        if enrollment.student_id in roster:
            continue
        row = ReviewRoundRoster(
            round_id=rnd.id,
            student_id=enrollment.student_id,
            team_id=active_team_id(db, rnd.course_id, enrollment.student_id),
        )
        db.add(row)
        roster[enrollment.student_id] = row
        added_students += 1
    db.flush()

    existing = {
        (o.student_id, o.presentation_id)
        for o in db.scalars(select(ReviewObligation).where(ReviewObligation.round_id == rnd.id))
    }
    added_obligations = 0
    presentations = list(db.scalars(select(Presentation).where(Presentation.round_id == rnd.id)))
    for student_id, row in roster.items():
        for p in presentations:
            if p.team_id == row.team_id or (student_id, p.id) in existing:
                continue
            db.add(ReviewObligation(round_id=rnd.id, presentation_id=p.id, student_id=student_id))
            added_obligations += 1
    db.commit()
    return {"students_added": added_students, "obligations_added": added_obligations}


def open_reviewing(db: Session, rnd: ReviewRound) -> None:
    if rnd.status not in ("draft", "scheduling"):
        raise PeerReviewError("invalid_state", f"Cannot open reviewing from '{rnd.status}'", 409)
    freeze_rubric(db, rnd)
    rnd.status = "reviewing"
    db.commit()
    snapshot_round(db, rnd)


def set_session_review_open(db: Session, rnd: ReviewRound, session_number: int, is_open: bool) -> int:
    if is_open and rnd.status != "reviewing":
        raise PeerReviewError("invalid_state", "Open reviewing for the round first", 409)
    changed = 0
    for p in db.scalars(
        select(Presentation).where(Presentation.round_id == rnd.id, Presentation.session_number == session_number)
    ):
        p.review_open = is_open
        changed += 1
    db.commit()
    return changed


def close_round(db: Session, rnd: ReviewRound) -> None:
    if rnd.status != "reviewing":
        raise PeerReviewError("invalid_state", "Only a round that is reviewing can be closed", 409)
    rnd.status = "closed"
    db.commit()


def reopen_round(db: Session, rnd: ReviewRound) -> None:
    if rnd.status != "closed" or rnd.released_at is not None:
        raise PeerReviewError("invalid_state", "Only a closed, unreleased round can be reopened", 409)
    rnd.status = "reviewing"
    db.commit()


def release_round(db: Session, rnd: ReviewRound) -> None:
    # Same policy for both sessions of the round: results go out together,
    # after reviewing for the whole round is closed.
    if rnd.status != "closed":
        raise PeerReviewError("invalid_state", "Close the round (both sessions) before releasing results", 409)
    rnd.released_at = utcnow()
    db.commit()


def unrelease_round(db: Session, rnd: ReviewRound) -> None:
    rnd.released_at = None
    db.commit()


def presentation_open(rnd: ReviewRound, presentation: Presentation) -> bool:
    """Practice rounds open every presentation while reviewing."""
    return rnd.status == "reviewing" and (presentation.review_open or not rnd.counts_toward_grade)


def reviews_accepted(rnd: ReviewRound, presentation: Presentation) -> bool:
    if not presentation_open(rnd, presentation):
        return False
    return rnd.review_deadline is None or utcnow() < rnd.review_deadline


# ---------------------------------------------------------------------------
# Student reviews
# ---------------------------------------------------------------------------


def validate_review(rubric: PeerRubricVersion, scores: dict, responses: dict) -> tuple[dict, dict]:
    criteria = json.loads(rubric.criteria_json)
    allowed = {s["value"] for s in json.loads(rubric.scale_json)}
    prompts = json.loads(rubric.prompts_json)

    keys = {c["key"] for c in criteria}
    unknown = set(scores) - keys
    if unknown:
        raise PeerReviewError("invalid_score", f"Unknown criteria: {sorted(unknown)}", 422)
    clean_scores: dict[str, int] = {}
    for c in criteria:
        value = scores.get(c["key"])
        if value is None and not c.get("counts", True):
            continue  # optional remark
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            raise PeerReviewError("missing_score", f"Score required for '{c['label']}'", 422)
        if int(value) not in allowed:
            raise PeerReviewError("invalid_score", f"Score for '{c['label']}' is outside the scale", 422)
        clean_scores[c["key"]] = int(value)

    clean_responses: dict[str, str] = {}
    for p in prompts:
        value = responses.get(p["key"], "")
        text = value.strip() if isinstance(value, str) else ""
        if len(text) > MAX_RESPONSE_CHARS:
            raise PeerReviewError("response_too_long", f"'{p['label']}' is too long", 422)
        if p.get("required") and not text:
            raise PeerReviewError("missing_response", f"'{p['label']}' is required", 422)
        clean_responses[p["key"]] = text
    return clean_scores, clean_responses


def submit_student_review(
    db: Session, student_id: int, presentation: Presentation, scores: dict, responses: dict
) -> PeerReview:
    """Create or edit the student's one review of a presentation."""
    rnd = presentation.round
    if not presentation_open(rnd, presentation):
        raise PeerReviewError("window_closed", "Reviewing is not open for this presentation", 409)
    if rnd.review_deadline is not None and utcnow() >= rnd.review_deadline:
        raise PeerReviewError("deadline_passed", "The review deadline has passed", 409)

    roster = db.scalar(
        select(ReviewRoundRoster).where(ReviewRoundRoster.round_id == rnd.id, ReviewRoundRoster.student_id == student_id)
    )
    if roster is None:
        raise PeerReviewError("not_eligible", "You are not on this round's roster", 403)
    if roster.team_id == presentation.team_id or active_team_id(db, rnd.course_id, student_id) == presentation.team_id:
        raise PeerReviewError("own_team", "You cannot review your own team", 403)
    obligation = db.scalar(
        select(ReviewObligation).where(
            ReviewObligation.presentation_id == presentation.id, ReviewObligation.student_id == student_id
        )
    )
    if obligation is None:
        raise PeerReviewError("not_eligible", "You are not assigned to review this presentation", 403)

    assert rnd.rubric_version is not None
    clean_scores, clean_responses = validate_review(rnd.rubric_version, scores, responses)

    def _apply(review: PeerReview) -> None:
        review.scores_json = json.dumps(clean_scores)
        review.responses_json = json.dumps(clean_responses, ensure_ascii=False)
        review.updated_at = utcnow()

    review = db.scalar(
        select(PeerReview).where(
            PeerReview.presentation_id == presentation.id, PeerReview.reviewer_student_id == student_id
        )
    )
    if review is None:
        review = PeerReview(
            round_id=rnd.id,
            presentation_id=presentation.id,
            rubric_version_id=rnd.rubric_version.id,
            reviewer_kind="student",
            reviewer_student_id=student_id,
            reviewer_team_id=roster.team_id,
        )
        _apply(review)
        db.add(review)
        try:
            db.commit()
        except IntegrityError:
            # A concurrent submit won the insert; fold this one in as an edit.
            db.rollback()
            review = db.scalar(
                select(PeerReview).where(
                    PeerReview.presentation_id == presentation.id, PeerReview.reviewer_student_id == student_id
                )
            )
            if review is None:
                raise
            _apply(review)
            db.commit()
    else:
        _apply(review)
        db.commit()
    db.refresh(review)
    return review


def set_exemptions(
    db: Session, rnd: ReviewRound, student_id: int, presentation_ids: list[int], exempt: bool, reason: str
) -> int:
    if exempt and not reason.strip():
        raise PeerReviewError("reason_required", "An exemption needs a reason")
    changed = 0
    for ob in db.scalars(
        select(ReviewObligation).where(
            ReviewObligation.round_id == rnd.id,
            ReviewObligation.student_id == student_id,
            ReviewObligation.presentation_id.in_(presentation_ids),
        )
    ):
        ob.exempt = exempt
        ob.exempt_reason = reason.strip() if exempt else ""
        changed += 1
    db.commit()
    return changed


def set_review_exclusion(db: Session, review: PeerReview, excluded: bool, reason: str) -> None:
    if excluded and not reason.strip():
        raise PeerReviewError("reason_required", "Excluding a review needs a reason")
    review.excluded = excluded
    review.exclusion_reason = reason.strip() if excluded else review.exclusion_reason
    review.excluded_at = utcnow() if excluded else None
    db.commit()


# ---------------------------------------------------------------------------
# Student links
# ---------------------------------------------------------------------------


def new_review_token() -> str:
    return secrets.token_urlsafe(24)


def ensure_review_tokens(db: Session, course_id: int) -> int:
    created = 0
    for enrollment in db.scalars(select(Enrollment).where(Enrollment.course_id == course_id)):
        if not enrollment.review_token:
            enrollment.review_token = new_review_token()
            created += 1
    db.commit()
    return created


# ---------------------------------------------------------------------------
# Practice rounds
# ---------------------------------------------------------------------------


def create_practice_round(db: Session, course: Course, title: str, open_now: bool) -> ReviewRound:
    """A round that never counts toward a grade, numbered 0, -1, … so it sorts
    before the graded rounds. With open_now, students can review right away;
    teams created later join it automatically."""
    numbers = set(db.scalars(select(ReviewRound.number).where(ReviewRound.course_id == course.id)))
    number = 0
    while number in numbers:
        number -= 1
    rnd = ReviewRound(
        course_id=course.id,
        number=number,
        kind="progress",
        title=title.strip() or "Practice round",
        sessions_json="[]",
        counts_toward_grade=False,
        llm_enabled=False,
    )
    db.add(rnd)
    db.commit()
    db.refresh(rnd)
    if open_now:
        open_reviewing(db, rnd)
    return rnd


def refresh_practice_rounds(db: Session, course_id: int) -> None:
    """Keep open practice rounds in step with team changes."""
    for rnd in db.scalars(
        select(ReviewRound).where(
            ReviewRound.course_id == course_id,
            ReviewRound.counts_toward_grade.is_(False),
            ReviewRound.status == "reviewing",
        )
    ):
        snapshot_round(db, rnd)
