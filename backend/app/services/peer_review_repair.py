"""Copy student reviews written in one round into another round of the same course.

For reviews that landed in the wrong round: in course 11126 a practice round
stayed open (every presentation accepting reviews) while the graded round's
presentations were never opened, so students reviewed the graded round's teams
in the practice round. A copy is the same student's review of the target
round's presentation of the same team, with the same scores, text and dates.
The original stays where it was, so a practice round keeps its history.

Never copied: AI reviews, excluded reviews, test students' reviews, and a
review where the student already has one of that team in the target round.
Nothing is committed here; the caller decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Enrollment, PeerReview, Presentation, ReviewObligation, ReviewRound, ReviewRoundRoster


@dataclass
class CopyResult:
    candidates: int = 0  # student reviews in the source round written in the time range
    copied: list[tuple[int, int]] = field(default_factory=list)  # (source review id, new review id)
    already_reviewed: int = 0  # the student already reviewed that team in the target round
    test_students: int = 0
    no_target: int = 0  # the team has no presentation in the target round
    with_obligation: int = 0  # copies that match a review assignment in the target round


def copy_reviews(
    db: Session, *, from_round_id: int, to_round_id: int, created_from: datetime, created_to: datetime
) -> CopyResult:
    """Copy the source round's student reviews created in [created_from, created_to)."""
    source = db.get(ReviewRound, from_round_id)
    target = db.get(ReviewRound, to_round_id)
    if source is None or target is None:
        raise ValueError("unknown round")
    if source.course_id != target.course_id:
        raise ValueError("the rounds belong to different courses")
    if target.rubric_version_id is None:
        raise ValueError("the target round has no frozen rubric: open reviewing for it first")

    test_ids = set(
        db.scalars(
            select(Enrollment.student_id).where(Enrollment.course_id == target.course_id, Enrollment.is_test.is_(True))
        )
    )
    target_by_team = {
        p.team_id: p for p in db.scalars(select(Presentation).where(Presentation.round_id == target.id))
    }
    roster_team = {
        r.student_id: r.team_id
        for r in db.scalars(select(ReviewRoundRoster).where(ReviewRoundRoster.round_id == target.id))
    }
    obligations = {
        (o.student_id, o.presentation_id)
        for o in db.scalars(select(ReviewObligation).where(ReviewObligation.round_id == target.id))
    }
    taken = {
        (r.presentation_id, r.reviewer_student_id)
        for r in db.scalars(select(PeerReview).where(PeerReview.round_id == target.id))
    }
    reviews = list(
        db.scalars(
            select(PeerReview)
            .where(
                PeerReview.round_id == source.id,
                PeerReview.reviewer_kind == "student",
                PeerReview.excluded.is_(False),
                PeerReview.created_at >= created_from,
                PeerReview.created_at < created_to,
            )
            .order_by(PeerReview.id)
        )
    )
    mismatched = {r.rubric_version_id for r in reviews} - {target.rubric_version_id}
    if mismatched:
        raise ValueError(f"reviews use rubric versions {sorted(mismatched)}, the target round {target.rubric_version_id}")

    result = CopyResult(candidates=len(reviews))
    for r in reviews:
        student = r.reviewer_student_id
        if student in test_ids:
            result.test_students += 1
            continue
        presented = db.get(Presentation, r.presentation_id)
        destination = target_by_team.get(presented.team_id) if presented else None
        if destination is None:
            result.no_target += 1
            continue
        if (destination.id, student) in taken:
            result.already_reviewed += 1
            continue
        copy = PeerReview(
            round_id=target.id,
            presentation_id=destination.id,
            rubric_version_id=target.rubric_version_id,
            reviewer_kind="student",
            reviewer_student_id=student,
            reviewer_team_id=roster_team.get(student, r.reviewer_team_id),
            scores_json=r.scores_json,
            responses_json=r.responses_json,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        db.add(copy)
        db.flush()
        taken.add((destination.id, student))
        result.copied.append((r.id, copy.id))
        result.with_obligation += (student, destination.id) in obligations
    return result
