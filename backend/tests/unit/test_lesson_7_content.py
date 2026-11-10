"""Lesson 7 of the 42052 plan ("connecting an AI capability to the product"),
authored in this repository from its seed: the committed content carries no
answer key, keeps the seed's checks and texts verbatim, follows the step
contract (one goal, explain, act, check, next), cites Google's docs with the
date they were checked, and ships a reference implementation whose mock check
runs with no network and no key (`node check.js`, here and in CI).
"""

from __future__ import annotations

import hashlib
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
SEED = REPO / "content" / "course-42052" / "lessons" / "lesson-07.json"
ORDERS = REPO / "content" / "course-42052" / "fixtures" / "bakery-orders.json"
CASES = REPO / "content" / "course-42052" / "fixtures" / "product-test-cases.json"
REFERENCE_SRC = REPO / "content" / "course-42052" / "materials" / "lesson-07" / "bakery-ai-reference"
REFERENCE_ZIP = ASSETS_ROOT / "lessons" / "lesson-07" / "v1" / "bakery-ai-reference.zip"
ENV_EXAMPLE = ASSETS_ROOT / "lessons" / "lesson-07" / "v1" / "env.example"

PRIVATE_FIELDS = {"answer", "correct_choice_id", "feedback_he", "correct", "correct_options", "misconceptions",
                  "explanation", "sample_reasoning", "rubric", "instructor_email", "email"}
SEED_CHECKS = {"l07-q1", "l07-q2", "l07-q3"}
CHECKED = "נבדק ב-4 בנובמבר 2026"
MODEL = "gemini-3.5-flash-lite"
MOCK_LABEL = "הדגמה ללא מודל חי"


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


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _understand(step: dict) -> str:
    return _dump(next(b for b in step["blocks"] if b.get("label") == "understand"))


@pytest.fixture(scope="module")
def lesson() -> dict:
    return load_fixture("42052-lesson-07")


def _build_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location("build_lesson_7_reference", BACKEND / "scripts" / "build_lesson_7_reference.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lesson_7_is_authored_valid_and_its_downloads_match(lesson):
    assert "lesson-07" in course_plan.AUTHORED
    content = validate_content(lesson, assets_root())  # both downloads exist with the declared sha256
    assert (content.slug, content.course_code) == ("lesson-07", "42052")
    assert [s.key for s in content.steps] == ["contract", "secrets", "output", "failure", "wrap-up"]
    zipped, env = lesson["assets"]["reference_zip"], lesson["assets"]["env_example"]
    assert (zipped["path"], zipped["filename"], zipped["mime"]) == (
        "/lessons/lesson-07/v1/bakery-ai-reference.zip", "bakery-ai-reference.zip", "application/zip")
    assert (env["path"], env["filename"], env["mime"]) == ("/lessons/lesson-07/v1/env.example", "env.example", "text/plain")
    assert zipped["sha256"] == hashlib.sha256(REFERENCE_ZIP.read_bytes()).hexdigest()
    assert env["sha256"] == hashlib.sha256(ENV_EXAMPLE.read_bytes()).hexdigest()
    # The served files are the build of the committed source, byte for byte.
    assert _build_script().main(["--check"]) == 0
    assert ENV_EXAMPLE.read_bytes() == (REFERENCE_SRC / ".env.example").read_bytes()
    with zipfile.ZipFile(REFERENCE_ZIP) as archive:
        names = archive.namelist()
    assert "bakery-ai-reference/.env.example" in names and "bakery-ai-reference/check.js" in names
    assert not any(n.endswith("/.env") or "node_modules" in n for n in names)
    # Where each is offered: .env.example with the key (B), the reference to compare with (C, optional).
    downloads = {s["key"]: [b["asset"] for b in _all_blocks(s["blocks"]) if b["type"] == "download"] for s in lesson["steps"]}
    assert downloads == {"contract": [], "secrets": ["env_example"], "output": ["reference_zip"], "failure": [], "wrap-up": []}


def test_no_answer_key_in_any_committed_lesson_7_file(lesson):
    """The repository is public: the fixture, its plan entry and the reference
    implementation carry questions only, never a key or private feedback."""
    assert not PRIVATE_FIELDS & _keys_in(lesson), sorted(PRIVATE_FIELDS & _keys_in(lesson))
    plan_entry = load_plan("42052")["lessons"]["lesson-07"]
    assert not PRIVATE_FIELDS & _keys_in(plan_entry)
    for path in REFERENCE_SRC.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            for marker in ("correct_choice_id", "feedback_he", "l07-", "lesson-07-exit"):
                assert marker not in text, (path.name, marker)
    for key, question in lesson["questions"].items():
        assert "answer" not in question, key
        if question["type"] == "single_choice":
            assert question["mode"] == "check", key  # no reveal before a first answer


def test_the_seed_checks_and_texts_survive_unchanged(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    generated = course_plan.seed_to_content(seed, "42052")
    assert set(generated["questions"]) == SEED_CHECKS | {"lesson-07-exit"}
    # Same key, wording, type, mode and options, so a key file written against
    # the seed fits the authored lesson.
    for key in ("l07-q1", "l07-q2", "lesson-07-exit"):
        assert lesson["questions"][key] == generated["questions"][key], key
    # l07-q3 (tool calling) is asked where tool calling is taught: step C,
    # "output". Only its step moved.
    assert lesson["questions"]["l07-q3"] == {**generated["questions"]["l07-q3"], "step": "output"}
    # The seed's step titles stay, under the same keys.
    for step in generated["steps"]:
        assert _step(lesson, step["key"])["title"] == step["title"], step["key"]
    plain = _dump(lesson).replace("**", "")
    for field in ("worked_example_he", "work_product_he"):
        assert course_plan.ltr(seed[field]) in plain, field
    # The exit section exactly as the seed builds it (the concrete prompt from #47).
    gen_wrap = next(s for s in generated["steps"] if s["key"] == "wrap-up")
    exit_section = next(b for b in gen_wrap["blocks"] if b.get("label") == "check")
    assert exit_section in _step(lesson, "wrap-up")["blocks"]
    assert exit_section["title"] == "לסיום: במילים שלכם"
    assert seed["optional_extension_he"] is None


def test_the_homework_stays_a_proposal_for_the_instructor_only(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    assert seed["homework_status"] == "proposal_not_yet_assigned"
    homework = load_plan("42052")["lessons"]["lesson-07"]["homework"]
    assert homework == {"status": "proposal_not_yet_assigned", "text": "תכונת AI אחת מקצה לקצה + בדיקת פלט + תרחיש כשל"}
    text = _dump(lesson)
    assert "מטלה" not in text and homework["text"] not in text and seed["homework_he"] not in text
    assert text.count(course_plan.EXIT_CHECK_HELP) == 1
    text = text.replace(course_plan.EXIT_CHECK_HELP, "")
    for word in ("deadline", "מועד הגשה", "משקל", "ציון", "אחוז"):
        assert word not in text and word not in homework["text"], word


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
        required = [s for s in sections if s["label"] == "try" and "רשות" not in s.get("title", "")]
        assert len(required) == 1, step["key"]
        action = required[0]["blocks"][0]
        assert action["type"] == "text" and action["body"][0].startswith("**הפעולה:**"), step["key"]
        assert sum(b["body"][0].startswith("**הפעולה:**") for b in _all_blocks(step["blocks"]) if b["type"] == "text") == 1
        for block in _all_blocks(step["blocks"]):
            if block["type"] == "expander":
                assert block["title"].startswith(("רשות", "מסלול חלופי")), block["title"]
    assert "בצוות הפרויקט" in _dump(lesson["steps"][0]["blocks"][0])
    assert "צוות" in lesson["intro"]
    # No Colab block, and no chatbot task: every prompt is a request to the agent.
    assert not any(b["type"] == "colab" for s in lesson["steps"] for b in _all_blocks(s["blocks"]))
    assert "צ׳טבוט" not in _dump(lesson)


def test_concepts_are_explained_before_they_are_used(lesson):
    first = {
        "contract": ["**[[API]]**", "**בקשה** ([[request]])", "**[[JSON]]**", "**סכימה** ([[schema]])",
                     "**פלט מובנה** ([[structured output]])", "`null` פירושו", "**[[JSON]] תקין אינו תוכן נכון.**"],
        "secrets": ["**מפתח [[API]]**", "**משתנה סביבה** ([[environment variable]])", "**`.env`**",
                    "**`.gitignore`**", "**`.env.example`**"],
        "output": ["**בדיקה** ([[validation]])", "**הוראה בתוך הנתונים**", "**קריאה לכלי** ([[function calling]]",
                   "**המודל מציע פעולה; השרת שלכם מחליט ומרשה.**"],
        "failure": ["**קוד שגיאה**", "`429`", "**זמן קצוב** ([[timeout]])", "**מגבלת קצב** ([[rate limit]])",
                    "**ניסיון חוזר מוגבל** ([[retry]])", "**מתג כשל מסומן**"],
    }
    keys = [s["key"] for s in lesson["steps"]]
    for key, words in first.items():
        for word in words:
            assert word in _understand(_step(lesson, key)), (key, word)
    later = {"[[schema]]": "contract", "`.gitignore`": "secrets", "`.env`": "secrets", "[[validation]]": "output",
             "[[function calling]]": "output", "[[timeout]]": "failure", "[[retry]]": "failure",
             "AI_FORCE_ERROR": "failure", "`429`": "failure"}
    for word, home in later.items():
        for step in lesson["steps"][: keys.index(home)]:
            body = {k: v for k, v in step.items() if k != "next_hint"}
            assert word not in _dump(body), (word, step["key"])


def test_google_facts_cite_the_docs_and_the_date_and_name_no_numbers(lesson):
    text = _dump(lesson)
    secrets = _dump(_step(lesson, "secrets"))
    for page in ("aistudio.google.com/apikey", "aistudio.google.com/docs/api-key", "aistudio.google.com/docs/available-regions",
                 "aistudio.google.com/docs/terms", "aistudio.google.com/docs/libraries", "aistudio.google.com/docs/models",
                 "aistudio.google.com/docs/structured-output", "aistudio.google.com/docs/rate-limits"):
        assert page in secrets, page
    for page in ("aistudio.google.com/docs/function-calling", "aistudio.google.com/docs/api-errors"):
        assert page in text, page
    assert "**מה בדקנו בתיעוד של Google (4 בנובמבר 2026):**" in secrets and text.count(CHECKED) >= 6
    # The facts themselves.
    assert "ישראל ברשימת האזורים" in secrets and "מגיל 18 ומעלה" in secrets
    assert "[[@google/genai]]" in secrets and "[[google-genai]]" in secrets
    assert f"`{MODEL}`" in secrets and "שמות מתחלפים" in secrets
    assert "`response_format`" in secrets and "application/json" in secrets
    # Free tier: the data may be used to improve Google's products, so synthetic data only.
    assert "משמש לשיפור המוצרים של Google" in secrets and "רק נתונים בדויים" in secrets
    assert "אף פעם לא הודעות של לקוחות אמיתיים" in secrets
    # No pricing or quota numbers: limits change, read them in AI Studio.
    assert "משתנות עם הזמן" in secrets
    for claim in ("₪", "$", "USD", "RPM", "RPD", "TPM", "לחודש", "בחינם", "http"):
        assert claim not in text, claim
    assert not re.search(r"\d+\s*(בקשות|requests|tokens)", text)
    # The lesson, the reference and its .env.example name the same model.
    assert f"GEMINI_MODEL={MODEL}" in (REFERENCE_SRC / ".env.example").read_text(encoding="utf-8")
    assert f'"{MODEL}"' in (REFERENCE_SRC / "src" / "extract.js").read_text(encoding="utf-8")


def test_agent_prompts_plan_first_keep_the_key_out_and_ask_for_evidence(lesson):
    prompts = {b["title"]: b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "prompt"}
    assert len(prompts) == 4
    for p in prompts.values():
        assert p["text"].startswith("/plan ") and p.get("note"), p["title"]
        assert "חכה לאישור" in p["text"] and ("diff" in p["text"] or "git status" in p["text"]), p["title"]
        assert "http" not in p["text"] and "[הדביקו" not in p["text"]
        assert re.search(r"[֐-׿]", p["text"]), p["title"]  # Hebrew
    wire = prompts["בקשה לסוכן: קריאה אחת מהשרת במקום ה-stub"]["text"]
    for rule in ("אל תכתוב את המפתח בקוד", "ואל תבקש אותו ממני בשיחה", "אל תפתח ואל תציג את .env",
                 "הקריאה יוצאת רק מהשרת", "@google/genai", "פלט מובנה", "בדוק בתיעוד הנוכחי של Google",
                 MOCK_LABEL, "לעולם אל תציג תשובה קבועה כאילו היא מהמודל", ".gitignore", "אל תתקין כלום בלי לשאול",
                 "הדבק את הפלט", "כתוב אם הוא הגיע מהמודל או מההדמיה"):
        assert rule in wire, rule
    contract = prompts["בקשה לסוכן: חוזה ה-AI ב-SPEC.md, בלי קוד"]["text"]
    assert "אל תכתוב קוד" in contract and "pickup_time: null, needs_clarification: true" in contract
    check = prompts["בקשה לסוכן: בדיקת הפלט בשרת"]["text"]
    for rule in ("quantity מספר שלם גדול מ-0", "אל תציג את ההזמנה", "בלי רשת ובלי מפתח", "הדבק את הפלט"):
        assert rule in check, rule
    fail = prompts["בקשה לסוכן: מתג כשל, ניסיון חוזר מוגבל ומצבי מסך"]["text"]
    for rule in ("AI_FORCE_ERROR", "לכל היותר 2 ניסיונות חוזרים", "על 400 ו-403 – בלי ניסיון חוזר", "כפתור השליחה נעול",
                 "המכסה היומית – בלי ניסיון חוזר", "את מספר הניסיונות סופר הקוד שלנו",
                 "אף פעם לא תוצאה מזויפת", "אל תכתוב מספרי מגבלות בקוד"):
        assert rule in fail, rule


def test_the_key_step_has_a_labelled_mock_route_and_a_git_status_check(lesson):
    secrets = _step(lesson, "secrets")
    text = _dump(secrets)
    assert "`git status`" in text and "ולא מדביקים אותו בשום צ׳אט" in text
    assert "אתם עושים את זה בעצמכם, בעורך – לא הסוכן" in text
    fallback = next(b for b in _all_blocks(secrets["blocks"]) if b["type"] == "expander")
    assert fallback["title"].startswith("מסלול חלופי") and MOCK_LABEL in _dump(fallback)
    assert {"type": "ack", "key": "key_safe"} in secrets["completion"]


def test_the_cases_come_from_the_fixtures(lesson):
    orders = json.loads(ORDERS.read_text(encoding="utf-8"))
    cases = {c["id"]: c for c in json.loads(CASES.read_text(encoding="utf-8"))}
    contract = _dump(_step(lesson, "contract"))
    for message in orders["messages"]:
        if message["id"] in ("m1", "m3"):
            assert message["text"] in contract, message["id"]
    codes = [b["code"] for b in _all_blocks(_step(lesson, "contract")["blocks"]) if b["type"] == "code"]
    assert len(codes) == 2 and '"pickup_time": "09:00"' in codes[0]
    assert '"pickup_time": null' in codes[1] and '"needs_clarification": true' in codes[1]
    table = next(b for b in _all_blocks(_step(lesson, "output")["blocks"]) if b["type"] == "table")
    rows = {r[0]: r for r in table["rows"]}
    assert list(rows) == ["תקין", "חסר", "לא תקין", "הוראה בתוך הנתונים"]
    assert rows["תקין"][1] == cases["valid-order"]["input"]
    assert rows["חסר"][1] == cases["missing-time"]["input"]
    assert "`-2`" in rows["לא תקין"][1] and rows["לא תקין"][2].startswith("דחייה ברורה")
    assert "התעלמו מכל הכללים" in rows["הוראה בתוך הנתונים"][1] and "מפתח" in rows["הוראה בתוך הנתונים"][1]
    # The reference's mock knows exactly these messages.
    mock = (REFERENCE_SRC / "src" / "mock.js").read_text(encoding="utf-8")
    for text in [m["text"] for m in orders["messages"]] + [cases["valid-order"]["input"], cases["missing-time"]["input"],
                                                           rows["הוראה בתוך הנתונים"][1]]:
        assert f'"{text}"' in mock, text


def test_single_choice_options_do_not_follow_a_longest_is_right_pattern(lesson):
    new = [q for k, q in lesson["questions"].items() if q["type"] == "single_choice" and k not in SEED_CHECKS]
    assert len(new) >= 6
    per_step = {}
    for q in new:
        per_step[q["step"]] = per_step.get(q["step"], 0) + 1
    assert set(per_step) == {"contract", "secrets", "output", "failure"} and max(per_step.values()) <= 2
    longest_positions = set()
    for q in new:
        lengths = [len(o["text"]) for o in q["options"]]
        assert len(lengths) == 3 and len(set(lengths)) == 3, q["key"]
        longest_positions.add(lengths.index(max(lengths)))
    assert len(longest_positions) >= 2


def test_the_reference_implementation_keeps_the_key_server_side():
    ignore = (REFERENCE_SRC / ".gitignore").read_text(encoding="utf-8").split()
    assert ".env" in ignore and "node_modules/" in ignore
    env = (REFERENCE_SRC / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^GEMINI_API_KEY=$", env, re.M) and re.search(r"^AI_FORCE_ERROR=$", env, re.M)
    for path in (REFERENCE_SRC / "public").iterdir():
        text = path.read_text(encoding="utf-8")
        for word in ("GEMINI", "genai", "API_KEY", "googleapis"):
            assert word not in text, (path.name, word)
    extract = (REFERENCE_SRC / "src" / "extract.js").read_text(encoding="utf-8")
    assert "process.env.GEMINI_API_KEY" in extract
    # The retry cap is ours: one HTTP request per attempt, enforced by our own fetch, and no SDK retries.
    assert "httpOptions: { fetch: oneRequestOnly }" in extract and "maxRetries: 0" in extract
    assert '"@google/genai": "2.32.0"' in (REFERENCE_SRC / "package.json").read_text(encoding="utf-8")  # pinned: the version tested
    server = (REFERENCE_SRC / "server.js").read_text(encoding="utf-8")
    assert "s.key" not in server  # the start-up line names the mode and model, never the key
    app = (REFERENCE_SRC / "public" / "app.js").read_text(encoding="utf-8")
    assert "button.disabled = true" in app and "if (busy) return" in app and "data.label" in app


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail("node is needed to run the reference implementation's check")
        pytest.skip("node is not installed")
    return node


def _run_check(folder: Path):
    env = {k: v for k, v in os.environ.items() if not k.endswith("_PROXY") and not k.endswith("_proxy")}
    # A key in the environment is ignored: the check is always the mock.
    env |= {"GEMINI_API_KEY": "not-a-real-key", "AI_MODE": "live", "AI_FORCE_ERROR": "503"}
    return subprocess.run([_node(), "check.js"], cwd=folder, capture_output=True, text=True, timeout=60, env=env)


def test_the_reference_check_runs_offline_with_the_mock_and_prints_the_documented_output(tmp_path):
    """Unzipped as a student would, with no `npm install`, no network and no
    key, `node check.js` prints exactly what the README documents; and it
    fails when the quantity rule is removed."""
    with zipfile.ZipFile(REFERENCE_ZIP) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / "bakery-ai-reference"
    assert not (folder / "node_modules").exists()
    run = _run_check(folder)
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.startswith("mode: mock (no network, no key)\n")
    assert run.stdout.rstrip("\n").endswith("15 of 15 checks passed")
    assert f"```\n{run.stdout}```" in (folder / "README.md").read_text(encoding="utf-8")

    validate = folder / "src" / "validate.js"
    validate.write_text(validate.read_text(encoding="utf-8").replace("item.quantity <= 0", "item.quantity < -100"), encoding="utf-8")
    broken = _run_check(folder)
    assert broken.returncode == 1
    assert "FAIL invalid-quantity: valid JSON with quantity -2 is rejected" in broken.stdout
    assert "14 of 15 checks passed" in broken.stdout
