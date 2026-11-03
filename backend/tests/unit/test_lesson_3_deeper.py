"""Lesson 3's "go deeper" lesson (42052) and the interactive widget blocks:
the committed content carries no answer key, every illustration and measured
dataset is labeled at its source, the widget blocks are validated, the
notebook ships clean and executed, and the lesson is an optional draft
attached to session 3.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, ContentError, assets_root, load_fixture, load_plan, validate_content

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
DEEPER_DIR = ASSETS_ROOT / "lessons" / "lesson-03-deeper" / "v1"
L3_DIR = ASSETS_ROOT / "lessons" / "lesson-03" / "v1"
STUDENT_NB = DEEPER_DIR / "lesson-3-deeper-he.ipynb"
EXECUTED_NB = DEEPER_DIR / "lesson-3-deeper-he-executed.ipynb"
PRIVATE_FIELDS = {"answer", "correct_choice_id", "feedback_he", "correct", "correct_options", "misconceptions",
                  "explanation", "sample_reasoning", "rubric", "instructor_email", "email"}
WIDGETS = {"live_tokenizer", "next_word_guess", "attention_view", "neuron_playground", "training_demo", "embedding_map", "image"}


def _keys_in(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys_in(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys_in(v)}
    return set()


def _blocks(blocks):
    for b in blocks:
        yield b
        yield from _blocks(b.get("blocks") or [])


def _all_blocks(lesson: dict):
    for step in lesson["steps"]:
        yield from ((step["key"], b) for b in _blocks(step["blocks"]))


@pytest.fixture(scope="module")
def deeper() -> dict:
    return load_fixture("42052-lesson-03-deeper")


@pytest.fixture(scope="module")
def lesson3() -> dict:
    return load_fixture("42052-lesson-03")


def test_the_deeper_lesson_is_valid_optional_and_attached_to_session_3(deeper):
    content = validate_content(deeper, assets_root())  # asset files exist with their sha256
    assert content.enrichment is True and content.course_code == "42052"
    assert [s.key for s in content.steps] == ["neuron", "network", "embeddings", "transformer", "llm", "wrap-up"]
    sessions = load_plan("42052")["sessions"]
    assert sessions[2]["enrichment_fixture_keys"] == ["42052-lesson-03-deeper"]
    assert all(not s["enrichment_fixture_keys"] for s in sessions if s["session"] != 3)
    assert [s["session"] for s in sessions] == list(range(1, 14))  # nothing renumbered


def test_no_answer_key_in_any_committed_part_b_file(deeper):
    assert not PRIVATE_FIELDS & _keys_in(deeper)
    for key, q in deeper["questions"].items():
        assert "answer" not in q, key
        if q["type"] == "single_choice":
            assert q["mode"] == "check", key
    for path in [STUDENT_NB, EXECUTED_NB, L3_DIR / "next-word.json", L3_DIR / "embedding-map.json"]:
        text = path.read_text(encoding="utf-8")
        for marker in ("correct_choice_id", "feedback_he", '"correct"', "d-neuron", "d-emb-"):
            assert marker not in text, f"{path.name}: {marker}"


def test_each_step_has_one_goal_explain_act_check_next_and_one_to_three_checks(deeper):
    for i, step in enumerate(deeper["steps"]):
        assert step.get("goal"), step["key"]
        labels = [b["label"] for b in step["blocks"] if b["type"] == "section"]
        assert labels[0] == "understand" and labels[-1] == "check", step["key"]
        checks = [q for q in deeper["questions"].values() if q["step"] == step["key"] and q["type"] == "single_choice"]
        if step["key"] == "wrap-up":
            assert not checks and deeper["questions"]["lesson-03-deeper-exit"]["type"] == "free_text"
        else:
            assert "try" in labels and step.get("next_hint"), step["key"]
            assert 1 <= len(checks) <= 3, step["key"]
    prompts = [b for _, b in _all_blocks(deeper) if b["type"] == "prompt"]
    assert len({k for k, b in _all_blocks(deeper) if b["type"] == "prompt"}) >= 2  # chatbot exercise in 2+ steps
    for p in prompts:
        assert re.search(r"ניחוש|השער|הערכה", p["text"]), p["title"]  # the chatbot must say when it is guessing


def test_lesson_3_gets_its_three_widgets_without_changing_a_check(lesson3):
    widgets = {(k, b["type"]) for k, b in _all_blocks(lesson3) if b["type"] in WIDGETS}
    assert widgets == {("tokens", "live_tokenizer"), ("next-token", "next_word_guess"), ("attention", "attention_view")}
    assert sorted(lesson3["questions"]) == sorted(
        ["l03-q1", "l03-tokens-ratio", "l03-context-shift", "l03-probability-meaning", "l03-q2", "l03-illustration",
         "l03-q3", "l03-source", "l03-grounding-log", "lesson-03-exit"]
    )


def test_measured_data_names_its_model_revision_date_and_script():
    for name, model in (("next-word.json", "Qwen/Qwen2.5-0.5B"),
                        ("embedding-map.json", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")):
        data = json.loads((L3_DIR / name).read_text(encoding="utf-8"))
        assert data["model"] == model and re.fullmatch(r"[0-9a-f]{40}", data["revision"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["generated_at"])
        assert (REPO / data["script"]).is_file(), data["script"]
        assert model in (REPO / data["script"]).read_text(encoding="utf-8")
    nw = json.loads((L3_DIR / "next-word.json").read_text(encoding="utf-8"))
    for p in nw["prompts"]:
        assert len(p["top_tokens"]) == 10 and abs(sum(c["share"] for c in p["candidates"]) - 1) < 0.01
        assert 0 <= p["other_p"] <= 1
    em = json.loads((L3_DIR / "embedding-map.json").read_text(encoding="utf-8"))
    assert 30 <= len(em["words"]) <= 40 and em["dimensions"] == 384
    assert {w["lang"] for w in em["words"]} == {"he", "en"}
    assert all(len(w["neighbors"]) == 5 for w in em["words"])


def test_attention_is_an_illustration_that_only_looks_back(deeper, lesson3):
    for lesson in (lesson3, deeper):
        for _, b in _all_blocks(lesson):
            if b["type"] != "attention_view":
                continue
            for s in b["sentences"]:
                for i, row in enumerate(s["weights"]):
                    assert abs(sum(row) - 1) < 0.011 and all(w == 0 for w in row[i + 1:])
    big = next(s for _, b in _all_blocks(lesson3) if b["type"] == "attention_view" for s in b["sentences"] if s["id"] == "cake-big")
    she, large = big["tokens"].index("היא"), big["tokens"].index("גדולה")
    cake, box = big["tokens"].index("העוגה"), big["tokens"].index("לקופסה")
    assert big["weights"][she][cake] == big["weights"][she][box]  # «היא» alone can't tell
    assert big["weights"][large][cake] > big["weights"][large][box]  # «גדולה» decides
    # The component, not the author, adds the label: it can't be left out.
    widgets = (REPO / "frontend" / "components" / "lessons" / "widgets.tsx").read_text(encoding="utf-8")
    assert "המחשה, לא מדידה" in widgets and "לא מהצ׳טבוט" in widgets


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda b: b["sentences"][0]["weights"][0].__setitem__(1, 0.5), "gives weight to a later token"),
        (lambda b: b["sentences"][0]["weights"].pop(), "weights must be"),
        (lambda b: b["sentences"][0].__setitem__("start", 99), "start 99 is not a token"),
    ],
)
def test_a_broken_attention_block_is_refused(lesson3, mutate, problem):
    raw = copy.deepcopy(lesson3)
    block = next(b for _, b in _all_blocks(raw) if b["type"] == "attention_view")
    mutate(block)
    with pytest.raises(ContentError) as err:
        validate_content(raw, assets_root())
    assert any(problem in e for e in err.value.errors), err.value.errors


def test_other_broken_widgets_are_refused(lesson3, deeper):
    raw = copy.deepcopy(lesson3)
    block = next(b for _, b in _all_blocks(raw) if b["type"] == "next_word_guess")
    block["prompts"].append("no-such-prompt")
    with pytest.raises(ContentError, match="prompt 'no-such-prompt' is not in the asset"):
        validate_content(raw, assets_root())
    raw = copy.deepcopy(deeper)
    neuron = next(b for _, b in _all_blocks(raw) if b["type"] == "neuron_playground")
    neuron["inputs"][0]["value"] = 999
    emap = next(b for _, b in _all_blocks(raw) if b["type"] == "embedding_map")
    emap["start"] = "nope"
    image = next(b for _, b in _all_blocks(raw) if b["type"] == "image")
    image["asset"] = "notebook"
    demo = next(b for _, b in _all_blocks(raw) if b["type"] == "training_demo")
    for p in demo["points"]:
        p["label"] = 1
    with pytest.raises(ContentError) as err:
        validate_content(raw, assets_root())
    joined = " | ".join(err.value.errors)
    for problem in ("input 'orders' needs", "start 'nope' is not a word", "is not an image", "need both labels"):
        assert problem in joined, problem
    raw = copy.deepcopy(lesson3)
    tok = next(b for _, b in _all_blocks(raw) if b["type"] == "live_tokenizer")
    tok["encoding"] = "cl100k_base"  # only the named, bundled encoding
    with pytest.raises(ContentError):
        validate_content(raw, assets_root())


def test_notebook_is_clean_and_executed_and_leaks_no_path():
    student = json.loads(STUDENT_NB.read_text(encoding="utf-8"))
    executed = json.loads(EXECUTED_NB.read_text(encoding="utf-8"))
    src = lambda nb: [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]  # noqa: E731
    assert src(student) == src(executed)
    code = [c for c in student["cells"] if c["cell_type"] == "code"]
    assert all(c["outputs"] == [] and c["execution_count"] is None for c in code)
    ran = [c for c in executed["cells"] if c["cell_type"] == "code"]
    assert [c["execution_count"] for c in ran] == list(range(1, len(ran) + 1))
    assert all(c["outputs"] and not [o for o in c["outputs"] if o["output_type"] == "error"] for c in ran)
    out = "\n".join("".join(o.get("text", "")) for c in ran for o in c["outputs"])
    assert "after 300 steps" in out and "cosine" in out and "MLPClassifier" in "".join(s for _, s in src(student))
    for kind, s in src(student):
        if kind == "markdown":
            assert s.startswith('<div dir="rtl"') and re.search(r"[֐-׿]", s)
    for path in [STUDENT_NB, EXECUTED_NB, *DEEPER_DIR.glob("*"), *L3_DIR.glob("*.json")]:
        text = path.read_text(encoding="utf-8")
        for marker in ("/tmp/", "/home/", "/root/", "scratchpad", "site-packages", "api_key", "sk-"):
            assert marker not in text, f"{path.name}: {marker}"


def test_review_corrections_stay_corrected_in_the_deeper_lesson(deeper):
    """A transformer stacks many layers with their own weights (not one layer
    repeating); the embedding model was trained on translation pairs; cosine
    of unrelated words is not near 0 in this model."""
    text = json.dumps(deeper, ensure_ascii=False)
    svg = (DEEPER_DIR / "transformer-pipeline.svg").read_text(encoding="utf-8")
    for source in (text, svg):
        assert "שוב ושוב" not in source and "חוזרת" not in source
    assert "בזו אחר זו" in text and "בזו אחר זו" in svg
    assert "זוגות של משפטים ותרגומם" in text
    assert "קרוב ל-0 – לא קשורות" not in text
    em = json.loads((L3_DIR / "embedding-map.json").read_text(encoding="utf-8"))
    by_id = {w["id"]: w for w in em["words"]}
    lowest = min(n["cosine"] for w in em["words"] for n in w["neighbors"])
    assert lowest > 0.3  # even the 5th-nearest neighbours are well above 0
    assert by_id["w00"]["text"] == "לחם" and by_id[by_id["w00"]["neighbors"][0]["id"]]["text"] == "bread"
    assert all(step.get("next_hint") for step in deeper["steps"])
