from __future__ import annotations

import math

import pytest

from app.services.peer_scoring import (
    LLM_REVIEWER,
    Obligation,
    RoundInputs,
    ScoredReview,
    compute_round,
    reviewer_shares,
    team_scores,
    weighted_total,
)

CRITERIA = [
    {"key": "a", "weight": 1.0},
    {"key": "b", "weight": 3.0},
]


def _rev(student: int | None, pres: int, a: int, b: int | None = None) -> ScoredReview:
    return ScoredReview(
        reviewer=LLM_REVIEWER if student is None else f"s:{student}",
        student_id=student,
        presentation_id=pres,
        scores={"a": a, "b": a if b is None else b},
    )


def test_weighted_total_normalises_by_sum_of_weights():
    assert weighted_total({"a": 1, "b": 5}, CRITERIA) == pytest.approx((1 * 1 + 3 * 5) / 4)
    assert weighted_total({"a": 3}, CRITERIA) is None  # incomplete review has no total


def test_each_reviewer_shares_sum_to_one():
    shares = reviewer_shares([_rev(1, 10, 2), _rev(1, 11, 4), _rev(2, 10, 5)], CRITERIA)
    assert shares["s:1"] == pytest.approx({10: 2 / 6, 11: 4 / 6})
    assert shares["s:2"] == pytest.approx({10: 1.0})


def test_zero_policy_is_the_literal_share_of_mass():
    shares = {"r1": {1: 0.6, 2: 0.4}, "r2": {1: 0.5, 2: 0.5}}
    t = team_scores(shares, [1, 2], policy="zero")
    assert t[1] == pytest.approx(0.55)
    assert t[2] == pytest.approx(0.45)


def test_policies_agree_under_full_symmetric_coverage():
    shares = {"r1": {1: 0.6, 2: 0.4}, "r2": {1: 0.5, 2: 0.5}, "r3": {1: 0.2, 2: 0.8}}
    zero = team_scores(shares, [1, 2], policy="zero")
    missing = team_scores(shares, [1, 2], policy="missing")
    assert zero == pytest.approx(missing)


def test_missing_policy_does_not_treat_a_missing_review_as_zero():
    # Every reviewer rates presentations 1 and 2 the same; presentation 2 gets
    # one reviewer fewer (absence, larger team). Under "missing" both teams end
    # up equal; under the literal "zero" policy team 2 is penalised.
    shares = {
        "r1": {1: 0.5, 2: 0.5},
        "r2": {1: 0.5, 2: 0.5},
        "r3": {1: 1.0},
    }
    missing = team_scores(shares, [1, 2], policy="missing")
    zero = team_scores(shares, [1, 2], policy="zero")
    assert missing[1] == pytest.approx(missing[2])
    assert zero[2] < zero[1]


def test_presentation_without_valid_reviews_is_not_yet_scored():
    shares = {"r1": {1: 0.5, 2: 0.5}}
    t = team_scores(shares, [1, 2, 3])
    assert t[3] is None
    assert t[1] + t[2] == pytest.approx(1.0)


def _class_inputs(**overrides) -> RoundInputs:
    # Teams 100, 200, 300 present as presentations 1, 2, 3. Two students per
    # team; each reviews the other two teams.
    roster = {11: 100, 12: 100, 21: 200, 22: 200, 31: 300, 32: 300}
    presentations = {1: 100, 2: 200, 3: 300}
    team_of_pres = {1: 100, 2: 200, 3: 300}
    obligations = [
        Obligation(s, p, False) for s, team in roster.items() for p in presentations if team_of_pres[p] != team
    ]
    reviews = [
        _rev(11, 2, 5), _rev(11, 3, 3),
        _rev(12, 2, 4), _rev(12, 3, 2),
        _rev(21, 1, 4), _rev(21, 3, 2),
        _rev(22, 1, 5), _rev(22, 3, 3),
        _rev(31, 1, 3), _rev(31, 2, 5),
        _rev(32, 1, 4), _rev(32, 2, 4),
    ]
    base = dict(
        criteria=CRITERIA,
        presentations=presentations,
        roster=roster,
        reviews=reviews,
        obligations=obligations,
        target_mean=80.0,
        target_std=10.0,
    )
    base.update(overrides)
    return RoundInputs(**base)


def test_review_score_is_dot_product_of_team_scores_and_own_shares():
    inputs = _class_inputs()
    result = compute_round(inputs)
    t = {team.presentation_id: team.share for team in result.teams}
    shares = reviewer_shares(inputs.reviews, CRITERIA)
    s11 = next(s for s in result.students if s.student_id == 11)
    expected = t[2] * shares["s:11"][2] + t[3] * shares["s:11"][3]
    assert s11.review_score == pytest.approx(expected)
    assert s11.participation_rate == 1.0
    assert s11.team_share == pytest.approx(t[1])
    assert sum(team.share for team in result.teams) == pytest.approx(1.0)


def test_raw_scores_sum_to_one_and_normalised_scores_hit_target_distribution():
    result = compute_round(_class_inputs())
    raws = [s.raw for s in result.students]
    assert sum(raws) == pytest.approx(1.0)
    finals = [s.normalized for s in result.students]
    mean = sum(finals) / len(finals)
    std = math.sqrt(sum((f - mean) ** 2 for f in finals) / len(finals))
    assert mean == pytest.approx(80.0)
    assert std == pytest.approx(10.0)


def test_bonus_is_added_after_normalisation():
    result = compute_round(_class_inputs(bonuses={11: 5.0}))
    s11 = next(s for s in result.students if s.student_id == 11)
    assert s11.final == pytest.approx(s11.normalized + 5.0)


def test_missing_reviews_lower_only_the_reviewer_and_never_zero_the_team():
    inputs = _class_inputs()
    # Student 12 submits nothing.
    inputs.reviews = [r for r in inputs.reviews if r.student_id != 12]
    result = compute_round(inputs)
    s12 = next(s for s in result.students if s.student_id == 12)
    assert s12.completed == 0 and s12.expected == 2
    assert s12.review_score == 0.0 and "no_reviews" in s12.flags
    assert s12.normalized == min(s.normalized for s in result.students)
    # Teams 2 and 3 lost a reviewer but are still scored from the reviews they got.
    assert all(team.share is not None for team in result.teams)


def test_participation_factor_scales_review_score_and_exemptions_reduce_expected():
    inputs = _class_inputs()
    inputs.reviews = [r for r in inputs.reviews if not (r.student_id == 11 and r.presentation_id == 3)]
    with_factor = compute_round(inputs)
    s11 = next(s for s in with_factor.students if s.student_id == 11)
    assert s11.participation_rate == pytest.approx(0.5)
    assert s11.adjusted_review_score == pytest.approx(s11.review_score * 0.5)

    inputs.obligations = [
        Obligation(o.student_id, o.presentation_id, o.student_id == 11 and o.presentation_id == 3)
        for o in inputs.obligations
    ]
    exempted = compute_round(inputs)
    s11 = next(s for s in exempted.students if s.student_id == 11)
    assert (s11.expected, s11.completed, s11.exempt) == (1, 1, 1)
    assert s11.participation_rate == 1.0


def test_fully_exempt_student_without_reviews_gets_class_average_review_score():
    inputs = _class_inputs()
    inputs.reviews = [r for r in inputs.reviews if r.student_id != 12]
    inputs.obligations = [Obligation(o.student_id, o.presentation_id, o.student_id == 12) for o in inputs.obligations]
    result = compute_round(inputs)
    s12 = next(s for s in result.students if s.student_id == 12)
    others = [s.adjusted_review_score for s in result.students if s.student_id != 12]
    assert "imputed_review_score" in s12.flags
    assert s12.adjusted_review_score == pytest.approx(sum(others) / len(others))
    assert s12.normalized is not None


def _with_llm(llm_totals: dict[int, int], **overrides) -> RoundInputs:
    """The class round plus an AI review of each presentation in llm_totals."""
    inputs = _class_inputs(**overrides)
    inputs.reviews = inputs.reviews + [_rev(None, p, total) for p, total in llm_totals.items()]
    return inputs


def _shares(result) -> dict[int, float | None]:
    return {t.presentation_id: t.share for t in result.teams}


def test_llm_is_a_third_of_each_team_score_and_has_no_student_score():
    class_only = _shares(compute_round(_class_inputs()))
    result = compute_round(_with_llm({1: 5, 2: 1, 3: 4}))
    llm = {1: 5 / 10, 2: 1 / 10, 3: 4 / 10}
    for team in result.teams:
        p = team.presentation_id
        assert team.share == pytest.approx(2 / 3 * class_only[p] + 1 / 3 * llm[p])
        assert team.llm_relative == pytest.approx(llm[p] * 3)
        assert team.class_relative == pytest.approx(class_only[p] * 3)
        assert team.valid_reviews == 5  # 4 students + the AI
    assert {s.student_id for s in result.students} == set(_class_inputs().roster)


def test_llm_weight_zero_leaves_the_class_view_alone():
    class_only = compute_round(_class_inputs())
    ignored = compute_round(_with_llm({1: 5, 2: 1, 3: 4}, llm_weight=0.0))
    assert list(_shares(ignored).values()) == pytest.approx(list(_shares(class_only).values()))
    assert [s.final for s in ignored.students] == pytest.approx([s.final for s in class_only.students])


def test_team_the_llm_did_not_review_keeps_the_class_view():
    class_only = _shares(compute_round(_class_inputs()))
    t = _shares(compute_round(_with_llm({1: 5, 2: 1})))
    assert t[3] == pytest.approx(class_only[3])
    assert sum(t.values()) == pytest.approx(1.0)
    # On the two teams it reviewed, the AI only moves mass from team 2 to team 1.
    assert t[1] > class_only[1] and t[2] < class_only[2]
    assert t[1] + t[2] == pytest.approx(class_only[1] + class_only[2])


def test_llm_alone_does_not_score_a_team():
    inputs = _with_llm({1: 5, 2: 1, 3: 4})
    inputs.reviews = [r for r in inputs.reviews if r.student_id is None or r.presentation_id != 3]
    result = compute_round(inputs)
    team3 = next(t for t in result.teams if t.presentation_id == 3)
    assert team3.share is None and team3.class_relative is None
    assert team3.llm_relative is not None  # the instructor still sees the AI's view
    assert {s.student_id for s in result.students if "team_not_scored" in s.flags} == {31, 32}


def test_llm_anchors_review_scores_toward_reviewers_who_agree_with_it():
    # Student 31 rated team 2 above team 1; student 32 rated them level. An AI
    # that rates team 1 far above team 2 widens 32's lead over 31.
    def lead(result) -> float:
        r = {s.student_id: s.review_score for s in result.students}
        return r[32] - r[31]

    assert lead(compute_round(_with_llm({1: 5, 2: 1, 3: 3}))) > lead(compute_round(_class_inputs()))


def test_student_without_team_or_unscored_team_is_flagged_not_scored():
    inputs = _class_inputs()
    inputs.roster = {**inputs.roster, 41: None}
    result = compute_round(inputs)
    s41 = next(s for s in result.students if s.student_id == 41)
    assert s41.normalized is None and "no_team" in s41.flags
