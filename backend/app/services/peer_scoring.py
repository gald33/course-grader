"""Peer-review scoring for one review round.

Pipeline (one assignment grade per round):

1. Review total — each review's criterion scores are combined with the
   rubric weights, normalised by the sum of weights (stays on the 1–5 scale).
2. Reviewer shares — each reviewer's totals are normalised to sum to 1 over
   every presentation they reviewed in the round: n[r, p].
3. Team score — the class's view C, anchored by the AI grader's view A:
       T[p] = (1 − a) · C[p] + a · A[p]          a = the round's llm_weight
   C is the share of all students' normalised score mass given to the team:
       zero policy:     C[p] = Σ_s n[s, p] / Σ_s Σ_q n[s, q]
       missing policy:  m[s, p] = n[s, p] · |P_s|   (1.0 = "average" for s)
                        C[p] ∝ mean over student reviewers of p of m[s, p]
   The two coincide when every reviewer covers the same number of teams and
   every team gets the same number of reviewers. The missing policy (default)
   keeps a missing review from acting as a zero for the presenting team, e.g.
   a larger team (fewer eligible reviewers) or a session with absences.
   A is the AI's own shares n[AI, p]. Where the AI reviewed only some of the
   teams, its shares are rescaled to the class's mass on those teams, so
   Σ T = 1 still holds and a team the AI did not review keeps C[p].
   A presentation with no valid student reviews is "not yet scored" (None):
   the AI anchors the class's view but never replaces it.
4. Review score — R[s] = Σ_p T[p] · n[s, p]: how much of the student's own
   mass went to the teams everyone else rated highly.
   Optional participation factor: R'[s] = R[s] · completed / expected, where
   expected counts non-exempt obligations only.
5. Raw score — R'[s] · T[team(s)], normalised so Σ_s raw = 1.
6. Normalised score — raw scores rescaled to the round's target mean and
   standard deviation (population), clamped to 0–100.
7. Final — normalised score + instructor bonus.

The AI grader enters only through A in step 3; it has no review score of its
own, but since R[s] is measured against T, it anchors every review score too.
Every student reviewer has equal weight; there is no reputation weighting.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import (
    Enrollment,
    PeerReview,
    Presentation,
    ReviewObligation,
    ReviewRound,
    ReviewRoundRoster,
    StudentComponentOverride,
)

LLM_REVIEWER = "llm"
# Share of each team score that comes from the AI grader (ReviewRound.llm_weight).
DEFAULT_LLM_WEIGHT = 1 / 3


def bonus_component(round_number: int) -> str:
    """StudentComponentOverride.component used for a round's bonus points."""
    return f"peer_round_{round_number}_bonus"


def score_component(round_number: int) -> str:
    """StudentComponentOverride.component a round's final scores are applied
    to the gradebook under (see apply_round_to_gradebook)."""
    return f"peer_round_{round_number}"


@dataclass(frozen=True)
class ScoredReview:
    reviewer: str  # "s:<student_id>" or LLM_REVIEWER
    student_id: int | None
    presentation_id: int
    scores: dict[str, float]


@dataclass(frozen=True)
class Obligation:
    student_id: int
    presentation_id: int
    exempt: bool


@dataclass
class RoundInputs:
    criteria: list[dict]
    presentations: dict[int, int]  # presentation_id -> team_id
    roster: dict[int, int | None]  # student_id -> team_id (snapshot)
    reviews: list[ScoredReview]  # valid (non-excluded) reviews only
    obligations: list[Obligation]
    bonuses: dict[int, float] = field(default_factory=dict)
    missing_review_policy: str = "missing"
    participation_factor: bool = True
    target_mean: float = 80.0
    target_std: float = 10.0
    llm_weight: float = DEFAULT_LLM_WEIGHT


@dataclass
class TeamResult:
    presentation_id: int
    team_id: int
    valid_reviews: int
    share: float | None  # T[p], sums to 1 over scored presentations
    relative: float | None  # share × number of scored presentations (1.0 = average)
    mean_total: float | None  # mean weighted total on the rubric scale
    criterion_means: dict[str, float]
    # The two views T blends, each as ×average over the teams it covers:
    # the class's C[p] and the AI's own n[AI, p]. None where that view is absent.
    class_relative: float | None = None
    llm_relative: float | None = None


@dataclass
class StudentResult:
    student_id: int
    team_id: int | None
    expected: int
    completed: int
    exempt: int
    participation_rate: float | None
    review_score: float | None  # R[s]
    adjusted_review_score: float | None  # R'[s] (after participation, imputation)
    team_share: float | None
    raw: float | None  # normalised raw (Σ = 1)
    normalized: float | None
    bonus: float
    final: float | None
    flags: list[str]
    shares: dict[int, float]  # n[s, p] — the student's own normalised scores


@dataclass
class RoundResult:
    teams: list[TeamResult]
    students: list[StudentResult]


def weighted_total(scores: dict[str, float], criteria: list[dict]) -> float | None:
    """Weighted mean of the counted criteria, normalised by the sum of their
    weights. Criteria with counts=False are remarks and never enter the score
    (older rubrics without the flag count every criterion)."""
    num = 0.0
    den = 0.0
    for c in criteria:
        if not c.get("counts", True):
            continue
        value = scores.get(c["key"])
        if value is None:
            return None
        weight = float(c.get("weight", 1.0))
        num += weight * float(value)
        den += weight
    if den <= 0:
        return None
    return num / den


def reviewer_shares(reviews: list[ScoredReview], criteria: list[dict]) -> dict[str, dict[int, float]]:
    """n[r, p]: each reviewer's totals normalised to sum to 1 over the round."""
    totals: dict[str, dict[int, float]] = defaultdict(dict)
    for r in reviews:
        total = weighted_total(r.scores, criteria)
        if total is not None:
            totals[r.reviewer][r.presentation_id] = total
    shares: dict[str, dict[int, float]] = {}
    for reviewer, by_pres in totals.items():
        s = sum(by_pres.values())
        if s > 0:
            shares[reviewer] = {p: t / s for p, t in by_pres.items()}
    return shares


def class_scores(
    shares: dict[str, dict[int, float]],
    presentation_ids: list[int],
    policy: str = "missing",
) -> dict[int, float | None]:
    """C[p]: the students' consensus. The AI grader's shares are left out."""
    received: dict[int, list[float]] = defaultdict(list)
    for reviewer, by_pres in shares.items():
        if reviewer == LLM_REVIEWER:
            continue
        k = len(by_pres)
        for p, n in by_pres.items():
            received[p].append(n * k if policy == "missing" else n)

    if policy == "missing":
        raw = {p: sum(v) / len(v) for p, v in received.items() if v}
    else:
        raw = {p: sum(v) for p, v in received.items() if v}
    total = sum(raw.values())
    return {p: (raw[p] / total if p in raw and total > 0 else None) for p in presentation_ids}


def anchor_to_llm(
    consensus: dict[int, float | None],
    llm: dict[int, float],
    weight: float,
) -> dict[int, float | None]:
    """T[p] = (1 − weight)·C[p] + weight·A[p] on the teams both views cover.

    A is the AI's shares rescaled to the class's mass on those teams, so the
    result still sums to 1 and a team the AI did not review keeps C[p]. A team
    only the AI reviewed stays unscored."""
    both = {p: c for p, c in consensus.items() if c is not None and p in llm}
    llm_total = sum(llm[p] for p in both)
    if weight <= 0 or llm_total <= 0:
        return dict(consensus)
    mass = sum(both.values())
    out = dict(consensus)
    for p, c in both.items():
        out[p] = (1 - weight) * c + weight * mass * llm[p] / llm_total
    return out


def team_scores(
    shares: dict[str, dict[int, float]],
    presentation_ids: list[int],
    policy: str = "missing",
    llm_weight: float = DEFAULT_LLM_WEIGHT,
) -> dict[int, float | None]:
    """T[p]: the class's view anchored by the AI grader's (module docstring, step 3)."""
    return anchor_to_llm(
        class_scores(shares, presentation_ids, policy), shares.get(LLM_REVIEWER, {}), llm_weight
    )


def _relative(values: dict[int, float | None]) -> dict[int, float]:
    """Shares as ×average over the teams they cover (1.0 = an average team)."""
    present = {p: v for p, v in values.items() if v is not None}
    total = sum(present.values())
    return {p: v * len(present) / total for p, v in present.items()} if total > 0 else {}


def _pop_stats(values: list[float]) -> tuple[float, float]:
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, math.sqrt(var)


def compute_round(inputs: RoundInputs) -> RoundResult:
    shares = reviewer_shares(inputs.reviews, inputs.criteria)
    pres_ids = sorted(inputs.presentations)
    consensus = class_scores(shares, pres_ids, inputs.missing_review_policy)
    llm = shares.get(LLM_REVIEWER, {})
    t = anchor_to_llm(consensus, llm, inputs.llm_weight)
    scored = [p for p in pres_ids if t[p] is not None]
    class_rel = _relative(consensus)
    llm_rel = _relative(dict(llm))

    reviews_by_pres: dict[int, list[ScoredReview]] = defaultdict(list)
    for r in inputs.reviews:
        reviews_by_pres[r.presentation_id].append(r)

    teams: list[TeamResult] = []
    for p in pres_ids:
        rs = reviews_by_pres.get(p, [])
        totals = [x for x in (weighted_total(r.scores, inputs.criteria) for r in rs) if x is not None]
        crit_means: dict[str, float] = {}
        for c in inputs.criteria:
            vals = [float(r.scores[c["key"]]) for r in rs if r.scores.get(c["key"]) is not None]
            if vals:
                crit_means[c["key"]] = sum(vals) / len(vals)
        teams.append(
            TeamResult(
                presentation_id=p,
                team_id=inputs.presentations[p],
                valid_reviews=len(rs),
                share=t[p],
                relative=(t[p] * len(scored)) if t[p] is not None else None,
                mean_total=(sum(totals) / len(totals)) if totals else None,
                criterion_means=crit_means,
                class_relative=class_rel.get(p),
                llm_relative=llm_rel.get(p),
            )
        )
    team_share_by_team = {inputs.presentations[p]: t[p] for p in pres_ids}

    # Participation per student
    expected: dict[int, int] = defaultdict(int)
    completed: dict[int, int] = defaultdict(int)
    exempt: dict[int, int] = defaultdict(int)
    reviewed_pairs = {(r.student_id, r.presentation_id) for r in inputs.reviews if r.student_id is not None}
    for ob in inputs.obligations:
        if ob.exempt:
            exempt[ob.student_id] += 1
            continue
        expected[ob.student_id] += 1
        if (ob.student_id, ob.presentation_id) in reviewed_pairs:
            completed[ob.student_id] += 1

    students: list[StudentResult] = []
    for sid in sorted(inputs.roster):
        own = shares.get(f"s:{sid}", {})
        flags: list[str] = []
        exp = expected.get(sid, 0)
        rate = (completed.get(sid, 0) / exp) if exp > 0 else None
        if own:
            review_score: float | None = sum((t[p] or 0.0) * n for p, n in own.items())
        elif exp > 0:
            review_score = 0.0
            flags.append("no_reviews")
        else:
            review_score = None
        adjusted = review_score
        if adjusted is not None and inputs.participation_factor and rate is not None:
            adjusted = adjusted * rate
        team_id = inputs.roster[sid]
        students.append(
            StudentResult(
                student_id=sid,
                team_id=team_id,
                expected=exp,
                completed=completed.get(sid, 0),
                exempt=exempt.get(sid, 0),
                participation_rate=rate,
                review_score=review_score,
                adjusted_review_score=adjusted,
                team_share=team_share_by_team.get(team_id) if team_id is not None else None,
                raw=None,
                normalized=None,
                bonus=float(inputs.bonuses.get(sid, 0.0)),
                final=None,
                flags=flags,
                shares=dict(own),
            )
        )

    # Fully exempt students with no reviews get the class-average review score
    # so their team score still counts; flagged for the instructor.
    defined = [s.adjusted_review_score for s in students if s.adjusted_review_score is not None]
    neutral = (sum(defined) / len(defined)) if defined else None
    for s in students:
        if s.adjusted_review_score is None and neutral is not None:
            s.adjusted_review_score = neutral
            s.flags.append("imputed_review_score")

    raws: dict[int, float] = {}
    for s in students:
        if s.team_id is None:
            s.flags.append("no_team")
            continue
        if s.team_share is None:
            s.flags.append("team_not_scored")
            continue
        if s.adjusted_review_score is None:
            continue
        raws[s.student_id] = s.adjusted_review_score * s.team_share

    raw_sum = sum(raws.values())
    if raws:
        normalised = {sid: (v / raw_sum if raw_sum > 0 else 0.0) for sid, v in raws.items()}
        mean, std = _pop_stats(list(normalised.values()))
        for s in students:
            if s.student_id not in normalised:
                continue
            s.raw = normalised[s.student_id]
            z = (s.raw - mean) / std if std > 1e-12 else 0.0
            s.normalized = min(100.0, max(0.0, inputs.target_mean + inputs.target_std * z))
            s.final = s.normalized + s.bonus

    return RoundResult(teams=teams, students=students)


# ---------------------------------------------------------------------------
# DB loading
# ---------------------------------------------------------------------------


def review_scores(review: PeerReview) -> dict[str, float]:
    try:
        data = json.loads(review.scores_json or "{}")
    except (TypeError, ValueError):
        return {}
    return {k: float(v) for k, v in data.items() if isinstance(v, (int, float))}


def load_round_inputs(db: Session, rnd: ReviewRound) -> RoundInputs:
    criteria = json.loads(rnd.rubric_version.criteria_json) if rnd.rubric_version else []
    presentations = {
        p.id: p.team_id for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id)).all()
    }
    # Test students take part on screen but never in the numbers.
    test_ids = set(
        db.scalars(select(Enrollment.student_id).where(Enrollment.course_id == rnd.course_id, Enrollment.is_test.is_(True)))
    )
    # Withdrawn students get no round score (their reviews of others still
    # count), unless they left after the round was released.
    left = {
        sid
        for sid, at in db.execute(
            select(Enrollment.student_id, Enrollment.withdrawn_at).where(
                Enrollment.course_id == rnd.course_id, Enrollment.withdrawn_at.is_not(None)
            )
        )
        if rnd.released_at is None or at < rnd.released_at
    }
    roster = {
        r.student_id: r.team_id
        for r in db.scalars(select(ReviewRoundRoster).where(ReviewRoundRoster.round_id == rnd.id)).all()
        if r.student_id not in test_ids and r.student_id not in left
    }
    reviews = [
        ScoredReview(
            reviewer=LLM_REVIEWER if r.reviewer_kind == "llm" else f"s:{r.reviewer_student_id}",
            student_id=r.reviewer_student_id,
            presentation_id=r.presentation_id,
            scores=review_scores(r),
        )
        for r in db.scalars(
            select(PeerReview).where(PeerReview.round_id == rnd.id, PeerReview.excluded.is_(False))
        ).all()
        if r.reviewer_student_id not in test_ids
    ]
    obligations = [
        Obligation(student_id=o.student_id, presentation_id=o.presentation_id, exempt=o.exempt)
        for o in db.scalars(select(ReviewObligation).where(ReviewObligation.round_id == rnd.id)).all()
        if o.student_id not in test_ids and o.student_id not in left
    ]
    bonuses: dict[int, float] = defaultdict(float)
    for o in db.scalars(
        select(StudentComponentOverride).where(
            StudentComponentOverride.course_id == rnd.course_id,
            StudentComponentOverride.component == bonus_component(rnd.number),
        )
    ).all():
        bonuses[o.student_id] += o.delta
    return RoundInputs(
        criteria=criteria,
        presentations=presentations,
        roster=roster,
        reviews=reviews,
        obligations=obligations,
        bonuses=dict(bonuses),
        missing_review_policy=rnd.missing_review_policy,
        participation_factor=rnd.participation_factor,
        target_mean=rnd.target_mean,
        target_std=rnd.target_std,
        llm_weight=rnd.llm_weight,
    )


def compute_round_scores(db: Session, rnd: ReviewRound) -> RoundResult:
    return compute_round(load_round_inputs(db, rnd))


def apply_round_to_gradebook(db: Session, rnd: ReviewRound) -> dict[str, int]:
    """Write each scored student's round final (normalised + bonus) as one
    override with component peer_round_<n>; the gradebook blends it into the
    round's gradebook_task (see scoring.peer_round_parts). Running it again
    updates those rows in place; students who no longer have a score lose
    theirs."""
    result = compute_round_scores(db, rnd)
    finals = {s.student_id: round(s.final, 2) for s in result.students if s.final is not None}
    component = score_component(rnd.number)
    reason = f"Peer review round {rnd.number}" + (f" ({rnd.title})" if rnd.title else "") + " final score"

    existing: dict[int, list[StudentComponentOverride]] = defaultdict(list)
    for o in db.scalars(
        select(StudentComponentOverride)
        .where(StudentComponentOverride.course_id == rnd.course_id, StudentComponentOverride.component == component)
        .order_by(StudentComponentOverride.id)
    ).all():
        existing[o.student_id].append(o)

    counts = {"created": 0, "updated": 0, "removed": 0}
    for sid, rows in existing.items():
        keep = rows[0] if sid in finals else None
        for o in rows:
            if o is not keep:
                db.delete(o)
                counts["removed"] += 1
        if keep is not None:
            keep.delta = finals[sid]
            keep.reason = reason
            counts["updated"] += 1
    for sid, final in finals.items():
        if sid not in existing:
            db.add(
                StudentComponentOverride(
                    course_id=rnd.course_id, student_id=sid, component=component, delta=final, reason=reason
                )
            )
            counts["created"] += 1
    db.commit()
    return counts


def remove_round_from_gradebook(db: Session, rnd: ReviewRound) -> int:
    rows = db.scalars(
        select(StudentComponentOverride).where(
            StudentComponentOverride.course_id == rnd.course_id,
            StudentComponentOverride.component == score_component(rnd.number),
        )
    ).all()
    for o in rows:
        db.delete(o)
    db.commit()
    return len(rows)
