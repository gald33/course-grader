"""Backfill rubric_dimension_scores from presentation_scores so the per-student
submission page renders the imported presentation / final_talk grades.

The gradebook reads presentation_scores directly, but the assignment page reads
rubric_dimension_scores keyed by (submission_id, component, dimension_key).
This mirrors each PresentationScore row into 5 RubricDimensionScore rows on
the student's PROJECT submission.

Usage:
    python backend/scripts/backfill_talk_rubric_from_presentation.py [--dry-run]
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "db.sqlite3"
BACKUP_PATH = REPO_ROOT / "data" / "db.sqlite3.bak-rubric-talk-backfill"
COURSE_ID = 1

STAGE_TO_COMPONENT = {
    "presentation": "presentation",
    "final": "final_talk",
}
DIMENSIONS = ["clarity", "complexity", "qa_answers", "elegance", "subjective_impression"]


def find_project_submission_id(cur: sqlite3.Cursor, course_id: int, student_id: int) -> int | None:
    cur.execute(
        """
        SELECT s.id
        FROM submissions s
        JOIN submission_members m ON m.submission_id = s.id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE s.course_id = ?
          AND m.student_id = ?
          AND a.assignment_type = 'PROJECT'
        ORDER BY a.workcode DESC, s.id DESC
        LIMIT 1
        """,
        (course_id, student_id),
    )
    row = cur.fetchone()
    return row[0] if row else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run:
        shutil.copyfile(DB_PATH, BACKUP_PATH)
        print(f"backup -> {BACKUP_PATH}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    cur.execute(
        """
        SELECT ps.id, ps.student_id, ps.stage,
               ps.clarity, ps.complexity, ps.qa_answers, ps.elegance, ps.subjective_impression,
               st.national_id, st.name
        FROM presentation_scores ps
        JOIN students st ON st.id = ps.student_id
        WHERE ps.course_id = ?
        ORDER BY ps.stage, st.national_id
        """,
        (COURSE_ID,),
    )
    sources = cur.fetchall()
    print(f"presentation_scores rows for course {COURSE_ID}: {len(sources)}")

    inserted = 0
    skipped_unmapped_stage = 0
    skipped_no_submission = 0
    already_present = 0
    seen_submission_components: set[tuple[int, str]] = set()

    for src in sources:
        component = STAGE_TO_COMPONENT.get(src["stage"])
        if component is None:
            print(
                f"  SKIP student={src['national_id']} ({src['name']}): unknown stage={src['stage']!r}",
                file=sys.stderr,
            )
            skipped_unmapped_stage += 1
            continue

        sub_id = find_project_submission_id(cur, COURSE_ID, src["student_id"])
        if sub_id is None:
            print(
                f"  SKIP student={src['national_id']} ({src['name']}): no PROJECT submission",
                file=sys.stderr,
            )
            skipped_no_submission += 1
            continue

        key = (sub_id, component)
        first_for_pair = key not in seen_submission_components
        seen_submission_components.add(key)

        for dim in DIMENSIONS:
            raw = float(src[dim])
            cur.execute(
                """
                INSERT OR IGNORE INTO rubric_dimension_scores
                    (submission_id, component, dimension_key, raw_score, adjusted_score, approved)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (sub_id, component, dim, raw, raw),
            )
            if cur.rowcount == 1:
                inserted += 1
            else:
                already_present += 1

        marker = "first" if first_for_pair else "shared-group"
        print(
            f"  {component} sub={sub_id} student={src['national_id']} ({src['name']}) [{marker}]"
        )

    if args.dry_run:
        conn.rollback()
        print(
            f"\n[DRY RUN] would_insert={inserted} already_present={already_present} "
            f"skipped_no_submission={skipped_no_submission} skipped_unmapped_stage={skipped_unmapped_stage}"
        )
    else:
        conn.commit()
        print(
            f"\ninserted={inserted} already_present={already_present} "
            f"skipped_no_submission={skipped_no_submission} skipped_unmapped_stage={skipped_unmapped_stage}"
        )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
