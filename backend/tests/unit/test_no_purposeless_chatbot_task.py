"""Operator rule, 2026-11-03: no chatbot task without a reason. The exit
checks used to end with "ask the chatbot to challenge your explanation";
that is gone from every seed and every built lesson of the 42052 plan, and
the rule is recorded in the handoff's START-HERE.txt."""

from __future__ import annotations

import json
from pathlib import Path

from app.lessons import CONTENT_DIR, load_fixture, load_plan

REPO = Path(__file__).resolve().parents[3]
SEEDS = REPO / "content" / "course-42052"


def _plan_fixtures() -> list[str]:
    return [k for s in load_plan("42052")["sessions"] for k in [s["fixture_key"], *s["part_fixture_keys"]]]


def test_no_exit_check_asks_the_chatbot_to_challenge_the_answer():
    built = [json.dumps(load_fixture(k), ensure_ascii=False) for k in _plan_fixtures()]
    built += [p.read_text(encoding="utf-8") for p in sorted((CONTENT_DIR / "course-42052").glob("lesson-*.json"))]
    seeds = [p.read_text(encoding="utf-8") for p in sorted((SEEDS / "lessons").glob("lesson-*.json"))] if SEEDS.is_dir() else []
    assert len(built) >= 14
    for text in built + seeds:
        assert "לאתגר את ההסבר" not in text  # the exit checks' add-on, in any form
        assert "ואז אפשר לבקש מהצ׳טבוט" not in text
    for key in _plan_fixtures():
        exit_checks = [q for q in load_fixture(key)["questions"].values() if q["key"].endswith("-exit")]
        assert exit_checks, key
        # No exit check sends the student to the chatbot. Lesson 1's may name it
        # (how did you check the stall's profit rather than trust what the
        # chatbot wrote?); test_exit_checks_concrete pins every prompt verbatim.
        for q in exit_checks:
            for ask in ("בקשו מהצ׳טבוט", "לבקש מהצ׳טבוט", "שאלו את הצ׳טבוט", "לשאול את הצ׳טבוט", "היעזרו בצ׳טבוט"):
                assert ask not in q["prompt"], key
            assert "צ׳טבוט" not in q["prompt"] or key == "42052-lesson-01", key


def test_the_rule_is_recorded_beside_the_seeds():
    if SEEDS.is_dir():
        note = (SEEDS / "START-HERE.txt").read_text(encoding="utf-8")
        assert "2026-11-03" in note and "no chatbot task without a reason" in note
