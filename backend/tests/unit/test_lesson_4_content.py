"""Lesson 4 of the 42052 plan ("coding agent: from plan to run and check"),
authored in this repository from its seed: the committed content carries no
answer key, keeps the seed's checks and texts, follows the step contract (one
goal, explain, act, check, next), and its starter project (a zip built from
content/course-42052/materials/lesson-04/) opens in a browser and passes its
own check with the output the lesson documents.
"""

from __future__ import annotations

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
STARTER_ZIP = ASSETS_ROOT / "lessons" / "lesson-04" / "v1" / "bakery-orders-starter.zip"
STARTER_FILES = {
    "README.md", "index.html", "app.js", "orders.js", "data.js", "checks.js", "check.js", "check.html",
    "instructions-template.md",
}

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
    assert [s.key for s in content.steps] == ["agent", "save", "loop", "context", "wrap-up"]
    assert lesson["assets"]["starter"]["path"] == "/lessons/lesson-04/v1/bakery-orders-starter.zip"
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
    for field in ("worked_example_he", "work_product_he"):
        assert course_plan.ltr(seed[field]) in plain, field
    assert seed["optional_extension_he"] is None
    # The homework is a proposal, adapted to the lesson's tool: kept in the
    # instructor's plan, never in the lesson.
    assert seed["homework_status"] == "proposal_not_yet_assigned"
    homework = load_plan("42052")["lessons"]["lesson-04"]["homework"]
    assert homework["status"] == "proposal_not_yet_assigned"
    assert homework["text"].startswith("הצעה:") and "Antigravity" in homework["text"]
    assert "אין להניח גישה חינמית או רישיון לכל ספק" in homework["text"]
    assert "מטלה" not in text and homework["text"] not in text and seed["homework_he"] not in text
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
    first = {"agent": ["**קובץ**", "**תיקיית פרויקט**", "**טרמינל**"], "save": ["**[[commit]]**"], "loop": ["**[[diff]]**"]}
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
    assert "[[antigravity.google/docs]]" in text and "3 בנובמבר 2026" in text
    assert "[[antigravity.google/download]]" in text and "[[antigravity.google/docs/rules]]" in text
    assert "`AGENTS.md`" in text and "`GEMINI.md`" in text
    # Sign-in prerequisites as Google states them, cited; nothing about institutional accounts.
    prereq = json.dumps(lesson["steps"][0]["blocks"][0], ensure_ascii=False)
    assert "חשבון Google אישי" in prereq and "מגיל 18" in prereq and "[[antigravity.google/docs/faq]]" in prereq
    assert "מסלול חלופי" in prereq
    for word in ("מוסד", "של עבודה", "Workspace"):
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
    # Claude Code and Codex: a short comparison, nothing to install.
    wrap = json.dumps(lesson["steps"][-1], ensure_ascii=False)
    assert "Claude Code" in wrap and "Codex" in wrap and "לא נדרש להתקין" in wrap
    assert "Claude Code" not in json.dumps(lesson["steps"][:-1], ensure_ascii=False)


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
    loop = json.dumps(next(s for s in lesson["steps"] if s["key"] == "loop"), ensure_ascii=False)
    assert "[[Staged Changes]]" in loop
    assert loop.index("[[Unstage change]]") < loop.index("[[Discard unstaged changes]]")
