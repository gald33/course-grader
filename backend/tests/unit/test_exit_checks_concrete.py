"""Operator rule, 2026-11-03: each lesson's exit question asks something
concrete about that lesson. The old generic prompt ("explain in your own words
what you tried, what you saw and what is still unknown") left students unsure
what was wanted; it is gone from every seed and every built lesson of the 42052
plan. The section is titled "לסיום: במילים שלכם" with one line under it saying
the answer is short and ungraded. The question ids are unchanged (free text, no
answer keys)."""

from __future__ import annotations

import json
from pathlib import Path

from app.lessons import CONTENT_DIR, course_plan, load_fixture, load_plan

REPO = Path(__file__).resolve().parents[3]
SEEDS = REPO / "content" / "course-42052" / "lessons"

GENERIC = "הסבירו במילים שלכם מה ניסיתם, מה ראיתם ומה עדיין אינו ידוע"
OLD_TITLE = "בדיקת יציאה"
TITLE = "לסיום: במילים שלכם"
HELP = "תשובה קצרה, משפט או שניים. אין כאן ציון – זה עוזר לכם (ולמרצה) לראות מה התבהר."

# Verbatim, as the operator set them (before [[ltr]] markup).
PROMPTS = {
    "lesson-01": "איך בדקתם שחישוב הרווח של הדוכן נכון – ולא רק סמכתם על מה שהצ׳טבוט כתב?",
    "lesson-02": "מה ההבדל בין אימון לחיזוי, ולמה בודקים את המודל על דוגמאות שלא שימשו באימון?",
    "lesson-03": "מה משתנה ברשת נוירונים בזמן אימון – ומה זה אומר כששתי מילים מקבלות ייצוגים קרובים?",
    "lesson-03-deeper": "איך מודל שפה בוחר את המילה הבאה – ולמה זה אומר שצריך לבדוק כל פרט שלא נמסר לו?",
    "lesson-04": "תארו את השינוי שעשיתם עם הסוכן: מה ציפיתם שיקרה, מה הראה ה-diff, ואיך בדקתם בעצמכם שזה עובד?",
    "lesson-05": "כתבו את פעולת ה-MVP שלכם במשפט אחד, ודוגמת קלט אחת עם הפלט הצפוי לה.",
    "lesson-06": "באיזו פקודה מריצים את השלד שלכם, ומה קרה כשחבר צוות אחר הריץ אותו לפי ה-README?",
    "lesson-07": "איזו בדיקה הוספתם לפלט של ה-AI, ומה המוצר מציג כשהשירות נכשל?",
    "lesson-08": "איך הוכחתם שהזמנה באמת נשמרה, ומה קורה כשמזינים קלט שגוי?",
    "lesson-09": "כתבו תצפית אחת מבדיקת השימוש – מה המשתמש עשה ומה קרה – ואת השינוי שעשיתם בעקבותיה.",
    "lesson-10": "איזה סיכון מצאתם במוצר, ואיזה מנגנון בקוד או בהרשאות מונע אותו?",
    "lesson-11": "מה בדקתם כשפתחתם את המוצר ממכשיר שאינו מחשב הפיתוח, ומה גיליתם?",
    "lesson-12": "מה הראיה החזקה ביותר שהצגתם לכך שהמוצר עובד, ואיזו מגבלה אמרתם בגלוי?",
    "lesson-13": "מה תעשו אחרת בפרויקט הבא, ולמה?",
}


def _plan_slugs() -> list[str]:
    keys = [k for s in load_plan("42052")["sessions"] for k in [s["fixture_key"], *s["part_fixture_keys"]]]
    return [k.removeprefix("42052-") for k in keys]


def _sections(node):
    if isinstance(node, dict):
        if node.get("type") == "section":
            yield node
        for v in node.values():
            yield from _sections(v)
    elif isinstance(node, list):
        for v in node:
            yield from _sections(v)


def test_every_plan_lesson_has_its_prompt():
    assert sorted(_plan_slugs()) == sorted(PROMPTS)
    assert course_plan.EXIT_CHECK_TITLE == TITLE and course_plan.EXIT_CHECK_HELP == HELP


def test_no_lesson_seed_or_built_still_has_the_generic_prompt_or_old_title():
    texts = {p.name: p.read_text(encoding="utf-8") for p in sorted((CONTENT_DIR / "course-42052").glob("*.json"))}
    texts |= {k: json.dumps(load_fixture(k), ensure_ascii=False) for k in (f"42052-{s}" for s in PROMPTS)}
    if SEEDS.is_dir():
        texts |= {f"seed/{p.name}": p.read_text(encoding="utf-8") for p in sorted(SEEDS.glob("lesson-*.json"))}
    assert len(texts) >= 15
    for name, text in texts.items():
        assert GENERIC not in text, name
        assert "מה עדיין אינו ידוע" not in text, name
        assert OLD_TITLE not in text, name


def test_each_seed_carries_its_lessons_prompt_verbatim():
    if not SEEDS.is_dir():
        return
    seeds = {json.loads(p.read_text(encoding="utf-8"))["slug"]: p for p in sorted(SEEDS.glob("lesson-*.json"))}
    assert len(seeds) == 13
    for slug, path in seeds.items():
        assert json.loads(path.read_text(encoding="utf-8"))["exit_check_he"] == PROMPTS[slug], slug


def test_each_built_lesson_asks_its_concrete_question_under_the_new_title():
    for slug, prompt in PROMPTS.items():
        lesson = load_fixture(f"42052-{slug}")
        key = f"{slug}-exit"  # the same id as before
        exits = [k for k in lesson["questions"] if k.endswith("-exit")]
        assert exits == [key], slug
        question = lesson["questions"][key]
        assert question["prompt"] == course_plan.ltr(prompt), slug
        assert question["type"] == "free_text" and question["step"] == "wrap-up", slug
        holding = [s for s in _sections(lesson) if {"type": "question", "question": key} in s["blocks"]]
        assert len(holding) == 1, slug
        section = holding[0]
        assert section["title"] == TITLE, slug
        assert section["blocks"] == [{"type": "text", "body": [HELP]}, {"type": "question", "question": key}], slug
