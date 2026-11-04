"""Lesson 6 of the 42052 plan ("building a skeleton that works end to end"),
authored in this repository from its seed: no answer key in any committed
file, the seed's checks and texts kept verbatim, the step contract (one goal,
explain, one action, check, next), two downloadable templates whose sha256 is
in the assets, agent prompts that plan first and ask for evidence, no chatbot
task at all, and every GitHub/Antigravity instruction cited to the docs
checked on the build date.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, assets_root, course_plan, load_fixture, load_plan, validate_content

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SEED = REPO / "content" / "course-42052" / "lessons" / "lesson-06.json"
MATERIALS = REPO / "content" / "course-42052" / "materials" / "lesson-06"
SERVED = ASSETS_ROOT / "lessons" / "lesson-06" / "v1"
CHECKED = "נבדק ב-3 בנובמבר 2026"

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


def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


@pytest.fixture(scope="module")
def lesson() -> dict:
    return load_fixture("42052-lesson-06")


def test_lesson_6_is_authored_valid_and_its_templates_match(lesson):
    assert "lesson-06" in course_plan.AUTHORED
    content = validate_content(lesson, assets_root())  # both files exist with the declared sha256
    assert (content.slug, content.course_code) == ("lesson-06", "42052")
    assert [s.key for s in content.steps] == ["slice", "structure", "version", "run", "wrap-up"]
    expected = {"readme_template": "README.md", "git_routine": "team-git-routine.md"}
    assert {k: a["filename"] for k, a in lesson["assets"].items()} == expected
    for key, name in expected.items():
        asset = lesson["assets"][key]
        assert (asset["path"], asset["mime"]) == (f"/lessons/lesson-06/v1/{name}", "text/markdown")
        served = (SERVED / name).read_bytes()
        assert asset["sha256"] == hashlib.sha256(served).hexdigest(), name
        assert served == (MATERIALS / name).read_bytes(), name  # the served file is the committed source
    downloads = {b["asset"]: s["key"] for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "download"}
    assert downloads == {"readme_template": "structure", "git_routine": "version"}


def test_no_answer_key_in_any_committed_lesson_6_file(lesson):
    leaked = PRIVATE_FIELDS & _keys_in(lesson)
    assert not leaked, sorted(leaked)
    leaked = PRIVATE_FIELDS & _keys_in(load_plan("42052")["lessons"]["lesson-06"])
    assert not leaked, sorted(leaked)
    for path in MATERIALS.iterdir():
        text = path.read_text(encoding="utf-8")
        for marker in ("correct_choice_id", "feedback_he", "l06-", "lesson-06-exit"):
            assert marker not in text, (path.name, marker)
    for key, question in lesson["questions"].items():
        assert "answer" not in question, key
        if question["type"] == "single_choice":
            assert question["mode"] == "check", key


def test_the_seed_checks_and_texts_survive_unchanged(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    generated = course_plan.seed_to_content(seed, "42052")
    assert set(generated["questions"]) == {"l06-q1", "l06-q2", "l06-q3", "lesson-06-exit"}
    for key, question in generated["questions"].items():
        assert lesson["questions"][key] == question, key
    for step in generated["steps"]:
        assert _step(lesson, step["key"])["title"] == step["title"], step["key"]
    plain = _dump(lesson).replace("**", "")
    for field in ("worked_example_he", "work_product_he"):
        assert course_plan.ltr(seed[field]) in plain, field
    # The seed's teaching sentences stay where the seed put them.
    for step in seed["steps"]:
        assert course_plan.ltr(step["understand_he"]).split(";")[0].split(".")[0] in plain, step["key"]
    assert seed["optional_extension_he"] is None
    # The concrete exit check (operator, 2026-11-03), pinned: same id, the
    # seed's new wording, its section title and helper line.
    assert seed["exit_check_he"] == "באיזו פקודה מריצים את השלד שלכם, ומה קרה כשחבר צוות אחר הריץ אותו לפי ה-README?"
    assert lesson["questions"]["lesson-06-exit"]["prompt"] == course_plan.ltr(seed["exit_check_he"])
    exit_section = next(b for b in _step(lesson, "wrap-up")["blocks"]
                        if any(x.get("question") == "lesson-06-exit" for x in b.get("blocks", [])))
    assert exit_section["title"] == "לסיום: במילים שלכם"
    assert exit_section["blocks"][0]["body"] == [
        "תשובה קצרה, משפט או שניים. אין כאן ציון – זה עוזר לכם (ולמרצה) לראות מה התבהר."]


def test_the_homework_stays_a_proposal_for_the_instructor_only(lesson):
    homework = load_plan("42052")["lessons"]["lesson-06"]["homework"]
    assert homework == {"status": "proposal_not_yet_assigned", "text": "שלד עובד + README + קישור למאגר"}
    text = _dump(lesson)
    assert "מטלה" not in text and homework["text"] not in text
    helper = "אין כאן ציון"
    assert text.count("ציון") == text.count(helper)  # the only mention says there is no grade
    for word in ("deadline", "מועד הגשה", "משקל", "להגיש", "הגשה"):
        assert word not in text, word


def test_every_step_has_one_goal_an_explanation_one_action_a_check_and_a_next_step(lesson):
    for step in lesson["steps"]:
        assert step.get("goal"), step["key"]
        sections = [b for b in step["blocks"] if b["type"] == "section"]
        assert sections[0]["label"] == "understand" and any(s["label"] == "check" for s in sections), step["key"]
        assert step["completion"], step["key"]
        if step["key"] == "wrap-up":
            continue
        assert step.get("next_hint"), step["key"]
        tries = [s for s in sections if s["label"] == "try"]
        assert len(tries) == 1, step["key"]
        assert tries[0]["blocks"][0]["body"][0].startswith("**הפעולה:**"), step["key"]
        actions = [b for b in _all_blocks(step["blocks"]) if b["type"] == "text" and b["body"][0].startswith("**הפעולה:**")]
        assert len(actions) == 1, step["key"]
        for block in _all_blocks(step["blocks"]):
            if block["type"] == "expander":
                assert block["title"].startswith(("רשות", "מסלול חלופי")), block["title"]
    assert "בצוות הפרויקט" in _dump(lesson["steps"][0]["blocks"][0])


def test_concepts_are_explained_before_they_are_used(lesson):
    def understand(step):
        return _dump(next(b for b in step["blocks"] if b.get("label") == "understand"))

    first = {
        "slice": ["**שלד**", "**פרוסה אנכית** ([[vertical slice]])", "**[[stub]]**"],
        "structure": ["**תיקיות**", "**קובץ כניסה**", "**קובץ תלויות**", "**תלות**", "**פקודת הרצה**", "**[[README]]**"],
        "version": ["**[[GitHub]]**", "**[[remote]]**", "**[[push]]**", "**[[pull]]**", "**[[clone]]**", "**קונפליקט**"],
    }
    keys = [s["key"] for s in lesson["steps"]]
    for key, words in first.items():
        for word in words:
            assert word in understand(_step(lesson, key)), (key, word)
    # Not used in an earlier step (next-step hints and prerequisites aside).
    later = {"[[stub]]": "slice", "[[push]]": "version", "[[pull]]": "version", "[[clone]]": "version",
             "[[remote]]": "version", "קונפליקט": "version", "package.json": "structure", "קובץ התלויות": "structure",
             "ענף": "version"}
    for word, home in later.items():
        for step in lesson["steps"][: keys.index(home)]:
            body = {k: v for k, v in step.items() if k != "next_hint"}
            body["blocks"] = [b for b in step["blocks"] if b.get("title") != "מה צריך לפני שמתחילים"]
            assert word not in _dump(body), (word, step["key"])


def test_the_ai_step_is_a_labelled_stub_with_no_live_api(lesson):
    slice_ = _dump(_step(lesson, "slice"))
    assert slice_.count("הדגמה ללא מודל חי") >= 3  # explained, in the example and asked of the agent
    assert "שיעור 7" in slice_
    text = _dump(lesson)
    for claim in ("₪", "$", "USD", "מכסת", "לחודש", "בחינם", "quota", "rate limit", "Pro ", "Ultra"):
        assert claim not in text, claim
    scaffold = next(b for b in _all_blocks(_step(lesson, "slice")["blocks"]) if b["type"] == "prompt")
    assert "בלי מפתח API" in scaffold["text"] and "stub" in scaffold["text"] and "«הדגמה ללא מודל חי»" in scaffold["text"]


def test_prompts_are_agent_requests_with_a_purpose_plan_first_and_evidence(lesson):
    """Operator rule 2026-11-03: no chatbot task without a reason. This lesson
    has none: every prompt is a request to the coding agent, says why, and
    acting ones plan first and ask for evidence."""
    prompts = [b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "prompt"]
    assert len(prompts) == 5
    titles = [p["title"] for p in prompts]
    assert all(t.startswith("בקשה לסוכן:") for t in titles), titles
    assert "צ׳טבוט" not in _dump(lesson)
    for p in prompts:
        assert p["text"].strip() and p.get("note"), p["title"]
        assert "[הדביקו" not in p["text"] and "http" not in p["text"]
        assert re.search(r"(הצג|הראה|הדבק)", p["text"]), p["title"]
        assert "--force" not in p["text"] or "אל תשתמש ב---force" in p["text"], p["title"]
    by_title = {p["title"]: p["text"] for p in prompts}
    for title in ("בקשה לסוכן: שלד לפי האפיון, תוכנית קודם", "בקשה לסוכן: חיבור למאגר ודחיפה ראשונה",
                  "בקשה לסוכן: עותק, שינוי אחד ודחיפה", "בקשה לסוכן: README רק ממה שהורץ"):
        assert by_title[title].startswith("/plan "), title
    scaffold = by_title["בקשה לסוכן: שלד לפי האפיון, תוכנית קודם"]
    assert "SPEC.md" in scaffold and "AGENTS.md" in scaffold and "אל תשנה את SPEC.md" in scaffold
    assert scaffold.index("הצג תוכנית") < scaffold.index("בנה רק")
    assert "השווה את הפלט לתשובה הצפויה" in scaffold
    conflict = by_title["בקשה לסוכן: פתרון קונפליקט יחד"]
    assert "אל תפתור אותו לבד" in conflict and "diff" in conflict
    for title in ("בקשה לסוכן: חיבור למאגר ודחיפה ראשונה", "בקשה לסוכן: עותק, שינוי אחד ודחיפה"):
        assert "אל תבקש ממני סיסמה או טוקן" in by_title[title], title
    assert "git pull" in by_title["בקשה לסוכן: עותק, שינוי אחד ודחיפה"]
    # Reed N4: the README prompt says where the output goes.
    assert "את הפלט של כל פקודה הדבק כאן בשיחה, לא ב-README" in by_title["בקשה לסוכן: README רק ממה שהורץ"]
    # Reed N1: "ענף" (branch) is defined in the step before the prompts use it.
    version = _step(lesson, "version")
    understand = _dump(version["blocks"][0])
    assert "**ענף** ([[branch]])" in understand and "הענף" in by_title["בקשה לסוכן: חיבור למאגר ודחיפה ראשונה"]


def test_github_and_antigravity_steps_cite_the_docs_checked_on_the_build_date(lesson):
    version = _dump(_step(lesson, "version"))
    cited = {
        "[[antigravity.google/docs/permissions]]",
        "[[docs.github.com/en/get-started/git-basics/caching-your-github-credentials-in-git]]",
        "[[cli.github.com/manual/gh_auth_login]]",
        "[[docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository]]",
        "[[docs.github.com/en/repositories/working-with-files/managing-files/editing-files]]",
        "[[docs.github.com/en/pull-requests/collaborating-with-pull-requests/addressing-merge-conflicts/resolving-a-merge-conflict-using-the-command-line]]",
    }
    for source in cited:
        assert source in version, source
    # Each citation carries the date it was checked.
    for match in re.finditer(r"\[\[((?:docs\.github\.com|cli\.github\.com|antigravity\.google)/[^\]]+)\]\]", _dump(lesson)):
        tail = _dump(lesson)[match.end(): match.end() + 120]  # one date may close two paired sources
        assert CHECKED in tail, match.group(1)
    assert "`gh auth login`" in version and "[[HTTPS]]" in version
    # Reed B1: GitHub Desktop's sign-in does not authenticate the git the
    # agent runs in the terminal, so it is not offered; whoever can't sign in
    # with gh takes the labelled fallback (a teammate's session, the web editor).
    assert "Desktop" not in _dump(lesson)
    assert "לא מצליחים להתקין את [[GitHub CLI]] או להתחבר? עברו למסלול החלופי" in version
    assert "סיסמה של [[GitHub]] לא עובדת" in version
    # GitHub Education: an option, nothing promised.
    assert "[[GitHub Education]]" in version and "רשות" in version
    for claim in ("הטבות", "חינם", "free"):
        assert claim not in version, claim
    assert "http" not in _dump(lesson)


def test_the_git_routine_and_conflict_are_spelled_out(lesson):
    version = _step(lesson, "version")
    text = _dump(version)
    assert "**[[pull]] לפני [[push]]:**" in text
    conflict = next(b for b in _all_blocks(version["blocks"]) if b["type"] == "code")
    for marker in ("<<<<<<< HEAD", "=======", ">>>>>>>"):
        assert marker in conflict["code"], marker
    routine = (MATERIALS / "team-git-routine.md").read_text(encoding="utf-8")
    order = [routine.index(f"## {n}. {w}") for n, w in enumerate(["pull", "change", "run", "commit", "push"], 1)]
    assert order == sorted(order)
    assert "git push --force" in routine and "**אף פעם**" in routine
    assert "הענף המשותף (הענף הראשי, בדרך כלל `main`" in routine  # Reed N1: the branch is named where it is used
    # Fallbacks for a member who can't install or sign in.
    assert "מסלול חלופי" in text and "[[Edit file]]" in text and "[[Commit changes]]" in text


def test_the_readme_template_has_the_five_run_sections_and_no_secrets():
    template = (MATERIALS / "README.md").read_text(encoding="utf-8")
    headings = ["## Prerequisites", "## Install", "## Run", "## Test", "## Known limits", "## Structure"]
    positions = [template.index(h) for h in headings]
    assert positions == sorted(positions)
    assert "הדגמה ללא מודל חי" in template and "לעולם לא כותבים כאן סיסמה, מפתח API" in template
    for path in MATERIALS.iterdir():
        lowered = path.read_text(encoding="utf-8").lower()
        for secret in ("api_key=", "sk-", "password", "ghp_", "http"):
            assert secret not in lowered, (path.name, secret)


def test_single_choice_options_do_not_follow_a_longest_is_right_pattern(lesson):
    seed_keys = {"l06-q1", "l06-q2", "l06-q3"}
    new = [q for k, q in lesson["questions"].items() if q["type"] == "single_choice" and k not in seed_keys]
    assert len(new) >= 5
    longest_positions = set()
    for q in new:
        lengths = [len(o["text"]) for o in q["options"]]
        assert len(lengths) == 3 and len(set(lengths)) == 3, q["key"]
        longest_positions.add(lengths.index(max(lengths)))
    assert len(longest_positions) >= 2
