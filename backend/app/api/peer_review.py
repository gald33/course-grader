"""Instructor API for peer review. Reviewer identities appear only here.

Protected like every other instructor route (see INSTRUCTOR_TOKEN in
app/main.py); student routes live in app/api/student_review.py.
"""

from __future__ import annotations

import json
import mimetypes
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import (
    Artifact,
    ClassSession,
    Course,
    Enrollment,
    PeerReview,
    Presentation,
    PresentationMove,
    ReviewObligation,
    ReviewRound,
    ReviewRoundRoster,
    Student,
    Team,
    TeamMembership,
)
from app.schemas.api import (
    ExemptionUpdate,
    PresentationUpdate,
    ReviewExclusion,
    RoundUpdate,
    RubricSave,
    SessionReviewToggle,
    SessionUpdate,
    StudentTeamUpdate,
    SwapRequest,
    TeamCreate,
    PracticeRoundIn,
    TeamUpdate,
    UploadedFileIn,
)
from app.services import peer_review as svc
from app.services.llm_peer_review import run_llm_round_review
from app.services import storage
from app.services.peer_export import export_round_xlsx
from app.services.peer_scoring import compute_round_scores, review_scores, weighted_total

router = APIRouter(prefix="/api/courses/{course_id}/peer", tags=["peer-review"])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def to_utc_naive(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def raise_domain(exc: svc.PeerReviewError) -> None:
    raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def _course(db: Session, course_id: int) -> Course:
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def _round(db: Session, course_id: int, round_id: int) -> ReviewRound:
    rnd = db.get(ReviewRound, round_id)
    if not rnd or rnd.course_id != course_id:
        raise HTTPException(status_code=404, detail="Round not found")
    return rnd


def _presentation(db: Session, course_id: int, presentation_id: int) -> Presentation:
    p = db.get(Presentation, presentation_id)
    if not p or p.round.course_id != course_id:
        raise HTTPException(status_code=404, detail="Presentation not found")
    return p


def _team(db: Session, course_id: int, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if not team or team.course_id != course_id:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


def _round_payload(db: Session, rnd: ReviewRound, teams: dict[int, Team]) -> dict:
    presentations = list(
        db.scalars(select(Presentation).where(Presentation.round_id == rnd.id).order_by(Presentation.id))
    )
    load = svc.session_load(db, rnd)
    student_reviews: dict[int, int] = defaultdict(int)
    llm_reviewed: set[int] = set()
    for r in db.scalars(select(PeerReview).where(PeerReview.round_id == rnd.id)):
        if r.reviewer_kind == "llm":
            llm_reviewed.add(r.presentation_id)
        elif not r.excluded:
            student_reviews[r.presentation_id] += 1
    moves: dict[int, int] = defaultdict(int)
    for pid, n in db.execute(
        select(PresentationMove.presentation_id, func.count())
        .where(PresentationMove.presentation_id.in_([p.id for p in presentations] or [-1]))
        .group_by(PresentationMove.presentation_id)
    ):
        moves[pid] = n

    obligations = list(
        db.scalars(select(ReviewObligation).where(ReviewObligation.round_id == rnd.id, ReviewObligation.exempt.is_(False)))
    )
    done = {
        (r.reviewer_student_id, r.presentation_id)
        for r in db.scalars(
            select(PeerReview).where(
                PeerReview.round_id == rnd.id, PeerReview.reviewer_kind == "student", PeerReview.excluded.is_(False)
            )
        )
    }
    completed = sum(1 for o in obligations if (o.student_id, o.presentation_id) in done)

    return {
        "id": rnd.id,
        "number": rnd.number,
        "kind": rnd.kind,
        "title": rnd.title,
        "status": rnd.status,
        "sessions": [{**s, "load": load[s["number"]]} for s in svc.round_sessions(rnd)],
        "selection_deadline": iso(rnd.selection_deadline),
        "review_deadline": iso(rnd.review_deadline),
        "released_at": iso(rnd.released_at),
        "rubric_version": (
            {"id": rnd.rubric_version.id, "version": rnd.rubric_version.version} if rnd.rubric_version else None
        ),
        "target_mean": rnd.target_mean,
        "target_std": rnd.target_std,
        "missing_review_policy": rnd.missing_review_policy,
        "participation_factor": rnd.participation_factor,
        "llm_enabled": rnd.llm_enabled,
        "counts_toward_grade": rnd.counts_toward_grade,
        "obligations": {"expected": len(obligations), "completed": completed},
        "presentations": [
            {
                "id": p.id,
                "team_id": p.team_id,
                "team_name": teams[p.team_id].name if p.team_id in teams else "?",
                "project_title": teams[p.team_id].project_title if p.team_id in teams else "",
                "session_number": p.session_number,
                "original_session_number": p.original_session_number,
                "assignment_source": p.assignment_source,
                "status": p.status,
                "review_open": p.review_open,
                "demo_url": p.demo_url,
                "materials_text": p.materials_text,
                "has_slides": p.slides_artifact_id is not None,
                "slides_artifact_id": p.slides_artifact_id,
                "review_count": student_reviews[p.id],
                "llm_reviewed": p.id in llm_reviewed,
                "moves": moves[p.id],
            }
            for p in presentations
        ],
    }


# ---------------------------------------------------------------------------
# Overview, setup, sessions
# ---------------------------------------------------------------------------


@router.get("/overview")
def overview(course_id: int, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.course_id == course_id).order_by(Team.name))}
    member_counts: dict[int, int] = defaultdict(int)
    for m in db.scalars(
        select(TeamMembership).where(TeamMembership.course_id == course_id, TeamMembership.end_at.is_(None))
    ):
        member_counts[m.team_id] += 1
    sessions = db.scalars(
        select(ClassSession).where(ClassSession.course_id == course_id).order_by(ClassSession.number)
    ).all()
    rounds = db.scalars(
        select(ReviewRound).where(ReviewRound.course_id == course_id).order_by(ReviewRound.number)
    ).all()
    student_count = db.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.course_id == course_id))
    return {
        "sessions": [
            {"number": s.number, "held_on": s.held_on.isoformat() if s.held_on else None, "title": s.title}
            for s in sessions
        ],
        "rounds": [_round_payload(db, r, teams) for r in rounds],
        "teams": [
            {"id": t.id, "name": t.name, "project_title": t.project_title, "member_count": member_counts[t.id]}
            for t in teams.values()
        ],
        "student_count": student_count or 0,
    }


@router.post("/setup")
def setup(course_id: int, db: Session = Depends(get_db)) -> dict:
    course = _course(db, course_id)
    svc.setup_default_schedule(db, course)
    return {"status": "ok"}


@router.patch("/sessions/{number}")
def update_session(course_id: int, number: int, payload: SessionUpdate, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    session = db.scalar(select(ClassSession).where(ClassSession.course_id == course_id, ClassSession.number == number))
    if session is None:
        session = ClassSession(course_id=course_id, number=number)
        db.add(session)
    session.held_on = payload.held_on
    if payload.title is not None:
        session.title = payload.title
    db.commit()
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------


@router.get("/teams")
def list_teams(course_id: int, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    teams = db.scalars(select(Team).where(Team.course_id == course_id).order_by(Team.name)).all()
    active = {
        m.student_id: m.team_id
        for m in db.scalars(
            select(TeamMembership).where(TeamMembership.course_id == course_id, TeamMembership.end_at.is_(None))
        )
    }
    students = db.scalars(
        select(Student).join(Enrollment).where(Enrollment.course_id == course_id).order_by(Student.name)
    ).all()
    return {
        "teams": [{"id": t.id, "name": t.name, "project_title": t.project_title} for t in teams],
        "students": [
            {"student_id": s.id, "name": s.name, "national_id": s.national_id, "team_id": active.get(s.id)}
            for s in students
        ],
    }


@router.post("/teams")
def create_team(course_id: int, payload: TeamCreate, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    if db.scalar(select(Team).where(Team.course_id == course_id, Team.name == payload.name.strip())):
        raise HTTPException(status_code=409, detail="A team with this name already exists")
    team = Team(course_id=course_id, name=payload.name.strip(), project_title=payload.project_title.strip())
    db.add(team)
    db.flush()
    # Rounds not yet open for reviewing get a presentation slot for the team.
    for rnd in db.scalars(select(ReviewRound).where(ReviewRound.course_id == course_id)):
        if rnd.status in ("draft", "scheduling"):
            svc.sync_round_presentations(db, rnd)
    db.commit()
    svc.refresh_practice_rounds(db, course_id)
    return {"id": team.id}


@router.patch("/teams/{team_id}")
def update_team(course_id: int, team_id: int, payload: TeamUpdate, db: Session = Depends(get_db)) -> dict:
    team = _team(db, course_id, team_id)
    if payload.name is not None:
        team.name = payload.name.strip()
    if payload.project_title is not None:
        team.project_title = payload.project_title.strip()
    db.commit()
    return {"status": "ok"}


@router.delete("/teams/{team_id}")
def delete_team(course_id: int, team_id: int, db: Session = Depends(get_db)) -> dict:
    team = _team(db, course_id, team_id)
    pres_ids = list(db.scalars(select(Presentation.id).where(Presentation.team_id == team.id)))
    has_history = pres_ids and (
        db.scalar(select(func.count()).select_from(PeerReview).where(PeerReview.presentation_id.in_(pres_ids)))
        or db.scalar(
            select(func.count()).select_from(ReviewObligation).where(ReviewObligation.presentation_id.in_(pres_ids))
        )
    )
    if has_history or db.scalar(
        select(func.count()).select_from(ReviewRoundRoster).where(ReviewRoundRoster.team_id == team.id)
    ):
        raise HTTPException(status_code=409, detail="This team already has review history and can't be deleted")
    db.delete(team)
    db.commit()
    return {"status": "ok"}


@router.put("/students/{student_id}/team")
def set_student_team(course_id: int, student_id: int, payload: StudentTeamUpdate, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    if not db.scalar(select(Enrollment).where(Enrollment.course_id == course_id, Enrollment.student_id == student_id)):
        raise HTTPException(status_code=404, detail="Student is not enrolled in this course")
    try:
        svc.set_student_team(db, course_id, student_id, payload.team_id)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Rubrics
# ---------------------------------------------------------------------------


@router.get("/rubrics")
def get_rubrics(course_id: int, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    out = {}
    for kind in svc.ROUND_KINDS:
        rubric = svc.latest_rubric(db, course_id, kind, create=True)
        assert rubric is not None
        used_by = [
            r.number
            for r in db.scalars(select(ReviewRound).where(ReviewRound.rubric_version_id == rubric.id))
        ]
        out[kind] = {**svc.rubric_payload(rubric), "used_by_rounds": used_by}
    db.commit()
    return out


@router.put("/rubrics/{kind}")
def save_rubric(course_id: int, kind: str, payload: RubricSave, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    try:
        rubric = svc.save_rubric(
            db,
            course_id,
            kind,
            [c.model_dump() for c in payload.criteria],
            [s.model_dump() for s in payload.scale],
            [p.model_dump() for p in payload.prompts],
            payload.instructions,
        )
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return svc.rubric_payload(rubric)


# ---------------------------------------------------------------------------
# Rounds & scheduling
# ---------------------------------------------------------------------------


@router.post("/rounds/practice")
def create_practice_round(course_id: int, payload: PracticeRoundIn, db: Session = Depends(get_db)) -> dict:
    """A round for trying the process: never counts toward a grade."""
    course = _course(db, course_id)
    try:
        rnd = svc.create_practice_round(db, course, payload.title, payload.open_now)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok", "round_id": rnd.id, "number": rnd.number}


@router.patch("/rounds/{round_id}")
def update_round(course_id: int, round_id: int, payload: RoundUpdate, db: Session = Depends(get_db)) -> dict:
    rnd = _round(db, course_id, round_id)
    if payload.title is not None:
        rnd.title = payload.title
    if payload.sessions is not None:
        numbers = [s.number for s in payload.sessions]
        if len(set(numbers)) != len(numbers):
            raise HTTPException(status_code=400, detail="Duplicate session in round")
        rnd.sessions_json = json.dumps([s.model_dump() for s in payload.sessions])
    if payload.clear_selection_deadline:
        rnd.selection_deadline = None
    elif payload.selection_deadline is not None:
        rnd.selection_deadline = to_utc_naive(payload.selection_deadline)
    if payload.clear_review_deadline:
        rnd.review_deadline = None
    elif payload.review_deadline is not None:
        rnd.review_deadline = to_utc_naive(payload.review_deadline)
    for field in ("target_mean", "target_std", "missing_review_policy", "participation_factor", "llm_enabled"):
        value = getattr(payload, field)
        if value is not None:
            setattr(rnd, field, value)
    db.commit()
    return {"status": "ok"}


ROUND_ACTIONS = {
    "open-selection": svc.open_selection,
    "open-reviewing": svc.open_reviewing,
    "close": svc.close_round,
    "reopen": svc.reopen_round,
    "release": svc.release_round,
    "unrelease": svc.unrelease_round,
}


@router.post("/rounds/{round_id}/actions/{action}")
def round_action(course_id: int, round_id: int, action: str, db: Session = Depends(get_db)) -> dict:
    rnd = _round(db, course_id, round_id)
    try:
        if action == "random-assign":
            assigned, left = svc.random_assign(db, rnd)
            return {"status": "ok", "assigned": assigned, "left_unassigned": left}
        if action == "sync":
            created = svc.sync_round_presentations(db, rnd)
            db.commit()
            snapshot = svc.snapshot_round(db, rnd) if rnd.status in ("reviewing", "closed") else {}
            return {"status": "ok", "presentations_added": created, **snapshot}
        handler = ROUND_ACTIONS.get(action)
        if handler is None:
            raise HTTPException(status_code=404, detail="Unknown action")
        handler(db, rnd)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok"}


@router.post("/rounds/{round_id}/sessions/{session_number}/reviewing")
def toggle_session_reviewing(
    course_id: int, round_id: int, session_number: int, payload: SessionReviewToggle, db: Session = Depends(get_db)
) -> dict:
    rnd = _round(db, course_id, round_id)
    try:
        changed = svc.set_session_review_open(db, rnd, session_number, payload.open)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok", "changed": changed}


@router.patch("/presentations/{presentation_id}")
def update_presentation(
    course_id: int, presentation_id: int, payload: PresentationUpdate, db: Session = Depends(get_db)
) -> dict:
    p = _presentation(db, course_id, presentation_id)
    try:
        if payload.move:
            svc.move_presentation(db, p, payload.session_number, payload.reason.strip(), postpone=payload.postpone)
        if payload.demo_url is not None:
            p.demo_url = payload.demo_url.strip()
        if payload.materials_text is not None:
            p.materials_text = payload.materials_text
        if payload.review_open is not None:
            if payload.review_open and p.round.status != "reviewing":
                raise svc.PeerReviewError("invalid_state", "Open reviewing for the round first", 409)
            p.review_open = payload.review_open
        db.commit()
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok"}


@router.post("/presentations/{presentation_id}/slides")
async def upload_slides(
    course_id: int, presentation_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
) -> dict:
    p = _presentation(db, course_id, presentation_id)
    artifact = await store_slides(db, p, file)
    return {"status": "ok", "artifact_id": artifact.id}


MAX_SLIDES_BYTES = 20 * 1024 * 1024


def slides_key(p: Presentation) -> str:
    return f"peer/rounds/{p.round_id}/presentation_{p.id}_slides.pdf"


def _record_slides(db: Session, p: Presentation, data: bytes, filename: str, location: str | None = None) -> Artifact:
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail={"code": "not_pdf", "message": "Slides must be a PDF"})
    if len(data) > MAX_SLIDES_BYTES:
        raise HTTPException(status_code=413, detail={"code": "too_large", "message": "PDF is larger than 20 MB"})
    artifact = Artifact(
        kind="presentation_slides",
        filename=filename or f"presentation_{p.id}_slides.pdf",
        path=location or storage.save(slides_key(p), data, "application/pdf"),
        mime_type=mimetypes.types_map.get(".pdf", "application/pdf"),
        size_bytes=len(data),
    )
    db.add(artifact)
    db.flush()
    p.slides_artifact_id = artifact.id
    db.commit()
    return artifact


async def store_slides(db: Session, p: Presentation, file: UploadFile) -> Artifact:
    """Upload through the API (local storage, or small files)."""
    return _record_slides(db, p, await file.read(), file.filename or "")


def slides_upload_target(p: Presentation) -> dict:
    """Where the browser should send a slides PDF: straight to Storage with a
    signed URL when hosted (request bodies are capped), else to the API."""
    if not storage.direct_uploads_enabled():
        return {"direct": False}
    key = slides_key(p)
    return {"direct": True, "url": storage.signed_upload_url(key), "key": key}


def record_uploaded_slides(db: Session, p: Presentation, payload: UploadedFileIn) -> Artifact:
    """Register slides the browser uploaded directly to Storage."""
    if payload.key != slides_key(p):
        raise HTTPException(status_code=400, detail={"code": "bad_key", "message": "Unexpected upload key"})
    location = storage.location_for(payload.key)
    try:
        data = storage.read_bytes(location)
    except storage.StorageError:
        raise HTTPException(status_code=400, detail={"code": "upload_missing", "message": "Upload not found"})
    return _record_slides(db, p, data, payload.filename, location=location)


@router.post("/presentations/{presentation_id}/slides/upload-url")
def instructor_slides_upload_url(course_id: int, presentation_id: int, db: Session = Depends(get_db)) -> dict:
    return slides_upload_target(_presentation(db, course_id, presentation_id))


@router.post("/presentations/{presentation_id}/slides/complete")
def instructor_slides_complete(
    course_id: int, presentation_id: int, payload: UploadedFileIn, db: Session = Depends(get_db)
) -> dict:
    artifact = record_uploaded_slides(db, _presentation(db, course_id, presentation_id), payload)
    return {"status": "ok", "artifact_id": artifact.id}


@router.post("/rounds/{round_id}/swap")
def swap(course_id: int, round_id: int, payload: SwapRequest, db: Session = Depends(get_db)) -> dict:
    rnd = _round(db, course_id, round_id)
    a = _presentation(db, course_id, payload.a_id)
    b = _presentation(db, course_id, payload.b_id)
    if a.round_id != rnd.id:
        raise HTTPException(status_code=400, detail="Presentation is not in this round")
    try:
        svc.swap_presentations(db, a, b, payload.reason.strip())
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok"}


@router.get("/presentations/{presentation_id}/moves")
def presentation_moves(course_id: int, presentation_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _presentation(db, course_id, presentation_id)
    return [
        {
            "id": m.id,
            "from_session": m.from_session,
            "to_session": m.to_session,
            "kind": m.kind,
            "actor": m.actor,
            "reason": m.reason,
            "created_at": iso(m.created_at),
        }
        for m in db.scalars(
            select(PresentationMove)
            .where(PresentationMove.presentation_id == presentation_id)
            .order_by(PresentationMove.id)
        )
    ]


# ---------------------------------------------------------------------------
# Reviews, moderation, participation, exemptions
# ---------------------------------------------------------------------------


@router.get("/rounds/{round_id}/reviews")
def round_reviews(course_id: int, round_id: int, db: Session = Depends(get_db)) -> list[dict]:
    """Individual reviews WITH reviewer identity — instructor only."""
    rnd = _round(db, course_id, round_id)
    criteria = json.loads(rnd.rubric_version.criteria_json) if rnd.rubric_version else []
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.course_id == course_id))}
    presentations = {p.id: p for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id))}
    students = {
        s.id: s
        for s in db.scalars(select(Student).join(Enrollment).where(Enrollment.course_id == course_id))
    }
    out = []
    for r in db.scalars(select(PeerReview).where(PeerReview.round_id == rnd.id).order_by(PeerReview.id)):
        p = presentations.get(r.presentation_id)
        reviewer = students.get(r.reviewer_student_id) if r.reviewer_student_id else None
        scores = review_scores(r)
        out.append(
            {
                "id": r.id,
                "presentation_id": r.presentation_id,
                "team_name": teams[p.team_id].name if p and p.team_id in teams else "?",
                "session_number": p.session_number if p else None,
                "reviewer_kind": r.reviewer_kind,
                "reviewer_student_id": r.reviewer_student_id,
                "reviewer_name": reviewer.name if reviewer else ("LLM" if r.reviewer_kind == "llm" else None),
                "reviewer_national_id": reviewer.national_id if reviewer else None,
                "reviewer_team_name": teams[r.reviewer_team_id].name if r.reviewer_team_id in teams else None,
                "scores": scores,
                "weighted_total": weighted_total(scores, criteria),
                "responses": json.loads(r.responses_json or "{}"),
                "llm_rationales": json.loads(r.llm_rationale_json) if r.llm_rationale_json else None,
                "llm_model": r.llm_model,
                "excluded": r.excluded,
                "exclusion_reason": r.exclusion_reason,
                "excluded_at": iso(r.excluded_at),
                "created_at": iso(r.created_at),
                "updated_at": iso(r.updated_at),
            }
        )
    return out


@router.post("/reviews/{review_id}/exclusion")
def set_exclusion(course_id: int, review_id: int, payload: ReviewExclusion, db: Session = Depends(get_db)) -> dict:
    review = db.get(PeerReview, review_id)
    if not review or db.get(ReviewRound, review.round_id).course_id != course_id:
        raise HTTPException(status_code=404, detail="Review not found")
    try:
        svc.set_review_exclusion(db, review, payload.excluded, payload.reason)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok"}


@router.get("/rounds/{round_id}/participation")
def participation(course_id: int, round_id: int, db: Session = Depends(get_db)) -> list[dict]:
    rnd = _round(db, course_id, round_id)
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.course_id == course_id))}
    presentations = {p.id: p for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id))}
    roster = list(db.scalars(select(ReviewRoundRoster).where(ReviewRoundRoster.round_id == rnd.id)))
    students = {s.id: s for s in db.scalars(select(Student).where(Student.id.in_([r.student_id for r in roster] or [-1])))}
    reviews = {
        (r.reviewer_student_id, r.presentation_id): r
        for r in db.scalars(select(PeerReview).where(PeerReview.round_id == rnd.id, PeerReview.reviewer_kind == "student"))
    }
    by_student: dict[int, list[ReviewObligation]] = defaultdict(list)
    for o in db.scalars(select(ReviewObligation).where(ReviewObligation.round_id == rnd.id)):
        by_student[o.student_id].append(o)

    out = []
    for row in roster:
        s = students.get(row.student_id)
        items = []
        expected = completed = exempt = excluded = 0
        for o in sorted(by_student[row.student_id], key=lambda o: (presentations[o.presentation_id].session_number or 99, o.presentation_id)):
            p = presentations[o.presentation_id]
            review = reviews.get((row.student_id, o.presentation_id))
            state = "exempt" if o.exempt else ("excluded" if review and review.excluded else ("done" if review else "missing"))
            if o.exempt:
                exempt += 1
            else:
                expected += 1
                if review and not review.excluded:
                    completed += 1
                if review and review.excluded:
                    excluded += 1
            items.append(
                {
                    "presentation_id": p.id,
                    "team_name": teams[p.team_id].name if p.team_id in teams else "?",
                    "session_number": p.session_number,
                    "state": state,
                    "exempt_reason": o.exempt_reason,
                }
            )
        out.append(
            {
                "student_id": row.student_id,
                "name": s.name if s else "?",
                "national_id": s.national_id if s else "",
                "team_name": teams[row.team_id].name if row.team_id in teams else None,
                "expected": expected,
                "completed": completed,
                "exempt": exempt,
                "excluded": excluded,
                "items": items,
            }
        )
    out.sort(key=lambda r: r["name"])
    return out


@router.post("/rounds/{round_id}/exemptions")
def update_exemptions(course_id: int, round_id: int, payload: ExemptionUpdate, db: Session = Depends(get_db)) -> dict:
    rnd = _round(db, course_id, round_id)
    if payload.presentation_ids is not None:
        ids = payload.presentation_ids
    elif payload.session_number is not None:
        ids = list(
            db.scalars(
                select(Presentation.id).where(
                    Presentation.round_id == rnd.id, Presentation.session_number == payload.session_number
                )
            )
        )
    else:
        ids = list(db.scalars(select(Presentation.id).where(Presentation.round_id == rnd.id)))
    try:
        changed = svc.set_exemptions(db, rnd, payload.student_id, ids, payload.exempt, payload.reason)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok", "changed": changed}


# ---------------------------------------------------------------------------
# Scores, LLM grader, export
# ---------------------------------------------------------------------------


def round_scores_payload(db: Session, rnd: ReviewRound) -> dict:
    result = compute_round_scores(db, rnd)
    teams = {t.id: t for t in db.scalars(select(Team).where(Team.course_id == rnd.course_id))}
    presentations = {p.id: p for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id))}
    students = {
        s.id: s for s in db.scalars(select(Student).where(Student.id.in_([s.student_id for s in result.students] or [-1])))
    }
    return {
        "round_id": rnd.id,
        "criteria": json.loads(rnd.rubric_version.criteria_json) if rnd.rubric_version else [],
        "counts_toward_grade": rnd.counts_toward_grade,
        "settings": {
            "target_mean": rnd.target_mean,
            "target_std": rnd.target_std,
            "missing_review_policy": rnd.missing_review_policy,
            "participation_factor": rnd.participation_factor,
        },
        "teams": [
            {
                "presentation_id": t.presentation_id,
                "team_id": t.team_id,
                "team_name": teams[t.team_id].name if t.team_id in teams else "?",
                "project_title": teams[t.team_id].project_title if t.team_id in teams else "",
                "session_number": presentations[t.presentation_id].session_number,
                "valid_reviews": t.valid_reviews,
                "share": t.share,
                "relative": t.relative,
                "mean_total": t.mean_total,
                "criterion_means": t.criterion_means,
            }
            for t in result.teams
        ],
        "students": [
            {
                "student_id": s.student_id,
                "name": students[s.student_id].name if s.student_id in students else "?",
                "national_id": students[s.student_id].national_id if s.student_id in students else "",
                "team_name": teams[s.team_id].name if s.team_id in teams else None,
                "expected": s.expected,
                "completed": s.completed,
                "exempt": s.exempt,
                "participation_rate": s.participation_rate,
                "review_score": s.review_score,
                "adjusted_review_score": s.adjusted_review_score,
                "team_share": s.team_share,
                "raw": s.raw,
                "normalized": s.normalized,
                "bonus": s.bonus,
                "final": s.final,
                "flags": s.flags,
            }
            for s in result.students
        ],
    }


@router.get("/rounds/{round_id}/scores")
def round_scores(course_id: int, round_id: int, db: Session = Depends(get_db)) -> dict:
    return round_scores_payload(db, _round(db, course_id, round_id))


@router.post("/rounds/{round_id}/llm-review")
def llm_review(course_id: int, round_id: int, db: Session = Depends(get_db)) -> dict:
    rnd = _round(db, course_id, round_id)
    try:
        saved = run_llm_round_review(db, rnd)
    except svc.PeerReviewError as exc:
        raise_domain(exc)
    return {"status": "ok", "reviews": len(saved)}


@router.get("/rounds/{round_id}/export.xlsx")
def export_round(course_id: int, round_id: int, db: Session = Depends(get_db)) -> FileResponse:
    rnd = _round(db, course_id, round_id)
    path = export_round_xlsx(db, rnd, round_scores_payload(db, rnd))
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=path.name,
    )


# ---------------------------------------------------------------------------
# Student links
# ---------------------------------------------------------------------------


@router.get("/links")
def review_links(course_id: int, db: Session = Depends(get_db)) -> list[dict]:
    _course(db, course_id)
    active = {
        m.student_id: m.team_id
        for m in db.scalars(
            select(TeamMembership).where(TeamMembership.course_id == course_id, TeamMembership.end_at.is_(None))
        )
    }
    teams = {t.id: t.name for t in db.scalars(select(Team).where(Team.course_id == course_id))}
    rows = db.execute(
        select(Enrollment, Student).join(Student).where(Enrollment.course_id == course_id).order_by(Student.name)
    ).all()
    return [
        {
            "enrollment_id": e.id,
            "student_id": s.id,
            "name": s.name,
            "national_id": s.national_id,
            "team_name": teams.get(active.get(s.id)) if active.get(s.id) else None,
            "token": e.review_token,
        }
        for e, s in rows
    ]


@router.post("/links/generate")
def generate_links(course_id: int, db: Session = Depends(get_db)) -> dict:
    _course(db, course_id)
    return {"status": "ok", "created": svc.ensure_review_tokens(db, course_id)}


@router.post("/links/{enrollment_id}/regenerate")
def regenerate_link(course_id: int, enrollment_id: int, db: Session = Depends(get_db)) -> dict:
    enrollment = db.get(Enrollment, enrollment_id)
    if not enrollment or enrollment.course_id != course_id:
        raise HTTPException(status_code=404, detail="Enrollment not found")
    enrollment.review_token = svc.new_review_token()
    db.commit()
    return {"status": "ok", "token": enrollment.review_token}
