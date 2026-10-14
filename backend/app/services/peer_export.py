"""XLSX export for one peer-review round.

Sheets: team scores, student scores, participation (per-student counts), and
individual reviews. Reviews carry a per-export random pseudonym instead of
the reviewer's identity, so the file can't be used to unmask reviewers.
"""

from __future__ import annotations

import json
import secrets
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import Course, PeerReview, Presentation, ReviewRound, Team
from app.services.paths import export_path
from app.services.peer_scoring import review_scores, weighted_total


def _r(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def _header(ws, cols: list[str]) -> None:
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)


def export_round_xlsx(db: Session, rnd: ReviewRound, scores: dict) -> Path:
    course = db.get(Course, rnd.course_id)
    criteria = scores["criteria"]
    wb = Workbook()

    ws = wb.active
    ws.title = "Team scores"
    _header(
        ws,
        ["Team", "Project", "Session", "Valid reviews", "Team score (share)", "Relative (1 = avg)", "Mean total"]
        + [c["label"] for c in criteria],
    )
    for t in scores["teams"]:
        ws.append(
            [
                t["team_name"],
                t["project_title"],
                t["session_number"],
                t["valid_reviews"],
                _r(t["share"]) if t["share"] is not None else "not yet scored",
                _r(t["relative"], 3),
                _r(t["mean_total"], 2),
            ]
            + [_r(t["criterion_means"].get(c["key"]), 2) for c in criteria]
        )

    ws = wb.create_sheet("Student scores")
    _header(
        ws,
        [
            "National ID",
            "Name",
            "Team",
            "Review score",
            "Participation rate",
            "Adjusted review score",
            "Team score (share)",
            "Raw (normalised)",
            "Normalised score",
            "Bonus",
            "Final",
            "Flags",
        ],
    )
    for s in scores["students"]:
        ws.append(
            [
                s["national_id"],
                s["name"],
                s["team_name"],
                _r(s["review_score"], 6),
                _r(s["participation_rate"], 3),
                _r(s["adjusted_review_score"], 6),
                _r(s["team_share"]),
                _r(s["raw"], 6),
                _r(s["normalized"], 2),
                s["bonus"],
                _r(s["final"], 2),
                ", ".join(s["flags"]),
            ]
        )

    ws = wb.create_sheet("Participation")
    _header(ws, ["National ID", "Name", "Team", "Expected reviews", "Completed", "Exempt"])
    for s in scores["students"]:
        ws.append([s["national_id"], s["name"], s["team_name"], s["expected"], s["completed"], s["exempt"]])

    ws = wb.create_sheet("Reviews (anonymised)")
    teams = {t.id: t.name for t in db.scalars(select(Team).where(Team.course_id == rnd.course_id))}
    presentations = {p.id: p for p in db.scalars(select(Presentation).where(Presentation.round_id == rnd.id))}
    prompts = json.loads(rnd.rubric_version.prompts_json) if rnd.rubric_version else []
    _header(
        ws,
        ["Reviewer", "Presenting team", "Weighted total"]
        + [c["label"] for c in criteria]
        + [p["label"] for p in prompts]
        + ["Excluded", "Exclusion reason"],
    )
    reviews = list(db.scalars(select(PeerReview).where(PeerReview.round_id == rnd.id)))
    student_ids = sorted({r.reviewer_student_id for r in reviews if r.reviewer_student_id is not None})
    secrets.SystemRandom().shuffle(student_ids)
    pseudonym = {sid: f"Reviewer {i + 1:02d}" for i, sid in enumerate(student_ids)}
    rows = []
    for r in reviews:
        p = presentations.get(r.presentation_id)
        sc = review_scores(r)
        responses = json.loads(r.responses_json or "{}")
        rows.append(
            [
                "LLM" if r.reviewer_kind == "llm" else pseudonym[r.reviewer_student_id],
                teams.get(p.team_id, "?") if p else "?",
                _r(weighted_total(sc, criteria), 3),
            ]
            + [sc.get(c["key"]) for c in criteria]
            + [responses.get(pr["key"], "") for pr in prompts]
            + ["yes" if r.excluded else "", r.exclusion_reason if r.excluded else ""]
        )
    rows.sort(key=lambda row: (row[1], row[0]))
    for row in rows:
        ws.append(row)

    folder = f"{course.code}_{course.year}_{course.semester}" if course else f"course_{rnd.course_id}"
    suffix = "" if rnd.counts_toward_grade else "_practice_not_graded"
    out = export_path(folder, f"peer_review_round_{rnd.number}{suffix}.xlsx")
    wb.save(out)
    return out
