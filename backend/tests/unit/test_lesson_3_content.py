"""Lesson 3 of the 42052 plan ("how language models work"), authored in this
repository from its seed: the committed content carries no answer key, keeps
the seed's checks and texts, follows the step contract (one goal, explain,
act, check, next), and its notebook ships as a clean student copy plus an
executed copy of the same cells.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, assets_root, course_plan, load_fixture, load_plan, validate_content

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SEED = REPO / "content" / "course-42052" / "lessons" / "lesson-03.json"
NOTEBOOK_DIR = ASSETS_ROOT / "lessons" / "lesson-03" / "v1"
STUDENT_NB = NOTEBOOK_DIR / "lesson-3-language-models-he.ipynb"
EXECUTED_NB = NOTEBOOK_DIR / "lesson-3-language-models-he-executed.ipynb"

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


@pytest.fixture(scope="module")
def lesson() -> dict:
    return load_fixture("42052-lesson-03")


def test_lesson_3_is_authored_valid_and_its_assets_match(lesson):
    assert "lesson-03" in course_plan.AUTHORED
    content = validate_content(lesson, assets_root())  # asset files exist with the declared sha256
    assert (content.slug, content.course_code) == ("lesson-03", "42052")
    assert [s.key for s in content.steps] == ["tokens", "next-token", "attention", "grounding", "wrap-up"]


def test_no_answer_key_in_any_committed_lesson_3_file(lesson):
    """The repository is public: the fixture, its plan entry and both
    notebooks carry questions only, never a key or private feedback."""
    leaked = PRIVATE_FIELDS & _keys_in(lesson)
    assert not leaked, sorted(leaked)
    leaked = PRIVATE_FIELDS & _keys_in(load_plan("42052")["lessons"]["lesson-03"])
    assert not leaked, sorted(leaked)
    for path in (STUDENT_NB, EXECUTED_NB):
        text = path.read_text(encoding="utf-8")
        for marker in ("correct_choice_id", "feedback_he", '"correct"', "l03-q", "lesson-03-exit"):
            assert marker not in text, f"{path.name}: {marker}"
    # Every question exists without a key: single choice ones need the private file.
    for key, question in lesson["questions"].items():
        assert "answer" not in question, key
        if question["type"] == "single_choice":
            assert question["mode"] == "check", key  # no reveal before a first answer


def test_the_seed_checks_and_texts_survive_unchanged(lesson):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    generated = course_plan.seed_to_content(seed, "42052")
    # The seed's three checks and the exit check: same key, step, wording and options,
    # so a key file written against the seed fits the authored lesson too.
    # l03-q2's wording was corrected in review (it spoke of "two sentences"
    # while the step is about word representations); its key, step, mode and
    # option ids are the seed's, so a key file written against the seed fits.
    revised = {"l03-q2"}
    for key, question in generated["questions"].items():
        mine = lesson["questions"][key]
        if key in revised:
            same = ("key", "step", "mode", "type")
            assert {k: mine[k] for k in same} == {k: question[k] for k in same}, key
            assert [o["id"] for o in mine["options"]] == [o["id"] for o in question["options"]], key
        else:
            assert mine == question, key
    text = json.dumps(lesson, ensure_ascii=False)
    plain = text.replace("**", "")  # the authored copy adds bold
    assert seed["worked_example_he"] in plain
    assert course_plan.ltr(seed["work_product_he"]) in plain
    # The seed's optional extension is a note to the instructor (an API demo
    # with a teaching account): not shown to students (Reed N3). The wrap-up
    # points at the optional "go deeper" lesson instead.
    assert course_plan.ltr(seed["optional_extension_he"]) not in plain
    assert "להעמיק" in json.dumps(lesson["steps"][-1], ensure_ascii=False)
    # The homework is a proposal: kept in the instructor's plan, never in the lesson.
    assert seed["homework_status"] == "proposal_not_yet_assigned"
    assert load_plan("42052")["lessons"]["lesson-03"]["homework"]["text"] == seed["homework_he"]
    assert "מטלה" not in text and seed["homework_he"] not in text
    for word in ("deadline", "מועד הגשה", "משקל בציון", "ציון"):
        assert word not in text


def test_every_step_has_one_goal_an_explanation_an_action_a_check_and_a_next_step(lesson):
    steps = lesson["steps"]
    for i, step in enumerate(steps):
        assert step.get("goal"), step["key"]
        labels = [b["label"] for b in step["blocks"] if b["type"] == "section"]
        assert labels[0] == "understand" and "check" in labels, step["key"]
        if step["key"] != "wrap-up":
            assert "try" in labels, step["key"]
            assert step.get("next_hint"), step["key"]
        assert step["completion"], step["key"]
    # The worked example: quantity 3 and cookies kept, pickup time left missing.
    grounding = json.dumps(steps[3], ensure_ascii=False)
    assert "דוגמה פתורה" in grounding
    code = next(b for s in steps[3]["blocks"] if s["type"] == "section" for b in s["blocks"] if b["type"] == "code")
    example = json.loads(code["code"])
    assert (example["quantity"], example["product"], example["pickup_time"]) == (3, "עוגיות", None)
    assert example["missing"] == ["pickup_time"] and example["pickup_day"] == "מחר"


def test_chatbot_exercises_show_exactly_what_to_paste(lesson):
    prompts = [b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "prompt"]
    assert len(prompts) >= 4
    for p in prompts:
        assert p["text"].strip() and p.get("note"), p["title"]
        assert "[הדביקו" not in p["text"]  # complete: nothing left to fill in
    rules = next(p for p in prompts if "כללים" in p["title"])
    assert rules["text"].rstrip().endswith("מיכל רוצה שלוש עוגיות למחר")
    assert "null" in rules["text"] and "missing" in rules["text"]


def test_no_fake_colab_link_and_no_paid_or_keyed_service(lesson):
    text = json.dumps(lesson, ensure_ascii=False)
    assert not re.search(r"colab\.research\.google\.com/(drive|github|notebooks)", text)
    assert "http" not in text
    colab = [b for s in lesson["steps"] for b in _all_blocks(s["blocks"]) if b["type"] == "colab"]
    assert colab and all(b["notebook_asset"] == "notebook" for b in colab)  # download, then upload to Colab
    for path in (STUDENT_NB, EXECUTED_NB):
        nb = path.read_text(encoding="utf-8")
        for secret in ("api_key", "OPENAI_API_KEY", "sk-", "userdata.get", "HF_TOKEN ="):
            assert secret not in nb, f"{path.name}: {secret}"


def test_no_absolute_workspace_path_in_any_lesson_3_file(lesson):
    """COURSE-HANDOFF §5: no stale absolute workspace paths. Executed outputs
    (warnings, tracebacks) are where they slip in."""
    files = [STUDENT_NB, EXECUTED_NB, BACKEND / "app" / "lessons" / "content" / "course-42052" / "lesson-03.json"]
    files += sorted(NOTEBOOK_DIR.glob("*"))
    for path in dict.fromkeys(files):
        text = path.read_text(encoding="utf-8")
        for marker in ("/tmp/", "/home/", "/root/", "/Users/", "scratchpad", "site-packages", "C:\\"):
            assert marker not in text, f"{path.name}: {marker}"


def _all_blocks(blocks):
    for block in blocks:
        yield block
        yield from _all_blocks(block.get("blocks", []))


def _sources(nb: dict) -> list[tuple[str, str]]:
    return [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]


def test_notebook_student_copy_is_clean_and_the_executed_copy_ran_the_same_cells():
    student = json.loads(STUDENT_NB.read_text(encoding="utf-8"))
    executed = json.loads(EXECUTED_NB.read_text(encoding="utf-8"))
    assert _sources(student) == _sources(executed)
    code_cells = [c for c in student["cells"] if c["cell_type"] == "code"]
    assert code_cells and all(c["outputs"] == [] and c["execution_count"] is None for c in code_cells)
    ran = [c for c in executed["cells"] if c["cell_type"] == "code"]
    assert [c["execution_count"] for c in ran] == list(range(1, len(ran) + 1))  # top to bottom, once
    for cell in ran:
        assert cell["outputs"], cell["id"]
        assert not [o for o in cell["outputs"] if o["output_type"] == "error"], cell["id"]
    # Markdown is Hebrew, right to left.
    for kind, source in _sources(student):
        if kind == "markdown":
            assert source.startswith('<div dir="rtl"') and re.search(r"[֐-׿]", source)


def test_notebook_labels_its_tokenizers_model_and_illustration():
    executed = json.loads(EXECUTED_NB.read_text(encoding="utf-8"))
    sources = "\n".join(s for _, s in _sources(executed))
    outputs = "\n".join(
        "".join(o.get("text", "")) for c in executed["cells"] if c["cell_type"] == "code" for o in c["outputs"]
    )
    # (a) real tokenizers, by name, on Hebrew and English.
    for name in ("o200k_base", "cl100k_base", "Qwen2.5"):
        assert re.search(rf"{re.escape(name)}\s+\d+ tokens", outputs), name
    assert "מיכל רוצה שלוש עוגיות למחר" in outputs and "Michal wants three cookies for tomorrow" in outputs
    # (b) next-token probabilities from a small open model, with honest limits.
    assert "Qwen/Qwen2.5-0.5B" in sources and "Loaded Qwen/Qwen2.5-0.5B" in outputs
    assert "לא</b> המודל של הצ׳טבוט שלכם" in sources
    # (c) the attention picture is an illustration, labeled as one.
    assert "ILLUSTRATION ONLY - hand-picked numbers, NOT measured from any model" in sources
    assert "המחשה רעיונית בלבד" in sources
    assert any("image/png" in o.get("data", {}) for c in executed["cells"] for o in c.get("outputs", []))


def test_review_corrections_stay_corrected(lesson):
    """Claims the adversarial review found wrong (lesson-3-review-fixes) are
    gone from the lesson and both notebooks."""
    texts = [json.dumps(lesson, ensure_ascii=False), STUDENT_NB.read_text(encoding="utf-8"), EXECUTED_NB.read_text(encoding="utf-8")]
    for text in texts:
        assert "פי עשרות ומאות" not in text  # chatbot model sizes are not published
        assert "עשרות «ראשי קשב»" not in text  # Qwen2.5-0.5B: 14 heads x 24 layers
    lesson_text = texts[0]
    assert "קיבלה את רוב ההסתברות" not in lesson_text  # 45.5% raw is the top, not a majority
    assert "14 «ראשי קשב» בכל אחת מ-24 השכבות" in lesson_text
    # The "74% of the four" quoted for the pickup prompt is the shipped number.
    data = json.loads((NOTEBOOK_DIR / "next-word.json").read_text(encoding="utf-8"))
    pickup = next(p for p in data["prompts"] if p["id"] == "pickup-he")
    assert round(next(c["share"] for c in pickup["candidates"] if c["word"] == "10:00") * 100) == 74
    assert "כ-74% מתוך ארבע האפשרויות" in lesson_text
    # One required action per step: the widget sections are marked optional.
    optional = [b for step in lesson["steps"] for b in step["blocks"] if b.get("title") == "רשות – נסו בעצמכם"]
    assert len(optional) == 3
