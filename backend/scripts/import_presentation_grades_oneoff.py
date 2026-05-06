"""One-off ingest of initial-stage presentation grades from a Google Sheet CSV export.

Parses the block-per-group layout used in the 2026/A 'הצגות' sheet, broadcasts a
single grade per criterion to all members of the group, resolves two ID-less
groups by hard-coded name mapping, and upserts PresentationScore rows.

Usage:
    python backend/scripts/import_presentation_grades_oneoff.py /tmp/preso_grades.csv [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DB_PATH = REPO_ROOT / "data" / "db.sqlite3"
COURSE_ID = 1
STAGE = "initial"

CRITERIA_MAP = {
    "בהירות": "clarity",
    "מורכבות": "complexity",
    "תשובה על שאלות": "qa_answers",
    "תשובות על שאלות": "qa_answers",
    "אלגנט": "elegance",
    "אלגנטיות": "elegance",
    "הערכה כללית": "subjective_impression",
}
IGNORED_CRITERIA = {"נתונים"}
SCORE_COLUMNS = ["clarity", "complexity", "qa_answers", "elegance", "subjective_impression"]

# 0-indexed row number of the header → name → resolved national_id.
# Resolved during planning by querying the students table.
NAME_TO_ID_BY_BLOCK = {
    9: {
        "דביר": "322308271",
        "עדן": "207789942",
    },
    30: {
        "אלכסדרה": "212930523",
        "טל בן דוד": "207734450",
        "אלעד מויסה": "211627864",
    },
}


def normalize_id(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def maybe_student_id(value) -> str | None:
    sid = normalize_id(value)
    return sid if len(sid) >= 7 else None


def coerce_score_to_0_5(value) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 5:
        numeric = numeric / 20.0
    return max(0.0, min(5.0, numeric))


def normalize_text(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def find_criterion_column(label: str) -> str | None:
    if not label:
        return None
    if any(ic in label for ic in IGNORED_CRITERIA):
        return None
    norm = normalize_text(label)
    for raw_key, mapped in CRITERIA_MAP.items():
        if normalize_text(raw_key) in norm:
            return mapped
    return None


def is_blank_row(row: list[str]) -> bool:
    return all((cell is None or str(cell).strip() == "") for cell in row)


def is_criterion_row(row: list[str]) -> bool:
    for cell in row[:5]:
        if cell is None or str(cell).strip() == "":
            continue
        text = str(cell).strip()
        if find_criterion_column(text) is not None:
            return True
        if any(ic in text for ic in IGNORED_CRITERIA):
            return True
        return False
    return False


def parse_blocks(rows: list[list[str]]) -> list[dict]:
    blocks: list[dict] = []
    cur_header: list[tuple[int, list[str]]] = []
    cur_criteria: list[tuple[int, list[str]]] = []

    def flush():
        nonlocal cur_header, cur_criteria
        if cur_header or cur_criteria:
            blocks.append({"header": cur_header[:], "criteria": cur_criteria[:]})
            cur_header = []
            cur_criteria = []

    for idx, row in enumerate(rows):
        if is_blank_row(row):
            if cur_criteria:
                flush()
            continue
        if is_criterion_row(row):
            cur_criteria.append((idx, row))
        else:
            if cur_criteria:
                flush()
            cur_header.append((idx, row))

    flush()
    return blocks


def block_label(block: dict) -> str:
    parts: list[str] = []
    for _idx, row in block["header"]:
        for cell in row:
            if cell and str(cell).strip():
                parts.append(str(cell).strip())
        if len(parts) >= 4:
            break
    return " | ".join(parts[:5])


def extract_ids_from_header(block: dict) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for _idx, row in block["header"]:
        for cell in row:
            sid = maybe_student_id(cell)
            if sid and sid not in seen:
                seen.add(sid)
                ids.append(sid)
    return ids


def resolve_ids_by_name(block: dict) -> list[str]:
    if not block["header"]:
        return []
    first_idx = block["header"][0][0]
    mapping = NAME_TO_ID_BY_BLOCK.get(first_idx)
    if not mapping:
        return []
    found: list[str] = []
    for _idx, row in block["header"]:
        for cell in row:
            if cell is None:
                continue
            text = str(cell).strip()
            if not text:
                continue
            for name, sid in mapping.items():
                if name in text and sid not in found:
                    found.append(sid)
    return found


def extract_grades(block: dict) -> dict[str, float]:
    grades: dict[str, float] = {}
    for _idx, row in block["criteria"]:
        label = ""
        for cell in row[:5]:
            if cell and str(cell).strip():
                label = str(cell).strip()
                break
        if not label:
            continue
        column = find_criterion_column(label)
        if column is None:
            continue
        numerics: list[float] = []
        for cell in row:
            if cell is None or str(cell).strip() == "":
                continue
            text = str(cell).strip()
            if text == label:
                continue
            try:
                numerics.append(float(text))
            except ValueError:
                continue
        if not numerics:
            continue
        if len(numerics) > 1:
            print(
                f"  WARN '{label}': multiple numeric values {numerics}; using first",
                file=sys.stderr,
            )
        score = coerce_score_to_0_5(numerics[0])
        if score is not None:
            grades[column] = score
    return grades


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv_path", type=str)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.reader(f))

    blocks = parse_blocks(rows)
    print(f"Detected {len(blocks)} blocks in {csv_path}")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON")

    cur.execute(
        """
        SELECT s.national_id, s.id AS student_id, s.name
        FROM students s
        JOIN enrollments e ON e.student_id = s.id
        WHERE e.course_id = ?
        """,
        (COURSE_ID,),
    )
    nid_to_student = {r["national_id"]: (r["student_id"], r["name"]) for r in cur.fetchall()}

    inserts = updates = skipped = no_ids = 0

    for i, block in enumerate(blocks, start=1):
        ids = extract_ids_from_header(block)
        source = "id-row"
        if not ids:
            ids = resolve_ids_by_name(block)
            source = "name-resolved"
        if not ids:
            print(f"[block {i}] NO IDs and no name match: {block_label(block)!r}", file=sys.stderr)
            no_ids += 1
            continue

        grades = extract_grades(block)
        if not grades:
            print(f"[block {i}] no grades extracted for {block_label(block)!r}", file=sys.stderr)
            continue

        label = block_label(block)
        print(f"\n[block {i}] {label[:80]}")
        print(f"   source={source} ids={ids}")
        print(f"   grades={grades}")

        for sid in ids:
            if sid not in nid_to_student:
                print(f"   SKIP {sid} (not enrolled in course {COURSE_ID})", file=sys.stderr)
                skipped += 1
                continue
            student_id, student_name = nid_to_student[sid]
            values = {col: grades.get(col, 0.0) for col in SCORE_COLUMNS}

            cur.execute(
                "SELECT id FROM presentation_scores WHERE course_id=? AND student_id=? AND stage=?",
                (COURSE_ID, student_id, STAGE),
            )
            existing = cur.fetchone()

            if existing:
                if not args.dry_run:
                    set_clause = ", ".join(f"{c}=?" for c in SCORE_COLUMNS)
                    cur.execute(
                        f"UPDATE presentation_scores SET {set_clause} WHERE id=?",
                        (*[values[c] for c in SCORE_COLUMNS], existing["id"]),
                    )
                updates += 1
                action = "UPDATE"
            else:
                if not args.dry_run:
                    cols_csv = ", ".join(SCORE_COLUMNS)
                    placeholders = ", ".join("?" for _ in SCORE_COLUMNS)
                    cur.execute(
                        f"INSERT INTO presentation_scores "
                        f"(course_id, student_id, stage, {cols_csv}) "
                        f"VALUES (?, ?, ?, {placeholders})",
                        (COURSE_ID, student_id, STAGE, *[values[c] for c in SCORE_COLUMNS]),
                    )
                inserts += 1
                action = "INSERT"

            print(f"   {action} sid={sid} {student_name}: {values}")

    if args.dry_run:
        conn.rollback()
        print(f"\n[DRY RUN] would_insert={inserts} would_update={updates} skipped={skipped} blocks_without_ids={no_ids}")
    else:
        conn.commit()
        print(f"\nimported_rows={inserts} updated={updates} skipped={skipped} blocks_without_ids={no_ids}")
    conn.close()


if __name__ == "__main__":
    main()
