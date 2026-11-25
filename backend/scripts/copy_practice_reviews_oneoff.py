"""One-off, 2026-11-25: put course 11126's misplaced reviews into the graded rounds.

The practice round (id 31) stayed open while round 1's presentations were never
opened for reviews, so students reviewed rounds 1 and 2 in the practice round.
Confirmed with the instructor on 2026-11-25:

- practice reviews written 2026-11-01 .. 2026-11-24 (UTC): 60, round 1 (id 11)
- practice reviews written 2026-11-25: 17, round 2 (id 12); a student who has
  since reviewed that team in round 2 keeps that review instead

Copies, never moves (services/peer_review_repair.py). Dry run by default: it
prints what it would do and rolls back. With --commit it writes, and only if
the number of practice reviews in each range is still exactly as confirmed.

From the repo root, after `make migrate-hosted` (this uses the app's models):

    set -a; . ./.env; set +a; cd backend && DATABASE_URL="$SUPABASE_POOL_URL" python scripts/copy_practice_reviews_oneoff.py
    set -a; . ./.env; set +a; cd backend && DATABASE_URL="$SUPABASE_POOL_URL" python scripts/copy_practice_reviews_oneoff.py --commit
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.entities import Course, ReviewRound  # noqa: E402
from app.services.peer_review_repair import copy_reviews  # noqa: E402

COURSE_ID = 3
PRACTICE_ROUND_ID = 31
# (target round id, its number, written from, written before, practice reviews confirmed in that range)
BATCHES = [
    (11, 1, datetime(2026, 11, 1), datetime(2026, 11, 25), 60),
    (12, 2, datetime(2026, 11, 25), datetime(2026, 11, 26), 17),
]


def main(commit: bool) -> int:
    with SessionLocal() as db:
        course = db.get(Course, COURSE_ID)
        practice = db.get(ReviewRound, PRACTICE_ROUND_ID)
        if course is None or practice is None or practice.course_id != COURSE_ID or practice.counts_toward_grade:
            print("Round 31 is not this course's practice round; nothing changed.")
            return 1
        print(f"Course {course.code} {course.name}: copying from '{practice.title}'")
        mapping = []
        for target_id, number, start, end, confirmed in BATCHES:
            target = db.get(ReviewRound, target_id)
            if target is None or target.course_id != COURSE_ID or target.number != number or not target.counts_toward_grade:
                print(f"Round id {target_id} is not graded round {number} of this course; nothing changed.")
                db.rollback()
                return 1
            result = copy_reviews(
                db, from_round_id=PRACTICE_ROUND_ID, to_round_id=target_id, created_from=start, created_to=end
            )
            print(
                f"  round {number} '{target.title}': {result.candidates} practice reviews in range "
                f"(confirmed {confirmed}); copy {len(result.copied)} ({result.with_obligation} match a review "
                f"assignment); already reviewed in round {number}: {result.already_reviewed}; "
                f"test students: {result.test_students}; team not in round: {result.no_target}"
            )
            if result.candidates != confirmed:
                print("  The practice reviews in this range changed since they were counted; nothing changed.")
                db.rollback()
                return 1
            mapping += [{"round": number, "from_review": s, "to_review": t} for s, t in result.copied]
        if not commit:
            db.rollback()
            print(f"Dry run: {len(mapping)} copies would be written. Nothing changed. Run again with --commit.")
            return 0
        db.commit()
        out = ROOT.parent / "data" / "exports" / f"copied_practice_reviews_{datetime.now():%Y%m%d_%H%M%S}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(mapping, indent=1))
        print(f"Committed {len(mapping)} copies. Review id mapping: {out}")
        return 0


if __name__ == "__main__":
    sys.exit(main("--commit" in sys.argv))
