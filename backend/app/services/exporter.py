from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from bidi.algorithm import get_display
from fpdf import FPDF
from sqlalchemy.orm import Session

from app.models.entities import Course
from app.services.paths import export_path
from app.services.scoring import compute_gradebook_rows
from app.utils.text import sanitize_filename


@dataclass
class ExportResult:
    csv_path: str
    report_dir: str
    report_count: int


def _hebrew(text: str) -> str:
    return get_display(text)


def export_gradebook_csv(db: Session, course_id: int) -> str:
    course = db.get(Course, course_id)
    if not course:
        raise ValueError("Course not found")

    rows = compute_gradebook_rows(db, course_id)
    out_path = export_path(f"{course.code}_{course.year}_{course.semester}", "gradebook.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if rows:
        headers = list(rows[0].keys())
    else:
        headers = [
            "student_id",
            "national_id",
            "name",
            "attendance_percent",
            "attendance_score",
            "hw1",
            "hw2",
            "project_code",
            "project_report",
            "initial_talk",
            "final_talk",
            "project_base",
            "bonus_points",
            "project_with_bonus",
            "final",
            "overrides",
        ]

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    return str(out_path)


def _name_parts(name: str) -> tuple[str, str]:
    parts = [p for p in name.strip().split() if p]
    if not parts:
        return "Unknown", "Student"
    if len(parts) == 1:
        return parts[0], ""
    return parts[-1], " ".join(parts[:-1])


def export_student_reports_hebrew(db: Session, course_id: int) -> ExportResult:
    course = db.get(Course, course_id)
    if not course:
        raise ValueError("Course not found")

    rows = compute_gradebook_rows(db, course_id)
    course_dir_name = f"{course.code}_{course.year}_{course.semester}"
    report_dir = export_path(course_dir_name, "student_reports")
    report_dir.mkdir(parents=True, exist_ok=True)

    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    for row in rows:
        national_id = row["national_id"]
        last, first = _name_parts(row["name"])
        filename = sanitize_filename(f"{national_id}_{last}_{first}.pdf") + ".pdf"
        path = report_dir / filename

        pdf = FPDF()
        pdf.add_page()
        pdf.add_font("DejaVu", "", font_path)
        pdf.set_font("DejaVu", size=14)

        lines = [
            f"דו\"ח ציונים לסטודנט/ית",
            f"קורס: {course.name} ({course.code}) {course.year} {course.semester}",
            f"שם: {row['name']}",
            f"תעודת זהות: {national_id}",
            f"נוכחות: {row['attendance_score']}",
            f"תרגיל 1: {row['hw1']}",
            f"תרגיל 2: {row['hw2']}",
            f"קוד פרויקט: {row['project_code']}",
            f"דו\"ח פרויקט: {row['project_report']}",
            f"מצגת התחלתית: {row['initial_talk']}",
            f"מצגת סופית: {row['final_talk']}",
            f"בונוס: {row['bonus_points']}",
            f"ציון סופי: {row['final']}",
        ]

        for line in lines:
            pdf.cell(0, 10, _hebrew(line), new_x="LMARGIN", new_y="NEXT", align="R")

        pdf.output(str(path))

    csv_path = export_gradebook_csv(db, course_id)
    return ExportResult(csv_path=csv_path, report_dir=str(report_dir), report_count=len(rows))
