"""Peer review domain logic: schedule, rubric versions, review windows,
eligibility, and review submission. API handlers stay thin and call in here.

Every rule a student could try to bypass (own team, window, deadline,
duplicates, scale) is enforced here, server-side.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
import secrets
from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.services import link_check
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
# others are optional remarks shown to the team as feedback. A criterion with
# "max" takes any number from 0 to max instead of a point on the scale (scores
# are normalised per reviewer, so only their ratios matter).
_DEFAULT_CRITERIA = [
    {
        "key": "final_score",
        "label": "ציון סופי",
        "description": "הציון שלך להצגה, מ-0 עד 100. רק הציון הזה נספר; שאר השדות הם הערות לצוות.",
        "weight": 1.0,
        "counts": True,
        "max": 100,
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
        clean = {
            "key": key,
            "label": label,
            "description": str(c.get("description", "")).strip(),
            "weight": weight,
            "counts": bool(c.get("counts", True)),
        }
        if c.get("max") is not None:
            try:
                top = float(c["max"])
            except (TypeError, ValueError):
                raise PeerReviewError("invalid_rubric", f"Criterion '{label}' has an invalid maximum")
            if top <= 0:
                raise PeerReviewError("invalid_rubric", f"Criterion '{label}' needs a positive maximum")
            clean["max"] = int(top) if top == int(top) else top
        clean_criteria.append(clean)
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
        # Only the counted score is ever required; text answers are always optional.
        clean_prompts.append({"key": key, "label": label, "required": False})
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


def set_student_team(
    db: Session, course_id: int, student_id: int, team_id: int | None, commit: bool = True
) -> None:
    """Move a student. The previous membership is ended, never rewritten.

    With commit=False the change is only flushed, so a caller can group
    several moves into one transaction (and refresh practice rounds itself).
    """
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
    if not commit:
        db.flush()
        return
    db.commit()
    refresh_practice_rounds(db, course_id)


# ---------------------------------------------------------------------------
# Teams: created by the instructor or by students (join code)
# ---------------------------------------------------------------------------

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I


def new_join_code(db: Session) -> str:
    while True:
        code = "".join(secrets.choice(JOIN_CODE_ALPHABET) for _ in range(6))
        if db.scalar(select(Team.id).where(Team.join_code == code)) is None:
            return code


def create_team(db: Session, course_id: int, name: str, project_title: str = "", commit: bool = True) -> Team:
    name = name.strip()
    if not name:
        raise PeerReviewError("invalid_team", "The team needs a name", 422)
    if db.scalar(select(Team).where(Team.course_id == course_id, Team.name == name)):
        raise PeerReviewError("team_name_taken", "A team with this name already exists", 409)
    team = Team(course_id=course_id, name=name, project_title=project_title.strip(), join_code=new_join_code(db))
    db.add(team)
    db.flush()
    # Rounds not yet open for reviewing get a presentation slot for the team.
    for rnd in db.scalars(select(ReviewRound).where(ReviewRound.course_id == course_id)):
        if rnd.status in ("draft", "scheduling"):
            sync_round_presentations(db, rnd)
    if not commit:
        return team
    db.commit()
    refresh_practice_rounds(db, course_id)
    return team


def team_has_history(db: Session, team: Team) -> bool:
    pres_ids = list(db.scalars(select(Presentation.id).where(Presentation.team_id == team.id)))
    if pres_ids and (
        db.scalar(select(PeerReview.id).where(PeerReview.presentation_id.in_(pres_ids)).limit(1))
        or db.scalar(select(ReviewObligation.id).where(ReviewObligation.presentation_id.in_(pres_ids)).limit(1))
    ):
        return True
    return db.scalar(select(ReviewRoundRoster.id).where(ReviewRoundRoster.team_id == team.id).limit(1)) is not None


def teams_locked(course: Course) -> bool:
    """Students can't change teams: switched off, or the deadline has passed (server clock)."""
    return not course.teams_open or (course.teams_deadline is not None and utcnow() >= course.teams_deadline)


def _require_teams_open(course: Course) -> None:
    if teams_locked(course):
        raise PeerReviewError("teams_locked", "Teams are locked; ask the instructor to change your team", 409)


def student_create_team(db: Session, course: Course, student_id: int, name: str, project_title: str) -> Team:
    _require_teams_open(course)
    if active_team_id(db, course.id, student_id) is not None:
        raise PeerReviewError("already_in_team", "Leave your current team first", 409)
    team = create_team(db, course.id, name, project_title)
    set_student_team(db, course.id, student_id, team.id)
    return team


def student_join_team(db: Session, course: Course, student_id: int, code: str) -> Team:
    _require_teams_open(course)
    if active_team_id(db, course.id, student_id) is not None:
        raise PeerReviewError("already_in_team", "Leave your current team first", 409)
    team = db.scalar(select(Team).where(Team.course_id == course.id, Team.join_code == code.strip().upper()))
    if team is None:
        raise PeerReviewError("bad_code", "No team with this code in your course", 404)
    if len(active_members(db, team.id)) >= course.max_team_size:
        raise PeerReviewError("team_full", f"This team already has {course.max_team_size} members", 409)
    set_student_team(db, course.id, student_id, team.id)
    return team


def student_leave_team(db: Session, course: Course, student_id: int) -> None:
    """Leave the team; a team left empty with no review history is removed."""
    _require_teams_open(course)
    remove_student_from_team(db, course.id, student_id)


def remove_student_from_team(db: Session, course_id: int, student_id: int) -> None:
    """Take a student off their team, ignoring the lock (instructor action).

    A team left empty with no review history is removed.
    """
    team_id = active_team_id(db, course_id, student_id)
    if team_id is None:
        return
    set_student_team(db, course_id, student_id, None)
    team = db.get(Team, team_id)
    if team is not None and not active_members(db, team_id) and not team_has_history(db, team):
        db.delete(team)
        db.commit()


def unassigned_students(db: Session, course_id: int) -> list[int]:
    """Enrolled (non-test, not withdrawn) students with no active team."""
    assigned = select(TeamMembership.student_id).where(
        TeamMembership.course_id == course_id, TeamMembership.end_at.is_(None)
    )
    return list(
        db.scalars(
            select(Enrollment.student_id).where(
                Enrollment.course_id == course_id,
                Enrollment.is_test.is_(False),
                Enrollment.withdrawn_at.is_(None),
                Enrollment.student_id.not_in(assigned),
            )
        )
    )


def active_members(db: Session, team_id: int) -> list[int]:
    return list(
        db.scalars(
            select(TeamMembership.student_id).where(
                TeamMembership.team_id == team_id, TeamMembership.end_at.is_(None)
            )
        )
    )


# ---------------------------------------------------------------------------
# Auto-assigning unteamed students (instructor proposes, reviews, approves)
# ---------------------------------------------------------------------------
#
# Stateless: propose_assignment writes nothing and returns the proposal with a
# fingerprint of the team state it was built from. approve_assignment re-checks
# the fingerprint, re-validates every placement and writes the (possibly
# edited) proposal in one transaction. Once applied, memberships change, so the
# fingerprint changes and approving the same proposal again is refused as stale.
#
# Assignment rule (deterministic for a given seed and state):
#   1. The eligible students (enrolled, not test, not withdrawn, no active team)
#      are sorted by id, then shuffled with random.Random(seed).
#   2. Fill: each student in turn joins the existing team with the fewest
#      active members that is still below max_team_size (ties: lowest team id).
#   3. New teams: the k = ceil(n / max_team_size) fewest teams that fit the n
#      students left, with sizes as equal as possible (they differ by at most 1).
#   4. No lone student: if exactly one student is left for a new team and the
#      fill step placed someone, the last student it placed moves into the new
#      team instead, making it a pair (only when max_team_size >= 2).


def team_state_fingerprint(db: Session, course: Course) -> str:
    """Hash of everything a proposal depends on: team size limit, the course's
    teams, active memberships and each enrollment's test/withdrawn state."""
    teams = sorted(db.scalars(select(Team.id).where(Team.course_id == course.id)))
    members = sorted(
        (m.student_id, m.team_id)
        for m in db.scalars(
            select(TeamMembership).where(TeamMembership.course_id == course.id, TeamMembership.end_at.is_(None))
        )
    )
    enrollments = sorted(
        (e.student_id, bool(e.is_test), e.withdrawn_at is not None)
        for e in db.scalars(select(Enrollment).where(Enrollment.course_id == course.id))
    )
    state = {
        "course": course.id,
        "max_team_size": course.max_team_size,
        "teams": teams,
        "members": members,
        "enrollments": enrollments,
    }
    return hashlib.sha256(json.dumps(state, separators=(",", ":")).encode()).hexdigest()


def _require_teams_locked(course: Course) -> None:
    # Students must not be changing teams while the instructor assigns them.
    if not teams_locked(course):
        raise PeerReviewError("teams_open", "Close team formation (or wait for the deadline) first", 409)


def _new_team_names(db: Session, course_id: int, count: int) -> list[str]:
    taken = set(db.scalars(select(Team.name).where(Team.course_id == course_id)))
    names, n = [], 1
    while len(names) < count:
        name = f"צוות {n}"
        if name not in taken:
            names.append(name)
        n += 1
    return names


def propose_assignment(db: Session, course: Course, seed: int | None = None) -> dict:
    """Build a proposal for placing every unteamed student. Writes nothing."""
    _require_teams_locked(course)
    if seed is None:
        seed = secrets.randbelow(2**31)
    max_size = course.max_team_size
    pool = sorted(unassigned_students(db, course.id))
    random.Random(seed).shuffle(pool)

    teams = list(db.scalars(select(Team).where(Team.course_id == course.id).order_by(Team.id)))
    size = {t.id: len(active_members(db, t.id)) for t in teams}
    added: dict[int, list[int]] = {t.id: [] for t in teams}
    placed: list[tuple[int, int]] = []  # (team_id, student_id) in fill order
    while pool:
        open_teams = [t.id for t in teams if size[t.id] < max_size]
        if not open_teams:
            break
        team_id = min(open_teams, key=lambda tid: (size[tid], tid))
        student_id = pool.pop(0)
        added[team_id].append(student_id)
        size[team_id] += 1
        placed.append((team_id, student_id))

    if len(pool) == 1 and placed and max_size >= 2:
        team_id, student_id = placed.pop()
        added[team_id].remove(student_id)
        pool.insert(0, student_id)

    groups: list[list[int]] = []
    if pool:
        k = math.ceil(len(pool) / max_size)
        base, extra = divmod(len(pool), k)
        start = 0
        for i in range(k):
            end = start + base + (1 if i < extra else 0)
            groups.append(pool[start:end])
            start = end
    names = _new_team_names(db, course.id, len(groups))
    return {
        "seed": seed,
        "fingerprint": team_state_fingerprint(db, course),
        "max_team_size": max_size,
        "existing": [{"team_id": tid, "student_ids": ids} for tid, ids in added.items() if ids],
        "new_teams": [{"name": name, "student_ids": ids} for name, ids in zip(names, groups)],
    }


def approve_assignment(
    db: Session, course_id: int, fingerprint: str, existing: list[dict], new_teams: list[dict]
) -> dict:
    """Apply a (possibly edited) proposal in one transaction, or refuse.

    Refused with stale_proposal (409) when the team state changed since the
    proposal was built, including after this same proposal was applied.
    Bypasses the student-facing lock on purpose: it is an instructor action
    and only runs once teams are locked. Every student must still be an
    eligible unteamed student of this course, and no team may end up above
    max_team_size.
    """
    # Serialises concurrent approvals on Postgres (SQLite locks on write anyway).
    course = db.get(Course, course_id, with_for_update=True)
    if course is None:
        raise PeerReviewError("not_found", "Course not found", 404)
    _require_teams_locked(course)
    if fingerprint != team_state_fingerprint(db, course):
        raise PeerReviewError(
            "stale_proposal", "Teams or the roster changed since this proposal was made; propose again", 409
        )

    eligible = set(unassigned_students(db, course.id))
    seen: set[int] = set()

    def check_students(ids: list[int]) -> None:
        for sid in ids:
            if sid in seen:
                raise PeerReviewError("invalid_proposal", "A student appears twice in the proposal", 422)
            if sid not in eligible:
                raise PeerReviewError(
                    "invalid_proposal", "The proposal includes a student who can't be assigned", 422
                )
            seen.add(sid)

    team_ids = set(db.scalars(select(Team.id).where(Team.course_id == course.id)))
    adding: Counter = Counter()
    for item in existing:
        tid, ids = item["team_id"], item["student_ids"]
        if tid not in team_ids:
            raise PeerReviewError("not_found", "Team not found", 404)
        check_students(ids)
        adding[tid] += len(ids)
        if len(active_members(db, tid)) + adding[tid] > course.max_team_size:
            raise PeerReviewError("team_full", f"A team would have more than {course.max_team_size} members", 409)
    names = set(db.scalars(select(Team.name).where(Team.course_id == course.id)))
    for item in new_teams:
        name, ids = item["name"].strip(), item["student_ids"]
        if not ids:
            continue
        if not name or name in names:
            raise PeerReviewError("team_name_taken", "Each new team needs a new, unique name", 409)
        names.add(name)
        check_students(ids)
        if len(ids) > course.max_team_size:
            raise PeerReviewError("team_full", f"A team would have more than {course.max_team_size} members", 409)

    created: list[int] = []
    try:
        for item in existing:
            for sid in item["student_ids"]:
                set_student_team(db, course.id, sid, item["team_id"], commit=False)
        for item in new_teams:
            if not item["student_ids"]:
                continue
            team = create_team(db, course.id, item["name"], commit=False)
            created.append(team.id)
            for sid in item["student_ids"]:
                set_student_team(db, course.id, sid, team.id, commit=False)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise PeerReviewError(
            "stale_proposal", "Teams changed while the proposal was being applied; propose again", 409
        )
    except Exception:
        db.rollback()
        raise
    refresh_practice_rounds(db, course.id)
    return {"placed": len(seen), "created_team_ids": created}


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
    withdrawn = set()
    for enrollment in db.scalars(select(Enrollment).where(Enrollment.course_id == rnd.course_id)):
        if enrollment.withdrawn_at is not None:
            withdrawn.add(enrollment.student_id)
            continue
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
        if student_id in withdrawn:
            continue
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
    clean_scores: dict[str, float] = {}
    for c in criteria:
        value = scores.get(c["key"])
        if value is None and not c.get("counts", True):
            continue  # optional remark
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise PeerReviewError("missing_score", f"Score required for '{c['label']}'", 422)
        if c.get("max") is not None:
            if not 0 <= value <= float(c["max"]):
                raise PeerReviewError("invalid_score", f"Score for '{c['label']}' must be 0–{c['max']:g}", 422)
            clean_scores[c["key"]] = int(value) if value == int(value) else round(float(value), 2)
            continue
        if int(value) != value or int(value) not in allowed:
            raise PeerReviewError("invalid_score", f"Score for '{c['label']}' is outside the scale", 422)
        clean_scores[c["key"]] = int(value)

    clean_responses: dict[str, str] = {}
    for p in prompts:
        value = responses.get(p["key"], "")
        text = value.strip() if isinstance(value, str) else ""
        if len(text) > MAX_RESPONSE_CHARS:
            raise PeerReviewError("response_too_long", f"'{p['label']}' is too long", 422)
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


# ---------------------------------------------------------------------------
# Site links
# ---------------------------------------------------------------------------


def check_site_link(p: Presentation) -> None:
    """Re-check the presentation's link and store the result."""
    if not p.demo_url:
        p.link_status, p.link_detail, p.link_checked_at = "", "", None
        return
    result = link_check.check_link(p.demo_url)
    p.link_status, p.link_detail, p.link_checked_at = result.status, result.detail, utcnow()


def set_site_link(p: Presentation, url: str) -> None:
    """Save a team's link and check it right away, so the team sees at once
    whether reviewers will be able to open it."""
    url = url.strip()
    if url and not url.startswith(("http://", "https://")):
        raise PeerReviewError("invalid_url", "Link must start with http(s)://", 422)
    p.demo_url = url
    check_site_link(p)
