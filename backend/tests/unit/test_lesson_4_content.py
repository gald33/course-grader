"""Lesson 4 of the 42052 plan ("coding agent: from plan to run and check"),
authored in this repository from its seed: the committed content carries no
answer key, keeps the seed's checks and texts, follows the step contract (one
goal, explain, act, check, next), and its starter project (a zip built from
content/course-42052/materials/lesson-04/) opens in a browser and passes its
own check with the output the lesson documents.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, assets_root, course_plan, load_fixture, load_plan, validate_content

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SEED = REPO / "content" / "course-42052" / "lessons" / "lesson-04.json"
ORDERS = REPO / "content" / "course-42052" / "fixtures" / "bakery-orders.json"
STARTER_SRC = REPO / "content" / "course-42052" / "materials" / "lesson-04" / "bakery-orders-starter"
STARTER_ZIP = ASSETS_ROOT / "lessons" / "lesson-04" / "v2" / "bakery-orders-starter.zip"
# The first starter, kept for lesson versions that still link to it.
STARTER_ZIP_V1 = ASSETS_ROOT / "lessons" / "lesson-04" / "v1" / "bakery-orders-starter.zip"
STARTER_V1_SHA256 = "df0e561fe275ba0e621ae4f45f2b02b099d8cfcfbd4f43cd2d74c0c40be81d74"
STARTER_FILES = {
    "README.md", "index.html", "app.js", "orders.js", "data.js", "checks.js", "check.js", "check.html",
    "instructions-template.md",
}

# Field names an answer key or private feedback would use, in any shape the
# app accepts (the instructor's file, the stored key, the seed's private copy).
WORKED_EXAMPLE = (
    "בקשה טובה: «הוסף הודעת אישור אחרי לחיצה מוצלחת על «סימון כמוכנה». קודם הצג תוכנית: אילו קבצים תשנה ואיפה; "
    "אל תשנה את חישוב סך הכול. בדוק גם סימון של הזמנה שלא קיימת, והצג את ה-[[diff]]»."
)

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


def _builder():
    spec = importlib.util.spec_from_file_location("build_lesson_4_starter", BACKEND / "scripts" / "build_lesson_4_starter.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lesson() -> dict:
    return load_fixture("42052-lesson-04")


def _expected_output(lesson: dict) -> str:
    code = next(b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "code")
    return code["code"]


def test_lesson_4_is_authored_valid_and_its_starter_matches(lesson):
    assert "lesson-04" in course_plan.AUTHORED
    content = validate_content(lesson, assets_root())  # the zip exists with the declared sha256
    assert (content.slug, content.course_code) == ("lesson-04", "42052")
    assert [s.key for s in content.steps] == ["harness", "agent", "save", "loop", "context", "wrap-up"]
    assert [s.letter for s in content.steps] == list("ABCDEF")
    assert lesson["assets"]["starter"]["path"] == "/lessons/lesson-04/v2/bakery-orders-starter.zip"
    assert hashlib.sha256(STARTER_ZIP_V1.read_bytes()).hexdigest() == STARTER_V1_SHA256  # v1 is untouched
    # The zip is the build of the committed source folder, byte for byte.
    assert STARTER_ZIP.read_bytes() == _builder().build(), "run: python scripts/build_lesson_4_starter.py"
    with zipfile.ZipFile(STARTER_ZIP) as archive:
        names = archive.namelist()
    assert {n.removeprefix("bakery-orders-starter/") for n in names} == STARTER_FILES
    assert all(n.startswith("bakery-orders-starter/") for n in names)
    # The instructions file is the student's to create in step D, from the template.
    assert "AGENTS.md" not in {Path(n).name for n in names}


def test_no_answer_key_in_any_committed_lesson_4_file(lesson):
    """The repository is public: the fixture, its plan entry and the starter
    carry questions only, never a key or private feedback."""
    leaked = PRIVATE_FIELDS & _keys_in(lesson)
    assert not leaked, sorted(leaked)
    leaked = PRIVATE_FIELDS & _keys_in(load_plan("42052")["lessons"]["lesson-04"])
    assert not leaked, sorted(leaked)
    for path in STARTER_SRC.iterdir():
        text = path.read_text(encoding="utf-8")
        for marker in ("correct_choice_id", "feedback_he", "l04-", "lesson-04-exit"):
            assert marker not in text, f"{path.name}: {marker}"
    for key, question in lesson["questions"].items():
        assert "answer" not in question, key
        if question["type"] == "single_choice":
            assert question["mode"] == "check", key  # no reveal before a first answer


def test_the_seed_checks_and_texts_survive_unchanged(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    generated = course_plan.seed_to_content(seed, "42052")
    # The seed's three checks and the exit check: same key, step, wording and
    # options, so a key file written against the seed fits the authored lesson.
    for key, question in generated["questions"].items():
        assert lesson["questions"][key] == question, key
    text = json.dumps(lesson, ensure_ascii=False)
    plain = text.replace("**", "")
    assert course_plan.ltr(seed["work_product_he"]) in plain
    # The worked example is the planner's revision of the seed's (review N5):
    # it names this lesson's button, file and edge case.
    wrap = next(s for s in lesson["steps"] if s["key"] == "wrap-up")
    worked = next(b for b in _all_blocks(wrap["blocks"]) if b.get("title") == "דוגמה פתורה")
    assert worked["body"] == [WORKED_EXAMPLE]
    assert seed["optional_extension_he"] is None
    # The homework is a proposal, adapted to the lesson's tool: kept in the
    # instructor's plan, never in the lesson.
    assert seed["homework_status"] == "proposal_not_yet_assigned"
    homework = load_plan("42052")["lessons"]["lesson-04"]["homework"]
    assert homework["status"] == "proposal_not_yet_assigned"
    assert homework["text"].startswith("הצעה:") and "Antigravity" in homework["text"]
    assert "אין להניח גישה חינמית או רישיון לכל ספק" in homework["text"]
    assert "מטלה" not in text and homework["text"] not in text and seed["homework_he"] not in text
    # The exit question's helper line says there is no grade ("אין כאן ציון");
    # it is the only place the word may appear.
    assert text.count(course_plan.EXIT_CHECK_HELP) == 1
    text = text.replace(course_plan.EXIT_CHECK_HELP, "")
    for word in ("deadline", "מועד הגשה", "משקל בציון", "ציון"):
        assert word not in text and word not in homework["text"]


def test_every_step_has_one_goal_an_explanation_an_action_a_check_and_a_next_step(lesson):
    for step in lesson["steps"]:
        assert step.get("goal"), step["key"]
        labels = [b["label"] for b in step["blocks"] if b["type"] == "section"]
        assert labels[0] == "understand" and "check" in labels, step["key"]
        if step["key"] != "wrap-up":
            assert "try" in labels, step["key"]
            assert step.get("next_hint"), step["key"]
            action = next(b for b in step["blocks"] if b.get("label") == "try")["blocks"][0]
            assert action["type"] == "text" and action["body"][0].startswith("**הפעולה:**"), step["key"]
        assert step["completion"], step["key"]
    # Words a student without programming background meets are explained in
    # the step that first uses them, before any action.
    first = {"harness": ["**קובץ**", "**תיקיית פרויקט**", "**טרמינל**", "**[[harness]]**"], "save": ["**[[commit]]**"],
             "loop": ["**[[diff]]**"], "context": ["**מפתח [[API]]**", "**סוד**"]}
    for step in lesson["steps"]:
        understand = json.dumps(step["blocks"][0 if step["blocks"][0]["type"] == "section" else 1], ensure_ascii=False)
        for word in first.get(step["key"], []):
            assert word in understand, (step["key"], word)
    # The expected result is written before the change is asked for.
    loop = next(s for s in lesson["steps"] if s["key"] == "loop")
    try_blocks = next(b for b in loop["blocks"] if b.get("label") == "try")["blocks"]
    order = [b.get("question") or b.get("title") or b["type"] for b in try_blocks]
    assert order.index("l04-expected") < order.index("בקשה לסוכן: שינוי קטן, תוכנית קודם")


def test_agent_prompts_are_complete_and_ask_for_a_plan_first_and_evidence(lesson):
    prompts = [b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "prompt"]
    assert len(prompts) >= 4
    for p in prompts:
        assert p["text"].strip() and p.get("note"), p["title"]
        assert "[הדביקו" not in p["text"]
    # Every prompt that lets the agent act asks for a plan first and for evidence.
    acting = [p for p in prompts if p["title"] != "בקשה לסוכן: שינוי אחד, לפי ההוראות"]
    for p in acting:
        assert "תוכנית" in p["text"] or "התוכן המוצע" in p["text"], p["title"]
        assert re.search(r"(הצג|הראה|הדבק|באיזה קובץ ראית)", p["text"]), p["title"]
    change = next(p for p in prompts if "שינוי קטן" in p["title"])
    assert change["text"].startswith("/plan ")
    assert "node check.js" in change["text"] and "totalItems" in change["text"]
    # The one prompt without rules is the test of the instructions file.
    bare = next(p for p in prompts if p["title"] == "בקשה לסוכן: שינוי אחד, לפי ההוראות")
    assert "AGENTS.md" in bare["note"]


def test_antigravity_is_cited_with_no_pricing_claims_and_a_labeled_fallback(lesson):
    text = json.dumps(lesson, ensure_ascii=False)
    assert "http" not in text  # site names only, as plain text
    assert "[[antigravity.google/docs]]" in text and "10 בנובמבר 2026" in text  # rechecked on the build date
    assert "[[antigravity.google/docs/sandbox]]" in text
    assert "[[antigravity.google/download]]" in text and "[[antigravity.google/docs/rules]]" in text
    assert "`AGENTS.md`" in text and "`GEMINI.md`" in text
    # Sign-in prerequisites as Google states them, cited; nothing about institutional accounts.
    prereq = json.dumps(next(s for s in lesson["steps"] if s["key"] == "agent")["blocks"][0], ensure_ascii=False)
    assert "הכנה (לפני השיעור)" in prereq and "[[Software Engineering]]" in prereq and "[[Interface Layout]]" in prereq
    assert "חשבון Google אישי – לא חשבון של המכללה" in prereq and "[[Ubuntu 20]]" in prereq
    assert "חשבון Google אישי" in prereq and "מגיל 18" in prereq and "[[antigravity.google/docs/faq]]" in prereq
    assert "מסלול חלופי" in prereq
    for word in ("מוסד", "של עבודה", "Workspace"):  # "not the college's account" only
        assert word not in text, word
    # Limits: a pointer to the current ones, never a price or quota.
    assert "[[antigravity.google/docs/plans]]" in text
    for claim in ("₪", "$", "USD", "Ultra", "Pro ", "מכסת", "לשבוע", "בחינם"):
        assert claim not in text, claim
    assert "Turbo" in text  # named only as the setting not to turn on
    # The no-install path is labeled as an alternative in each step that needs it.
    for key in ("agent", "save"):
        step = json.dumps(next(s for s in lesson["steps"] if s["key"] == key), ensure_ascii=False)
        assert "מסלול חלופי" in step, key
    # Claude Code and Codex: named in the harness step as the same pattern, and
    # a short comparison at the end; nothing to install.
    wrap = json.dumps(lesson["steps"][-1], ensure_ascii=False)
    assert "Claude Code" in wrap and "Codex" in wrap and "לא נדרש להתקין" in wrap and "אותו דפוס" in wrap
    middle = json.dumps(lesson["steps"][1:-1], ensure_ascii=False)
    assert "Claude Code" not in middle and "Codex" not in middle


def test_starter_data_is_the_course_example(lesson):
    """data.js holds the three synthetic messages of bakery-orders.json, read
    the way the fixture expects (totals, m3's pickup time missing)."""
    source = (STARTER_SRC / "data.js").read_text(encoding="utf-8")
    body = source[source.index("{"): source.rindex("};") + 1]
    data = json.loads(re.sub(r"(\s)([a-z_]+):", r'\1"\2":', body))
    orders = json.loads(ORDERS.read_text(encoding="utf-8"))
    assert [(o["id"], o["message"]) for o in data["orders"]] == [(m["id"], m["text"]) for m in orders["messages"]]
    totals: dict[str, int] = {}
    for order in data["orders"]:
        for item in order["items"]:
            label = data["products"][item["product"]]
            totals[label] = totals.get(label, 0) + item["quantity"]
    assert totals == orders["expected_total_items"]
    assert [o["id"] for o in data["orders"] if o["pickup_time"] is None] == [
        f["message_id"] for f in orders["expected_missing_fields"] if f["field"] == "pickup_time"
    ]


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is needed to run the starter's check")
        pytest.skip("node is not installed")
    return node


def test_the_starter_check_prints_the_documented_output(lesson, tmp_path):
    """Unzipped as a student would, `node check.js` prints exactly what the
    lesson and the starter's README say, and fails when a total is wrong."""
    node = _node()
    with zipfile.ZipFile(STARTER_ZIP) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / "bakery-orders-starter"
    run = subprocess.run([node, "check.js"], cwd=folder, capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    expected = _expected_output(lesson)
    assert run.stdout == expected
    assert expected.rstrip("\n").endswith("5 of 5 checks passed")
    assert f"```\n{expected}```" in (folder / "README.md").read_text(encoding="utf-8")

    # The check catches a broken total.
    orders = folder / "orders.js"
    orders.write_text(orders.read_text(encoding="utf-8").replace("+ item.quantity;", "+ item.quantity + 1;"), encoding="utf-8")
    broken = subprocess.run([node, "check.js"], cwd=folder, capture_output=True, text=True, timeout=60)
    assert broken.returncode == 1
    assert "FAIL total rolls = 10" in broken.stdout and "3 of 5 checks passed" in broken.stdout


def test_the_starter_template_keeps_secrets_out():
    template = (STARTER_SRC / "instructions-template.md").read_text(encoding="utf-8")
    for heading in ("## מטרת הפרויקט", "## איך מריצים", "## איך בודקים", "## מה לא משנים", "## איך עובדים"):
        assert heading in template
    assert "node check.js" in template and "לעולם לא כותבים כאן סיסמה" in template
    for path in STARTER_SRC.iterdir():
        text = path.read_text(encoding="utf-8")
        for secret in ("api_key", "API_KEY=", "sk-", "password", "token"):
            assert secret not in text.lower(), f"{path.name}: {secret}"


def test_git_install_and_going_back_are_spelled_out(lesson):
    """Reed's N2 and N3: what each OS shows when installing git (accept the
    defaults), and unstaging before Discard, since Discard keeps staged changes."""
    save = json.dumps(next(s for s in lesson["steps"] if s["key"] == "save"), ensure_ascii=False)
    for os_name in ("[[Windows]]", "[[macOS]]", "[[Linux]]"):
        assert f"**{os_name}:**" in save, os_name
    assert save.count("ברירות המחדל") >= 3 and "[[Command Line Tools]]" in save
    loop = next(s for s in lesson["steps"] if s["key"] == "loop")
    back = next(b for b in _all_blocks(loop["blocks"]) if b.get("title") == "השינוי מקלקל משהו? חוזרים לנקודת השמירה")
    items = back["blocks"][0]["items"]
    assert items[0].startswith("**קודם כול, דרך הסוכן:**")  # review B5: the agent revert first
    assert items[1].startswith("**[[Staged Changes]]** הם שינויים שסומנו כבר לשמירה")
    review = next(i for i in items if i.startswith("**בחלונית [[Review]]:**"))
    assert review.index("[[Unstage change]]") < review.index("[[Discard unstaged changes]]")
    # The commit is a required, separate last line of the action (step E depends on it).
    action = next(b for b in loop["blocks"] if b.get("label") == "try")["blocks"][0]["body"]
    assert action[-1].startswith("**ולסיום (חובה):**") and "[[commit]]" in action[-1]
    assert {"type": "ack", "key": "committed"} in loop["completion"]
    assert "[[Include unstaged changes]]" in json.dumps(loop, ensure_ascii=False)
    # Git asks for a name: kept to this repository, never --global.
    save_prompt = next(b for b in _all_blocks(next(s for s in lesson["steps"] if s["key"] == "save")["blocks"])
                       if b.get("type") == "prompt")
    assert "git config user.name" in save_prompt["text"] and "בלי --global" in save_prompt["text"]


def _flow(lesson: dict) -> str:
    """The student-facing text in the order the page shows it: the intro, then
    each step's blocks, with each question's text where its block stands."""
    def walk(blocks):
        for block in blocks:
            if block.get("type") == "question":
                yield json.dumps(lesson["questions"][block["question"]], ensure_ascii=False)
            else:
                yield json.dumps({k: v for k, v in block.items() if k != "blocks"}, ensure_ascii=False)
                yield from walk(block.get("blocks", []))
    parts = [lesson["intro"]]
    for step in lesson["steps"]:
        parts += [step["title"], step.get("goal", ""), *walk(step["blocks"]), step.get("next_hint", "")]
    return "\n".join(parts)


# Each term a student without programming background meets: how it appears,
# and the definition it must not come before (review: no concept before its definition).
CONCEPTS = {
    "turn": (r"(?<![א-ת])[הבלמו]?תור(?![א-ת])", "**תור** – מהרגע"),
    "harness": (r"harness", "**[[harness]]** (רתמה)"),
    "tool request": (r"בקשת כלי|בקשות כלי|תוצאת הכלי|תוצאות כלי", "**בקשת כלי** – הפלט"),
    "sandbox": (r"ארגז ה?חול|sandbox", "**ארגז חול** ([[sandbox]])"),
    "Git": (r"(?<![A-Za-z])Git(?![A-Za-z])", "**[[Git]]** הוא כלי"),
    "repository": (r"מאגר", "**מאגר [[Git]]** הוא"),
    "commit": (r"(?i)commit", "**[[commit]]** הוא נקודת שמירה"),
    "diff": (r"(?i)diff", "**[[diff]]** הוא תצוגת"),
    "staged": (r"(?i)staged", "**[[Staged Changes]]** הם"),
    "AGENTS.md": (r"AGENTS\.md", "**קובץ ההוראות** (`AGENTS.md`, קובץ"),
    "API key": (r"מפתח (\[\[)?API|מפתחות", "**מפתח [[API]]** הוא"),
    "secret": (r"(?<![א-ת])[הבלו]?סוד(ות)?(?![א-ת])", "**סוד** הוא"),
    "node": (r"(?<![A-Za-z])node(?![A-Za-z])", "`node` – תוכנה שמריצה"),
}


@pytest.mark.parametrize("term", list(CONCEPTS))
def test_every_concept_is_defined_before_its_first_use(lesson, term):
    flow = _flow(lesson)
    pattern, definition = CONCEPTS[term]
    assert flow.count(definition) == 1, f"{term}: its definition appears {flow.count(definition)} times"
    first = re.search(pattern, flow)
    assert first, term
    at = flow.index(definition)
    assert first.start() >= at, f"{term} is used before it is defined: …{flow[max(0, first.start() - 60):first.start() + 30]}…"


def test_the_harness_step_comes_first_with_a_labeled_stepper(lesson):
    harness = lesson["steps"][0]
    assert harness["key"] == "harness" and harness["title"] == "איך סוכן קוד עובד מבפנים"
    text = json.dumps(harness, ensure_ascii=False)
    # Taught in order: turn, harness, context assembly, tool request, permission check, loop, so what.
    order = ["**תור**", "**[[harness]]**", "**הרכבת ההקשר**", "**בקשת כלי**", "**בדיקת הרשאות**", "**הלולאה**", "אז מה?"]
    at = [text.index(o) for o in order]
    assert at == sorted(at), order
    assert "חלון ההקשר" in text and "[[Claude Code]]" in text
    # The Windows sandbox fact, cited to the sandbox page.
    assert "[[24H2]]" in text and "[[Request Review]]" in text and "[[antigravity.google/docs/sandbox]]" in text
    stepper = next(b for b in _all_blocks(harness["blocks"]) if b["type"] == "agent_turn_stepper")
    frames = stepper["frames"]
    assert 3 <= len(frames) <= 10 and "question" not in frames[0]
    kinds = [f["model_output_kind"] for f in frames]
    assert "tool_request" in kinds and kinds[-1] == "text"  # the loop stops at a text answer
    for frame in frames[1:]:
        assert frame["question"] and frame["reveal"] and 2 <= len(frame["options"]) <= 3, frame["id"]
    # A tool request is run by the harness after a permission check, never by the model.
    runs = next(f for f in frames if "`node check.js`" in f["model_output"])
    assert runs["model_output_kind"] == "tool_request" and "ארגז חול" in runs["harness"] and runs["tool_result"]
    # The required action: walk the stepper; then the harness checks.
    assert harness["completion"][0] == {"type": "ack", "key": "turn_walked"}
    checks = [c["question"] for c in harness["completion"] if c["type"] == "answered"]
    assert checks == ["l04-harness-runs", "l04-harness-evidence"]
    for key in checks:
        assert lesson["questions"][key]["step"] == "harness"


def test_reworded_and_new_checks(lesson):
    qs = lesson["questions"]
    single = [k for k, q in qs.items() if q["type"] == "single_choice"]
    assert single == ["l04-harness-runs", "l04-harness-evidence", "l04-q1", "l04-permission", "l04-commit",
                      "l04-q2", "l04-diff", "l04-q3", "l04-secret", "l04-claim"]
    assert qs["l04-permission"]["prompt"] == "הסוכן מבקש אישור להריץ פקודה (מחוץ לארגז החול, או בלי ארגז חול). מה עושים?"
    assert [o["id"] for o in qs["l04-permission"]["options"]] == ["a", "b", "c"]
    assert qs["l04-commit"]["options"][0]["text"] == "תמונת מצב של הפרויקט שאפשר לחזור אליה"


def test_the_context_step_defines_secrets_and_ties_back_to_the_harness(lesson):
    context = next(s for s in lesson["steps"] if s["key"] == "context")
    text = json.dumps(context, ensure_ascii=False)
    assert "הרכבת ההקשר" in text and "[[harness]]" in text and "(אם שמרתם [[commit]] בסוף שלב D)" in text
    # Always "the instructions file (AGENTS.md)" in the student's text, never the bare file name.
    flow = _flow(lesson).replace("`AGENTS.md`, קובץ בתיקיית", "")
    for m in re.finditer(r"`AGENTS\.md`", flow):
        assert flow[max(0, m.start() - 15):m.start()].endswith("קובץ ההוראות ("), flow[m.start() - 40:m.end()]
    template = (STARTER_SRC / "instructions-template.md").read_text(encoding="utf-8")
    assert "`N of N checks passed` (בלי FAIL)" in template and "אם `node` לא מותקן – לא מתקינים; אומרים לי." in template


WINDOWS_SANDBOX = (
    "ארגז החול ב-[[Windows]] דורש [[Windows 11]] בגרסה [[24H2]] ומעלה, וגם את עדכון אוגוסט 2026 ומעלה. "
    "בכל [[Windows]] אחר – כולל [[Windows 10]] – אין ארגז חול: ההגדרה עוברת ל-[[Request Review]], "
    "והסוכן מבקש אישור לפני כל פקודה. גם אז – קוראים לפני שמאשרים."
)


def test_the_windows_sandbox_needs_both_conditions_wherever_it_is_mentioned(lesson):
    """Per antigravity.google/docs/sandbox: Windows 11 24H2+ AND the August
    2026 update+. Any other Windows has no sandbox (Request Review)."""
    text = json.dumps(lesson, ensure_ascii=False)
    assert text.count(WINDOWS_SANDBOX) == 2  # the harness step and the prep callout
    for step in ("harness", "agent"):
        assert WINDOWS_SANDBOX in json.dumps(next(s for s in lesson["steps"] if s["key"] == step), ensure_ascii=False)
    assert "שלפני [[24H2]]" not in text and "ישן יותר" not in text
