"""Student-facing peer-review API, addressed by a per-student link token.

Anonymity contract: nothing returned here identifies another reviewer. A
student sees only their own reviews and, once the instructor releases a
round, their team's aggregate scores and feedback text with no reviewer ids,
names, or timestamps, in an order unrelated to submission time.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.peer_review import iso, raise_domain, record_uploaded_slides, slides_upload_target, store_slides
from app.models.entities import (
    ClassSession,
    Course,
    Enrollment,
    PeerReview,
    Presentation,
    ReviewObligation,
    ReviewRound,
    ReviewRoundRoster,
    Student,
    Team,
)
from app.schemas.api import (
    StudentMaterialsIn,
    StudentReviewIn,
    StudentSessionChoice,
    StudentTeamCreate,
    StudentTeamIn,
    StudentTeamJoin,
    UploadedFileIn,
)
from app.services import peer_review as svc
from app.services import student_grades
from app.services.peer_scoring import ScoredReview, compute_round_scores, review_scores, reviewer_shares

router = APIRouter(prefix="/api/r/{token}", tags=["student-review"])


def _enrollment(db: Session, token: str) -> Enrollment:
    enrollment = db.scalar(select(Enrollment).where(Enrollment.review_token == token)) if len(token) >= 16 else None
    if enrollment is None:
        raise HTTPException(status_code=404, detail={"code": "invalid_link", "message": "Unknown review link"})
    return enrollment


def _own_presentation(db: Session, enrollment: Enrollment, presentation_id: int) -> Presentation:
    p = db.get(Presentation, presentation_id)
    if p is None or p.round.course_id != enrollment.course_id:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Presentation not found"})
    return p


def _feedback_order(presentation_id: int, review_id: int) -> str:
    # Stable but unrelated to submission order.
    return hashlib.sha256(f"feedback:{presentation_id}:{review_id}".encode()).hexdigest()


def _released_results(db: Session, rnd: ReviewRound, presentation: Presentation) -> dict:
    result = compute_round_scores(db, rnd)
    team = next((t for t in result.teams if t.presentation_id == presentation.id), None)
    prompts = json.loads(rnd.rubric_version.prompts_json) if rnd.rubric_version else []
    criteria = json.loads(rnd.rubric_version.criteria_json) if rnd.rubric_version else []
    # The grade is only ever the normalised result computed after the round;
    # raw averages of counted criteria (e.g. the final score) are never sent.
    remarks = {c["key"] for c in criteria if not c.get("counts", True)}
    reviews = db.scalars(
        select(PeerReview).where(PeerReview.presentation_id == presentation.id, PeerReview.excluded.is_(False))
    ).all()
    feedback = []
    for r in sorted(reviews, key=lambda r: _feedback_order(presentation.id, r.id)):
        responses = json.loads(r.responses_json or "{}")
        texts = {p["key"]: responses.get(p["key"], "").strip() for p in prompts}
        if any(texts.values()):
            feedback.append({"source": "ai" if r.reviewer_kind == "llm" else "peer", "responses": texts})
    return {
        "valid_reviews": team.valid_reviews if team else 0,
        "share": team.share if team else None,
        "relative": team.relative if team else None,
        "criterion_means": {k: v for k, v in (team.criterion_means if team else {}).items() if k in remarks},
        "prompts": prompts,
        "feedback": feedback,
    }


def _round_view(
    db: Session,
    rnd: ReviewRound,
    enrollment: Enrollment,
    team_id: int | None,
    sessions: dict[int, ClassSession],
    teams: dict[int, Team],
) -> dict:
    student_id = enrollment.student_id
    today = date.today()
    presentations = list(
        db.scalars(select(Presentation).where(Presentation.round_id == rnd.id).order_by(Presentation.id))
    )
    own = next((p for p in presentations if p.team_id == team_id), None) if team_id else None

    def held_on(n: int | None) -> str | None:
        s = sessions.get(n) if n is not None else None
        return s.held_on.isoformat() if s and s.held_on else None

    view: dict = {
        "id": rnd.id,
        "number": rnd.number,
        "kind": rnd.kind,
        "title": rnd.title,
        "status": rnd.status,
        "practice": not rnd.counts_toward_grade,
        "link_required": rnd.link_required,
        "released": rnd.released_at is not None,
        "my_presentation": None,
        "selection": None,
        "reviewing": None,
        "results": None,
    }

    if own is not None:
        view["my_presentation"] = {
            "id": own.id,
            "session_number": own.session_number,
            "held_on": held_on(own.session_number),
            "demo_url": own.demo_url,
            "link_status": own.link_status,
            "link_detail": own.link_detail,
            "materials_text": own.materials_text,
            "has_slides": own.slides_artifact_id is not None,
            "editable": rnd.status != "closed",
        }

    if rnd.status == "scheduling":
        load = svc.session_load(db, rnd)
        deadline_open = rnd.selection_deadline is None or svc.utcnow() < rnd.selection_deadline
        view["selection"] = {
            "open": deadline_open,
            "deadline": iso(rnd.selection_deadline),
            "locked": own is not None and own.assignment_source == "instructor",
            "my_session": own.session_number if own else None,
            "sessions": [
                {
                    "number": s["number"],
                    "held_on": held_on(s["number"]),
                    "capacity": s["capacity"],
                    "taken": load[s["number"]],
                }
                for s in svc.round_sessions(rnd)
            ],
        }

    if rnd.status in ("reviewing", "closed") and rnd.rubric_version is not None:
        rubric = svc.rubric_payload(rnd.rubric_version)
        roster = db.scalar(
            select(ReviewRoundRoster).where(
                ReviewRoundRoster.round_id == rnd.id, ReviewRoundRoster.student_id == student_id
            )
        )
        roster_team = roster.team_id if roster else team_id
        obligations = {
            o.presentation_id: o
            for o in db.scalars(
                select(ReviewObligation).where(
                    ReviewObligation.round_id == rnd.id, ReviewObligation.student_id == student_id
                )
            )
        }
        mine = {
            r.presentation_id: r
            for r in db.scalars(
                select(PeerReview).where(PeerReview.round_id == rnd.id, PeerReview.reviewer_student_id == student_id)
            )
        }
        # The student's own normalised shares, from their own reviews only.
        shares = reviewer_shares(
            [
                ScoredReview(reviewer="me", student_id=student_id, presentation_id=pid, scores=review_scores(r))
                for pid, r in mine.items()
            ],
            rubric["criteria"],
        ).get("me", {})
        items = []
        outstanding = []
        expected = completed = 0
        for p in presentations:
            is_own = p.team_id == roster_team or p.team_id == team_id
            ob = obligations.get(p.id)
            review = mine.get(p.id)
            if ob is not None and not ob.exempt and not is_own:
                expected += 1
                if review is not None:
                    completed += 1
                else:
                    outstanding.append(p.id)
            team = teams.get(p.team_id)
            items.append(
                {
                    "id": p.id,
                    "team_name": team.name if team else "",
                    "project_title": team.project_title if team else "",
                    "demo_url": p.demo_url,
                    "link_status": p.link_status,
                    "link_detail": p.link_detail,
                    "session_number": p.session_number,
                    "held_on": held_on(p.session_number),
                    "is_today": held_on(p.session_number) == today.isoformat(),
                    "own_team": is_own,
                    "obligation": None if ob is None else ("exempt" if ob.exempt else "expected"),
                    "accepting": (not is_own) and ob is not None and svc.reviews_accepted(rnd, p),
                    "my_review": (
                        {
                            "scores": review_scores(review),
                            "responses": json.loads(review.responses_json or "{}"),
                            "updated_at": iso(review.updated_at),
                        }
                        if review
                        else None
                    ),
                    "my_share": shares.get(p.id),
                }
            )
        view["reviewing"] = {
            "deadline": iso(rnd.review_deadline),
            "rubric": rubric,
            "presentations": items,
            "progress": {"expected": expected, "completed": completed, "outstanding": outstanding},
        }

    if rnd.released_at is not None and own is not None:
        view["results"] = _released_results(db, rnd, own)
    return view


def _payload(db: Session, enrollment: Enrollment) -> dict:
    course = db.get(Course, enrollment.course_id)
    student = db.get(Student, enrollment.student_id)
    team_id = svc.active_team_id(db, enrollment.course_id, enrollment.student_id)
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.course_id == enrollment.course_id))}
    sessions = {
        s.number: s for s in db.scalars(select(ClassSession).where(ClassSession.course_id == enrollment.course_id))
    }
    rounds = db.scalars(
        select(ReviewRound)
        .where(ReviewRound.course_id == enrollment.course_id, ReviewRound.status != "draft")
        .order_by(ReviewRound.number)
    ).all()
    team = teams.get(team_id) if team_id else None
    members = (
        [s.name for s in db.scalars(select(Student).where(Student.id.in_(svc.active_members(db, team.id))).order_by(Student.name))]
        if team
        else []
    )
    return {
        "student": {"name": student.name if student else ""},
        "course": {"name": course.name if course else "", "code": course.code if course else ""},
        "team": (
            {
                "id": team.id,
                "name": team.name,
                "project_title": team.project_title,
                "join_code": team.join_code,
                "members": members,
            }
            if team
            else None
        ),
        "teams_policy": {
            "open": bool(course and course.teams_open),
            "max_size": course.max_team_size if course else None,
        },
        "today": date.today().isoformat(),
        "rounds": [_round_view(db, r, enrollment, team_id, sessions, teams) for r in rounds],
        "grades": student_grades.grades_view(db, enrollment),
    }


@router.get("")
def student_home(token: str, db: Session = Depends(get_db)) -> dict:
    return _payload(db, _enrollment(db, token))


@router.put("/reviews/{presentation_id}")
def submit_review(token: str, presentation_id: int, payload: StudentReviewIn, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    p = _own_presentation(db, enrollment, presentation_id)
    try:
        svc.submit_student_review(db, enrollment.student_id, p, payload.scores, payload.responses)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return _payload(db, enrollment)


@router.put("/presentations/{presentation_id}/session")
def choose_session(
    token: str, presentation_id: int, payload: StudentSessionChoice, db: Session = Depends(get_db)
) -> dict:
    enrollment = _enrollment(db, token)
    p = _own_presentation(db, enrollment, presentation_id)
    try:
        svc.volunteer_for_session(db, enrollment.student_id, p, payload.session_number)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return _payload(db, enrollment)


def _require_own_team(db: Session, enrollment: Enrollment, p: Presentation) -> None:
    if svc.active_team_id(db, enrollment.course_id, enrollment.student_id) != p.team_id:
        raise HTTPException(status_code=403, detail={"code": "not_your_team", "message": "Not your team"})
    if p.round.status == "closed":
        raise HTTPException(status_code=409, detail={"code": "window_closed", "message": "Round is closed"})


@router.patch("/presentations/{presentation_id}/materials")
def update_materials(
    token: str, presentation_id: int, payload: StudentMaterialsIn, db: Session = Depends(get_db)
) -> dict:
    enrollment = _enrollment(db, token)
    p = _own_presentation(db, enrollment, presentation_id)
    _require_own_team(db, enrollment, p)
    if payload.demo_url is not None:
        try:
            svc.set_site_link(p, payload.demo_url)
        except svc.PeerReviewError as exc:
            raise_domain(exc)
    if payload.materials_text is not None:
        p.materials_text = payload.materials_text
    db.commit()
    return _payload(db, enrollment)


@router.post("/presentations/{presentation_id}/slides")
async def upload_slides(
    token: str, presentation_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict:
    enrollment = _enrollment(db, token)
    p = _own_presentation(db, enrollment, presentation_id)
    _require_own_team(db, enrollment, p)
    await store_slides(db, p, file)
    return _payload(db, enrollment)


@router.post("/presentations/{presentation_id}/slides/upload-url")
def slides_upload_url(token: str, presentation_id: int, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    p = _own_presentation(db, enrollment, presentation_id)
    _require_own_team(db, enrollment, p)
    return slides_upload_target(p)


@router.post("/presentations/{presentation_id}/slides/complete")
def slides_complete(token: str, presentation_id: int, payload: UploadedFileIn, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    p = _own_presentation(db, enrollment, presentation_id)
    _require_own_team(db, enrollment, p)
    record_uploaded_slides(db, p, payload)
    return _payload(db, enrollment)


@router.post("/team")
def create_team(token: str, payload: StudentTeamCreate, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    try:
        svc.student_create_team(db, enrollment.course, enrollment.student_id, payload.name, payload.project_title)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return _payload(db, enrollment)


@router.post("/team/join")
def join_team(token: str, payload: StudentTeamJoin, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    try:
        svc.student_join_team(db, enrollment.course, enrollment.student_id, payload.code)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return _payload(db, enrollment)


@router.post("/team/leave")
def leave_team(token: str, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    try:
        svc.student_leave_team(db, enrollment.course, enrollment.student_id)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return _payload(db, enrollment)


@router.patch("/team")
def update_team(token: str, payload: StudentTeamIn, db: Session = Depends(get_db)) -> dict:
    enrollment = _enrollment(db, token)
    team_id = svc.active_team_id(db, enrollment.course_id, enrollment.student_id)
    if team_id is None:
        raise HTTPException(status_code=404, detail={"code": "no_team", "message": "You are not on a team"})
    team = db.get(Team, team_id)
    team.project_title = payload.project_title.strip()
    db.commit()
    return _payload(db, enrollment)


# Instructor preview: the exact payload a student sees, for any enrolled
# student. Lives under /api/courses, so it needs the instructor token.
preview_router = APIRouter(prefix="/api/courses/{course_id}/peer/student-view", tags=["student-review"])


@preview_router.get("/{student_id}")
def student_view_preview(course_id: int, student_id: int, db: Session = Depends(get_db)) -> dict:
    enrollment = db.scalar(
        select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student_id)
    )
    if enrollment is None:
        raise HTTPException(status_code=404, detail="Student is not enrolled in this course")
    return _payload(db, enrollment)
