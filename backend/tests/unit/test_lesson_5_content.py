"""Lesson 5 of the 42052 plan ("defining a small business product"), authored
in this repository from its seed: the committed content carries no answer key,
keeps the seed's checks and texts verbatim, follows the step contract (one
goal, explain, act, check, next), ships a SPEC.md template whose sha256 is in
its assets, and adds an architecture-map self-check whose mapping lives in the
content (it is practice, not a keyed question).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, assets_root, course_plan, load_fixture, load_plan, validate_content
from app.lessons.schema import ContentError

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SEED = REPO / "content" / "course-42052" / "lessons" / "lesson-05.json"
ORDERS = REPO / "content" / "course-42052" / "fixtures" / "bakery-orders.json"
CASES = REPO / "content" / "course-42052" / "fixtures" / "product-test-cases.json"
TEMPLATE_SRC = REPO / "content" / "course-42052" / "materials" / "lesson-05" / "SPEC.md"
TEMPLATE = ASSETS_ROOT / "lessons" / "lesson-05" / "v1" / "SPEC.md"

# Field names an answer key or private feedback would use, in any shape the
# app accepts (the instructor's file, the stored key, the seed's private copy).
PRIVATE_FIELDS = {"answer", "correct_choice_id", "feedback_he", "correct", "correct_options", "misconceptions",
                  "explanation", "sample_reasoning", "rubric", "instructor_email", "email"}


def _keys_in(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys_in(v)}
    return set()


def _all_blocks(blocks):
    for block in blocks:
        yield block
        yield from _all_blocks(block.get("blocks", []))


def _step(lesson: dict, key: str) -> dict:
    return next(s for s in lesson["steps"] if s["key"] == key)


@pytest.fixture(scope="module")
def lesson() -> dict:
    return load_fixture("42052-lesson-05")


def test_lesson_5_is_authored_valid_and_its_template_matches(lesson):
    assert "lesson-05" in course_plan.AUTHORED
    content = validate_content(lesson, assets_root())  # the template exists with the declared sha256
    assert (content.slug, content.course_code) == ("lesson-05", "42052")
    assert [s.key for s in content.steps] == ["need", "mvp", "architecture", "spec", "wrap-up"]
    asset = lesson["assets"]["spec_template"]
    assert (asset["path"], asset["filename"], asset["mime"]) == ("/lessons/lesson-05/v1/SPEC.md", "SPEC.md", "text/markdown")
    assert asset["sha256"] == hashlib.sha256(TEMPLATE.read_bytes()).hexdigest()
    # The served file is the committed source, byte for byte.
    assert TEMPLATE.read_bytes() == TEMPLATE_SRC.read_bytes()
    # It is offered in the spec step, for download.
    downloads = [b for b in _all_blocks(_step(lesson, "spec")["blocks"]) if b["type"] == "download"]
    assert [d["asset"] for d in downloads] == ["spec_template"]


def test_no_answer_key_in_any_committed_lesson_5_file(lesson):
    """The repository is public: the fixture, its plan entry and the template
    carry questions only, never a key or private feedback."""
    leaked = PRIVATE_FIELDS & _keys_in(lesson)
    assert not leaked, sorted(leaked)
    leaked = PRIVATE_FIELDS & _keys_in(load_plan("42052")["lessons"]["lesson-05"])
    assert not leaked, sorted(leaked)
    template = TEMPLATE_SRC.read_text(encoding="utf-8")
    for marker in ("correct_choice_id", "feedback_he", "l05-", "lesson-05-exit"):
        assert marker not in template, marker
    for key, question in lesson["questions"].items():
        assert "answer" not in question, key
        if question["type"] == "single_choice":
            assert question["mode"] == "check", key  # no reveal before a first answer


def test_the_seed_checks_and_texts_survive_unchanged(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    generated = course_plan.seed_to_content(seed, "42052")
    # The seed's three checks and the exit check: same key, step, wording and
    # options, so a key file written against the seed fits the authored lesson.
    assert set(generated["questions"]) == {"l05-q1", "l05-q2", "l05-q3", "lesson-05-exit"}
    for key, question in generated["questions"].items():
        assert lesson["questions"][key] == question, key
    # Each sits in the step the seed put it in, and the seed's step titles stay.
    for step in generated["steps"]:
        assert _step(lesson, step["key"])["title"] == step["title"], step["key"]
    text = json.dumps(lesson, ensure_ascii=False)
    plain = text.replace("**", "")
    for field in ("worked_example_he", "work_product_he"):
        assert course_plan.ltr(seed[field]) in plain, field
    assert seed["optional_extension_he"] is None


def test_the_homework_stays_a_proposal_for_the_instructor_only(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert seed["homework_status"] == "proposal_not_yet_assigned"
    homework = load_plan("42052")["lessons"]["lesson-05"]["homework"]
    assert homework == {"status": "proposal_not_yet_assigned", "text": "הצעת פרויקט + SPEC.md (לפי התבנית)"}
    text = json.dumps(lesson, ensure_ascii=False)
    assert "מטלה" not in text and homework["text"] not in text and seed["homework_he"] not in text
    # The exit question's helper line says there is no grade ("אין כאן ציון");
    # it is the only place the word may appear.
    assert text.count(course_plan.EXIT_CHECK_HELP) == 1
    text = text.replace(course_plan.EXIT_CHECK_HELP, "")
    for word in ("deadline", "מועד הגשה", "משקל", "ציון", "אחוז"):
        assert word not in text and word not in homework["text"], word
    # The syllabus milestone is named, with no date, place or weight invented.
    wrap = json.dumps(_step(lesson, "wrap-up"), ensure_ascii=False)
    assert "לפי הסילבוס" in wrap and "הצעת פרויקט ואפיון" in wrap and "המרצה יפרסם" in wrap


def test_every_step_has_one_goal_an_explanation_an_action_a_check_and_a_next_step(lesson):
    for step in lesson["steps"]:
        assert step.get("goal"), step["key"]
        sections = [b for b in step["blocks"] if b["type"] == "section"]
        labels = [s["label"] for s in sections]
        assert labels[0] == "understand" and "check" in labels, step["key"]
        assert step["completion"], step["key"]
        if step["key"] == "wrap-up":
            continue
        assert step.get("next_hint"), step["key"]
        # Exactly one required action; any other "try" section is labeled optional.
        required = [s for s in sections if s["label"] == "try" and "רשות" not in s.get("title", "")]
        assert len(required) == 1, step["key"]
        action = required[0]["blocks"][0]
        assert action["type"] == "text" and action["body"][0].startswith("**הפעולה:**"), step["key"]
        assert sum(b["body"][0].startswith("**הפעולה:**") for b in _all_blocks(step["blocks"]) if b["type"] == "text") == 1
        # Extras are marked "רשות" or as the fallback route.
        for block in _all_blocks(step["blocks"]):
            if block["type"] == "expander":
                assert block["title"].startswith(("רשות", "מסלול חלופי")), block["title"]
    # The team works together: said up front and in the actions.
    assert "בצוות הפרויקט" in json.dumps(lesson["steps"][0]["blocks"][0], ensure_ascii=False)
    assert "צוות" in lesson["intro"]


def test_concepts_are_explained_before_they_are_used(lesson):
    """Each term is defined in the understand section of the step that first
    needs it, and does not appear in an earlier step."""
    def understand(step):
        return json.dumps(next(b for b in step["blocks"] if b.get("label") == "understand"), ensure_ascii=False)

    first = {
        "need": ["**עובדה**", "**הנחה**", "**שאלה**", "**משתמש**", "**מצב**", "**קושי**"],
        "mvp": ["**[[MVP]]**", "**בפנים ובחוץ:**", "**תשובה צפויה:**", "«הוראה בתוך הנתונים»"],
        "architecture": ["**ממשק** ([[frontend]])", "**שרת** ([[backend]])", "**מסד נתונים** ([[database]])",
                         "**[[API]]** –", "**מפתח [[API]]**"],
        "spec": ["**אפיון** ([[spec]]", "[[Markdown]]"],
    }
    keys = [s["key"] for s in lesson["steps"]]
    for key, words in first.items():
        step = _step(lesson, key)
        for word in words:
            assert word in understand(step), (key, word)
    # Not used before being explained (the intro, and a next-step hint that
    # announces it, aside).
    later = {"[[frontend]]": "architecture", "[[backend]]": "architecture", "SPEC.md": "spec", "[[MVP]]": "mvp"}
    for word, home in later.items():
        for step in lesson["steps"][: keys.index(home)]:
            body = {k: v for k, v in step.items() if k != "next_hint"}
            assert word not in json.dumps(body, ensure_ascii=False), (word, step["key"])


def test_the_bakery_example_and_the_test_case_kinds_come_from_the_fixtures(lesson):
    orders = json.loads(ORDERS.read_text(encoding="utf-8"))
    mvp = json.dumps(_step(lesson, "mvp"), ensure_ascii=False)
    for message in orders["messages"]:
        assert message["text"] in mvp, message["id"]
    assert orders["expected_total_items"] == {"לחמניות": 10, "עוגיות": 5}
    assert "10 לחמניות, 5 עוגיות" in mvp and "שעה חסרה – לסמן לבירור" in mvp
    # The four kinds of cases, in the shape of product-test-cases.json.
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))}
    table = next(b for b in _all_blocks(_step(lesson, "mvp")["blocks"])
                 if b["type"] == "table" and b["caption"] == "ארבעה סוגי מקרים, בדוגמת המאפייה")
    kinds = [row[0] for row in table["rows"]]
    assert kinds == ["תקין", "חסר", "לא תקין", "הוראה בתוך הנתונים"]
    by_kind = dict(zip(kinds, table["rows"]))
    for kind, case in (("תקין", "valid-order"), ("חסר", "missing-time")):
        assert by_kind[kind][1:] == [cases[case]["input"], cases[case]["expected"]], kind
    assert by_kind["לא תקין"][2] == cases["invalid-quantity"]["expected"]
    assert "`-2`" in by_kind["לא תקין"][1]
    assert "instruction-in-data" in cases and "מפתח" in by_kind["הוראה בתוך הנתונים"][1]
    assert "בהמשך הקורס לבדיקות" in mvp


def test_prompts_ask_and_compare_but_never_decide_and_the_agent_writes_no_code(lesson):
    prompts = {b["title"]: b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "prompt"}
    for p in prompts.values():
        assert p["text"].strip() and p.get("note"), p["title"]
        assert "[הדביקו" not in p["text"] and "http" not in p["text"]
    need = prompts["בקשה לצ׳טבוט: שאלות הבהרה ושני כיוונים"]["text"]
    assert "אל תבחר בשבילנו" in need and "אל תכריע" in need and "שאלות הבהרה" in need
    assert "שני כיווני פתרון" in need and "עובדות" in need and "הנחות" in need
    spec = prompts["בקשה לסוכן: ראיון ואפיון, בלי קוד"]["text"]
    assert spec.startswith("/plan ")
    assert "קודם הצג תוכנית" in spec and "שאל אותנו לפני כל הנחה" in spec and "אל תכתוב קוד" in spec
    assert spec.index("קודם הצג תוכנית") < spec.index("ראיין אותנו") < spec.index("AGENTS.md (")
    for section in ("משתמש ובעיה", "פעולת ה-MVP", "שלוש דוגמאות", "מסלול המשתמש", "מה קורה כשהוא נכשל", "שאלות פתוחות"):
        assert section in spec, section
    assert "פקודת הבדיקה המתוכננת" in spec and "אל תכתוב שום סוד" in spec
    # The no-install route copies the template into a free chatbot.
    step = json.dumps(_step(lesson, "spec"), ensure_ascii=False)
    assert "מסלול חלופי" in step and "צ׳טבוט חינמי" in step and "העתיקו את כל התוכן" in step


def test_the_spec_template_covers_every_section_and_keeps_secrets_out():
    template = TEMPLATE_SRC.read_text(encoding="utf-8")
    for heading in ("## 1. משתמש ובעיה", "## 2. MVP – פעולה אחת מקצה לקצה", "## 3. Examples – קלט ותשובה צפויה",
                    "## 4. Architecture – מסלול המשתמש והחלקים", "## 5. AI – איפה משתמשים בו, ומה קורה כשהוא נכשל",
                    "## 6. שאלות פתוחות"):
        assert heading in template, heading
    assert "עובדות" in template and "הנחות" in template and "שני כיווני פתרון" in template
    assert "frontend / backend / database / AI API" in template
    assert "לעולם לא כותבים כאן סיסמה, מפתח API או כל סוד אחר" in template
    lowered = template.lower()
    for secret in ("api_key", "api_key=", "sk-", "password", "token", "http"):
        assert secret not in lowered, secret
    for claim in ("₪", "$", "חינם", "מכסה", "quota"):
        assert claim not in template, claim


def test_ai_api_is_named_as_options_with_no_pricing_and_the_key_stays_server_side(lesson):
    text = json.dumps(lesson, ensure_ascii=False)
    arch = json.dumps(_step(lesson, "architecture"), ensure_ascii=False)
    assert "[[Gemini API]]" in arch and "[[Anthropic API]]" in arch and "[[OpenAI API]]" in arch
    assert arch.index("[[Gemini API]]") < arch.index("[[Anthropic API]]")
    assert "ברירת המחדל" in arch and "בשיעור 7" in arch
    for claim in ("₪", "$", "USD", "מכסת", "לחודש", "בחינם", "quota", "rate limit"):
        assert claim not in text, claim
    assert "מפתח [[API]] לעולם לא נכנס לקוד הממשק" in arch and "בשיעורים 7 ו-10" in arch
    assert "לא כל מוצר קטן צריך את כל החלקים מהיום הראשון" in arch
    assert "http" not in text


def _map_block(lesson):
    return next(b for b in _all_blocks(_step(lesson, "architecture")["blocks"]) if b["type"] == "architecture_map")


def test_the_architecture_map_is_an_optional_self_check_with_reasons(lesson):
    block = _map_block(lesson)
    holder = next(s for s in _step(lesson, "architecture")["blocks"]
                  if s["type"] == "section" and block in s["blocks"])
    assert holder["label"] == "try" and holder["title"].startswith("רשות")
    assert [p["id"] for p in block["parts"]] == ["frontend", "backend", "data", "ai"]
    mapping = {plain["label"]: plain["model_part"] for plain in block["items"]}
    assert mapping == {
        "כפתור שליחת הזמנה": "frontend",
        "בדיקה שהכמות חיובית": "backend",
        "שמירת ההזמנה": "data",
        "קריאה למודל שפה לחילוץ פרטים": "ai",
        "מפתח [[API]]": "backend",
        "הצגת הסיכום והשעות לבירור": "frontend",
    }
    for item in block["items"]:
        assert item["reason"].strip() and "\n" not in item["reason"], item["id"]
    # Not a question and not part of completion: nothing is recorded.
    step = _step(lesson, "architecture")
    assert all(r["type"] != "ack" for r in step["completion"])


def test_the_map_does_not_reuse_a_keyed_question(lesson):
    """The mapping is public; no single-choice question may be answered by it
    (same wording as an item, or an option that names an item's part)."""
    block = _map_block(lesson)
    items = {i["label"] for i in block["items"]} | {i["reason"] for i in block["items"]}
    for key, question in lesson["questions"].items():
        if question["type"] != "single_choice":
            continue
        for option in question["options"]:
            assert option["text"] not in items, (key, option["id"])
        for item in block["items"]:
            assert item["label"] not in question["prompt"] or item["label"] == "מפתח [[API]]", key
    # The key question asks why (what reaches the browser), not where the key goes.
    prompt = lesson["questions"]["l05-key-frontend"]["prompt"]
    assert "מה הבעיה" in prompt and "איפה" not in prompt


def test_the_map_is_validated():
    base = load_fixture("42052-lesson-05")
    for change, message in (
        (lambda b: b["items"][0].update(model_part="cloud"), "maps to an unknown part 'cloud'"),
        (lambda b: b["parts"].append(dict(b["parts"][0])), "duplicate part id 'frontend'"),
        (lambda b: b["items"].append(dict(b["items"][0])), "duplicate item id 'send-button'"),
    ):
        broken = json.loads(json.dumps(base))
        change(_map_block(broken))
        with pytest.raises(ContentError) as exc:
            validate_content(broken, assets_root())
        assert any(message in e for e in exc.value.errors), exc.value.errors
    broken = json.loads(json.dumps(base))
    _map_block(broken)["items"][0]["answer"] = "x"  # strict: no unknown fields
    with pytest.raises(ContentError):
        validate_content(broken, assets_root())


def test_single_choice_options_do_not_follow_a_longest_is_right_pattern(lesson):
    """The real keys are private; this checks the shape only: the new
    formative questions have three options of varied length, so length alone
    can't point at an answer across the lesson."""
    seed_keys = {"l05-q1", "l05-q2", "l05-q3"}
    new = [q for k, q in lesson["questions"].items() if q["type"] == "single_choice" and k not in seed_keys]
    assert len(new) >= 4
    longest_positions = set()
    for q in new:
        lengths = [len(o["text"]) for o in q["options"]]
        assert len(lengths) == 3 and len(set(lengths)) == 3, q["key"]
        longest_positions.add(lengths.index(max(lengths)))
    assert len(longest_positions) >= 2  # the longest option is not always in the same place
