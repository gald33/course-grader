"""Session 3 of the 42052 plan, taught in two REQUIRED lessons
(lesson-3-restructure-two-parts):

    part 1 = lesson-03         neuron, a network that learns, embeddings
    part 2 = lesson-03-deeper  tokens, next token, attention, transformer, chatbot, grounding

The committed content carries no answer key; no concept is used before the
step that defines it, across part 1 then part 2; the chatbot is used only
where it is what is being examined (grounding); each step has one required
action; the notebooks ship clean and executed, and every number the page
quotes is one the executed notebook printed.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, ContentError, assets_root, course_plan, load_fixture, load_plan, validate_content

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
SEED = REPO / "content" / "course-42052" / "lessons" / "lesson-03.json"
L3_DIR = ASSETS_ROOT / "lessons" / "lesson-03"
DEEP_DIR = ASSETS_ROOT / "lessons" / "lesson-03-deeper"
# One small notebook per Colab step (v3), clean and executed.
P1_STEPS = {"neuron": "a-neuron", "network": "b-network", "embeddings": "c-embeddings"}
P2_STEPS = {"tokens": "a-tokens", "next-token": "b-next-token", "attention": "c-attention", "grounding": "f-grounding"}


def _pair(folder: Path, part: int, stem: str) -> tuple[Path, Path]:
    base = folder / "v3" / f"lesson-3-part-{part}-{stem}-he"
    return base.with_suffix(".ipynb"), base.parent / f"{base.name}-executed.ipynb"


P1_NBS = {key: _pair(L3_DIR, 1, stem) for key, stem in P1_STEPS.items()}
P2_NBS = {key: _pair(DEEP_DIR, 2, stem) for key, stem in P2_STEPS.items()}
NOTEBOOKS = [*P1_NBS.values(), *P2_NBS.values()]
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


def _all_blocks(lesson):
    for step in lesson["steps"]:
        yield from ((step["key"], b) for b in _blocks(step["blocks"]))


def _nb(path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _outputs(nb) -> str:
    return "\n".join("".join(o.get("text", "")) for c in nb["cells"] if c["cell_type"] == "code" for o in c["outputs"])


def _part(nbs: dict) -> tuple[str, str]:
    """A part's executed notebooks, all together: (sources, outputs)."""
    ran = [_nb(executed) for _, executed in nbs.values()]
    return "\n".join("".join(c["source"]) for nb in ran for c in nb["cells"]), "\n".join(_outputs(nb) for nb in ran)


@pytest.fixture(scope="module")
def p1() -> dict:
    return load_fixture("42052-lesson-03")


@pytest.fixture(scope="module")
def p2() -> dict:
    return load_fixture("42052-lesson-03-deeper")


# ---------------------------------------------------------------------------
# Two required parts, in order
# ---------------------------------------------------------------------------


def test_session_3_is_two_required_lessons_in_order(p1, p2):
    a, b = validate_content(p1, assets_root()), validate_content(p2, assets_root())  # assets exist, sha256 match
    assert [s.key for s in a.steps] == ["neuron", "network", "embeddings", "wrap-up"]
    assert [s.key for s in b.steps] == ["tokens", "next-token", "attention", "transformer", "llm", "grounding", "wrap-up"]
    assert a.title.startswith("חלק 1") and b.title.startswith("חלק 2")
    sessions = load_plan("42052")["sessions"]
    assert sessions[2]["fixture_key"] == "42052-lesson-03" and sessions[2]["part_fixture_keys"] == ["42052-lesson-03-deeper"]
    assert all(not s["part_fixture_keys"] for s in sessions if s["session"] != 3)
    assert [s["session"] for s in sessions] == list(range(1, 14))  # nothing renumbered
    # Nothing frames either part as optional: no enrichment flag, no optional step, no "go deeper".
    for lesson in (p1, p2):
        assert "enrichment" not in lesson
        assert not any(s.get("optional") for s in lesson["steps"])
        framing = json.dumps({k: lesson[k] for k in ("title", "guiding_question", "intro")}, ensure_ascii=False)
        framing += json.dumps([b for _, b in _all_blocks(lesson) if b["type"] in ("callout", "link")], ensure_ascii=False)
        for word in ("רשות", "העשרה", "להעמיק", "אופציונלי"):
            assert word not in framing, (lesson["slug"], word)
    plan_text = json.dumps(load_plan("42052"), ensure_ascii=False)
    assert "enrichment" not in plan_text


def test_no_answer_key_in_any_committed_lesson_3_file(p1, p2):
    files = [*L3_DIR.rglob("*"), *DEEP_DIR.rglob("*")]
    for lesson in (p1, p2):
        assert not PRIVATE_FIELDS & _keys_in(lesson)
        for key, q in lesson["questions"].items():
            assert "answer" not in q, key
            if q["type"] == "single_choice":
                assert q["mode"] == "check", key
    assert not PRIVATE_FIELDS & _keys_in(load_plan("42052")["lessons"]["lesson-03"])
    for path in files:
        if path.is_file() and path.suffix in (".ipynb", ".json", ".svg"):
            text = path.read_text(encoding="utf-8")
            for marker in ("correct_choice_id", "feedback_he", '"correct"', "d-neuron", "d-emb-", "l03-q"):
                assert marker not in text, f"{path.name}: {marker}"


def test_every_question_id_survives_in_the_part_that_teaches_it(p1, p2):
    """No id was dropped by the split; each lives in exactly one part."""
    ids1, ids2 = set(p1["questions"]), set(p2["questions"])
    assert not ids1 & ids2
    assert ids1 == {"d-neuron-weight", "d-neuron-who", "d-train-step", "d-after-training", "d-params",
                    "d-emb-close", "d-emb-2d", "d-emb-odd", "l03-q2", "lesson-03-exit"}
    assert ids2 == {"l03-q1", "l03-tokens-ratio", "l03-context-shift", "l03-probability-meaning", "l03-illustration",
                    "d-pronoun", "d-pipeline-order", "d-instruction-tuning", "d-still-invents", "l03-grounding-log",
                    "l03-q3", "l03-source", "lesson-03-deeper-exit"}


def test_the_seed_checks_and_texts_survive_in_the_part_that_teaches_them(p1, p2):
    seed = json.loads(SEED.read_text(encoding="utf-8"))
    generated = course_plan.seed_to_content(seed, "42052")
    where = {**{k: p1 for k in p1["questions"]}, **{k: p2 for k in p2["questions"]}}
    revised = {"l03-q2"}  # reworded in review (#39): ids, mode and options pinned below
    for key, question in generated["questions"].items():
        mine = where[key]["questions"][key]
        same = ("key", "mode", "type")
        assert {k: mine[k] for k in same} == {k: question[k] for k in same}, key
        if question["type"] == "single_choice":
            assert [o["id"] for o in mine["options"]] == [o["id"] for o in question["options"]], key
        if key not in revised:
            assert mine["prompt"] == question["prompt"] and mine.get("options") == question.get("options"), key
    part2 = json.dumps(p2, ensure_ascii=False).replace("**", "")
    assert seed["worked_example_he"] in part2  # quantity 3 and cookies kept, pickup time missing
    assert course_plan.ltr(seed["work_product_he"]) in part2
    for text in (json.dumps(p1, ensure_ascii=False), part2):
        assert course_plan.ltr(seed["optional_extension_he"]) not in text  # a note to the instructor
        assert seed["homework_he"] not in text  # a proposal, kept in the plan
    assert load_plan("42052")["lessons"]["lesson-03"]["homework"]["text"] == seed["homework_he"]
    grounding = json.dumps(next(s for s in p2["steps"] if s["key"] == "grounding"), ensure_ascii=False)
    code = next(b for _, b in _all_blocks(p2) if b["type"] == "code")
    example = json.loads(code["code"])
    assert (example["quantity"], example["product"], example["pickup_time"]) == (3, "עוגיות", None)
    assert "דוגמה פתורה" in grounding


# ---------------------------------------------------------------------------
# How each step teaches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["p1", "p2"])
def test_each_step_has_one_goal_explanation_required_action_check_and_next_step(which, request):
    lesson = request.getfixturevalue(which)
    for step in lesson["steps"]:
        assert step.get("goal") and step.get("next_hint"), step["key"]
        sections = [b for b in step["blocks"] if b["type"] == "section"]
        labels = [s["label"] for s in sections]
        assert labels[0] == "understand" and "check" in labels, step["key"]
        checks = [q for q in lesson["questions"].values() if q["step"] == step["key"] and q["type"] == "single_choice"]
        assert len(checks) <= 3, step["key"]
        if step["key"] == "wrap-up":
            continue
        assert 1 <= len(checks), step["key"]
        required = [s for s in sections if s["label"] == "try" and not s.get("title", "").startswith("רשות")]
        assert len(required) == 1, (step["key"], [s.get("title") for s in sections])  # one required action
        assert "**הפעולה:**" in json.dumps(required[0], ensure_ascii=False), step["key"]
        # The notebook is practice beside the page, never the only way to the action.
        assert not any(b["type"] == "colab" for b in _blocks(required[0]["blocks"])), step["key"]


def _visible(lesson):
    """(where, text) for the lesson's intro and each step, the step's questions included; names (titles) excluded."""
    skip = {"title", "key", "letter", "type", "label", "asset", "notebook_asset", "question", "step", "mode", "id",
            "encoding", "target", "start", "caption"}

    def strings(v, out, key=None):
        if isinstance(v, str):
            if key not in skip:
                out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                strings(x, out, k)
        elif isinstance(v, list):
            for x in v:
                strings(x, out, key)

    head: list[str] = []
    strings({k: lesson[k] for k in ("guiding_question", "intro")}, head)
    seq = [(f"{lesson['slug']}:intro", " ".join(head))]
    for st in lesson["steps"]:
        out: list[str] = []
        strings(st["blocks"], out)
        for q in lesson["questions"].values():
            if q["step"] == st["key"]:
                strings(q, out)
        seq.append((f"{lesson['slug']}:{st['key']}", " ".join(out)))
    return seq


# term -> the step that defines it (in bold), in the order students meet them.
DEFINED_IN = {
    "נוירון": "lesson-03:neuron",
    "משקל": "lesson-03:neuron",
    "פרמטר": "lesson-03:network",
    "ייצוג": "lesson-03:embeddings",
    "embedding": "lesson-03:embeddings",
    "טוקן": "lesson-03-deeper:tokens",
    "tokenizer": "lesson-03-deeper:tokens",
    "טמפרטורה": "lesson-03-deeper:next-token",
    "קשב": "lesson-03-deeper:attention",
    "attention": "lesson-03-deeper:attention",
    "[Tt]ransformer": "lesson-03-deeper:transformer",
}


def test_no_concept_is_used_before_the_step_that_defines_it(p1, p2):
    seq = _visible(p1) + _visible(p2)
    order = [where for where, _ in seq]
    for term, defining in DEFINED_IN.items():
        first = next(where for where, text in seq if re.search(term, text))
        assert first == defining, f"'{term}' is used in {first} before {defining} defines it"
        text = dict(seq)[defining]
        assert re.search(r"\*\*[^*]*" + term, text), f"{defining} does not define '{term}' in bold"
        assert order.index(first) <= order.index(defining)


def test_every_part_2_step_that_uses_a_part_1_term_reminds_of_it(p2):
    for step in p2["steps"]:
        text = json.dumps(step, ensure_ascii=False)
        if any(t in text for t in ("פרמטר", "משקל", "ייצוג", "נוירון")) and step["key"] != "wrap-up":
            assert "זוכרים מחלק 1" in text, step["key"]


def test_the_chatbot_is_used_only_where_it_is_what_is_examined(p1, p2):
    prompts = [(lesson["slug"], k, b) for lesson in (p1, p2) for k, b in _all_blocks(lesson) if b["type"] == "prompt"]
    assert prompts and {(slug, k) for slug, k, _ in prompts} == {("lesson-03-deeper", "grounding")}
    grounding = json.dumps(next(s for s in p2["steps"] if s["key"] == "grounding"), ensure_ascii=False)
    assert "**למה בצ׳טבוט:**" in grounding
    for _, _, p in prompts:
        assert p.get("note", "").startswith("המטרה:"), p["title"]  # each states its purpose
        assert "[הדביקו" not in p["text"]  # complete: nothing left to fill in
    rules = next(p for _, _, p in prompts if "כללים" in p["title"])
    assert rules["text"].rstrip().endswith("מיכל רוצה שלוש עוגיות למחר")
    assert "null" in rules["text"] and "missing" in rules["text"]


def test_widgets_sit_in_the_step_that_teaches_them(p1, p2):
    assert {(k, b["type"]) for k, b in _all_blocks(p1) if b["type"] in WIDGETS} == {
        ("neuron", "neuron_playground"), ("network", "training_demo"), ("embeddings", "embedding_map")}
    assert {(k, b["type"]) for k, b in _all_blocks(p2) if b["type"] in WIDGETS} == {
        ("tokens", "live_tokenizer"), ("next-token", "next_word_guess"), ("attention", "attention_view"), ("transformer", "image")}


def test_no_fake_colab_link_and_no_paid_or_keyed_service(p1, p2):
    for lesson in (p1, p2):
        text = json.dumps(lesson, ensure_ascii=False)
        assert not re.search(r"colab\.research\.google\.com/(drive|github|notebooks)", text) and "http" not in text


def test_each_colab_step_opens_its_own_notebook(p1, p2):
    """One notebook per Colab step: the step's block points at that step's
    notebook (and its executed copy), and the notebook says which step it is."""
    for lesson, nbs in ((p1, P1_NBS), (p2, P2_NBS)):
        colab = {key: b for key, b in _all_blocks(lesson) if b["type"] == "colab"}
        assert set(colab) == set(nbs), lesson["slug"]
        letters = {s["key"]: s["letter"] for s in lesson["steps"]}
        for key, (clean, executed) in nbs.items():
            block, assets = colab[key], lesson["assets"]
            assert assets[block["notebook_asset"]]["path"] == "/" + str(clean.relative_to(ASSETS_ROOT))
            step = next(s for s in lesson["steps"] if s["key"] == key)
            offered = {assets[b["asset"]]["path"] for b in _blocks(step["blocks"]) if b["type"] == "download"}
            assert offered == {"/" + str(executed.relative_to(ASSETS_ROOT))}, key  # its own executed copy
            intro = "".join(_nb(clean)["cells"][0]["source"])
            assert f"המחברת הזו היא לשלב {letters[key]} (" in intro, (key, intro[:120])
            # Only this step's sections: the notebook's section numbers are the ones the block names.
            numbers = set(re.findall(r"<h2>(\d) \|", "".join("".join(c["source"]) for c in _nb(clean)["cells"])))
            assert numbers and numbers == set(re.findall(r"\d", block["section"])[:1]), (key, numbers, block["section"])


# ---------------------------------------------------------------------------
# Measured data and illustrations
# ---------------------------------------------------------------------------


def test_measured_data_names_its_model_revision_date_and_script():
    for name, model in (("next-word.json", "Qwen/Qwen2.5-0.5B"),
                        ("embedding-map.json", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")):
        data = json.loads((L3_DIR / "v1" / name).read_text(encoding="utf-8"))
        assert data["model"] == model and re.fullmatch(r"[0-9a-f]{40}", data["revision"])
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", data["generated_at"])
        assert model in (REPO / data["script"]).read_text(encoding="utf-8")
    em = json.loads((L3_DIR / "v1" / "embedding-map.json").read_text(encoding="utf-8"))
    assert 30 <= len(em["words"]) <= 40 and em["dimensions"] == 384
    assert min(n["cosine"] for w in em["words"] for n in w["neighbors"]) > 0.3  # "unrelated words score ~0.3-0.5"


def test_attention_is_an_illustration_that_only_looks_back(p2):
    view = next(b for _, b in _all_blocks(p2) if b["type"] == "attention_view")
    for s in view["sentences"]:
        for i, row in enumerate(s["weights"]):
            assert abs(sum(row) - 1) < 0.011 and all(w == 0 for w in row[i + 1:])
    big = next(s for s in view["sentences"] if s["id"] == "cake-big")
    she, large, cake, box = (big["tokens"].index(t) for t in ("היא", "גדולה", "העוגה", "לקופסה"))
    assert big["weights"][she][cake] == big["weights"][she][box] and big["weights"][large][cake] > big["weights"][large][box]
    widgets = (REPO / "frontend" / "components" / "lessons" / "widgets.tsx").read_text(encoding="utf-8")
    assert "המחשה, לא מדידה" in widgets and "לא מהצ׳טבוט" in widgets
    # The page points from the illustration to the real measurement in the notebook.
    attention = json.dumps(next(s for s in p2["steps"] if s["key"] == "attention"), ensure_ascii=False)
    assert "המשקלים האמיתיים" in attention or "משקלי הקשב האמיתיים" in attention


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda b: b["sentences"][0]["weights"][0].__setitem__(1, 0.5), "gives weight to a later token"),
        (lambda b: b["sentences"][0]["weights"].pop(), "weights must be"),
        (lambda b: b["sentences"][0].__setitem__("start", 99), "start 99 is not a token"),
    ],
)
def test_a_broken_attention_block_is_refused(p2, mutate, problem):
    raw = copy.deepcopy(p2)
    mutate(next(b for _, b in _all_blocks(raw) if b["type"] == "attention_view"))
    with pytest.raises(ContentError) as err:
        validate_content(raw, assets_root())
    assert any(problem in e for e in err.value.errors), err.value.errors


def test_other_broken_widgets_are_refused(p1, p2):
    raw = copy.deepcopy(p2)
    next(b for _, b in _all_blocks(raw) if b["type"] == "next_word_guess")["prompts"].append("no-such-prompt")
    with pytest.raises(ContentError, match="prompt 'no-such-prompt' is not in the asset"):
        validate_content(raw, assets_root())
    raw = copy.deepcopy(p1)
    next(b for _, b in _all_blocks(raw) if b["type"] == "neuron_playground")["inputs"][0]["value"] = 999
    next(b for _, b in _all_blocks(raw) if b["type"] == "embedding_map")["start"] = "nope"
    for p in next(b for _, b in _all_blocks(raw) if b["type"] == "training_demo")["points"]:
        p["label"] = 1
    with pytest.raises(ContentError) as err:
        validate_content(raw, assets_root())
    joined = " | ".join(err.value.errors)
    for problem in ("input 'orders' needs", "start 'nope' is not a word", "need both labels"):
        assert problem in joined, problem
    raw = copy.deepcopy(p2)
    next(b for _, b in _all_blocks(raw) if b["type"] == "image")["asset"] = "notebook_tokens"
    next(b for _, b in _all_blocks(raw) if b["type"] == "live_tokenizer")["encoding"] = "cl100k_base"
    with pytest.raises(ContentError):
        validate_content(raw, assets_root())


def test_review_corrections_stay_corrected(p1, p2):
    """What the adversarial review (#39) found untrue stays fixed after the split."""
    texts = [json.dumps(p1, ensure_ascii=False), json.dumps(p2, ensure_ascii=False)]
    texts += [path.read_text(encoding="utf-8") for pair in NOTEBOOKS for path in pair]
    svg = (DEEP_DIR / "v1" / "transformer-pipeline.svg").read_text(encoding="utf-8")
    for text in [*texts, svg]:
        assert "פי עשרות ומאות" not in text and "עשרות «ראשי קשב»" not in text
        assert "קיבלה את רוב ההסתברות" not in text and "שוב ושוב" not in text
    assert "בזו אחר זו" in svg and "זוגות של משפטים ותרגומם" in texts[0]
    assert "14 «ראשי קשב» בכל אחת מ-24 השכבות" in texts[1]
    data = json.loads((L3_DIR / "v1" / "next-word.json").read_text(encoding="utf-8"))
    pickup = next(p for p in data["prompts"] if p["id"] == "pickup-he")
    assert round(next(c["share"] for c in pickup["candidates"] if c["word"] == "10:00") * 100) == 74
    assert "כ-74% מתוך ארבע האפשרויות" in texts[1]


# ---------------------------------------------------------------------------
# Notebooks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("clean, executed", NOTEBOOKS)
def test_notebook_is_clean_and_executed_with_no_path(clean, executed):
    student, ran = _nb(clean), _nb(executed)
    src = lambda nb: [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]  # noqa: E731
    assert src(student) == src(ran)
    code = [c for c in student["cells"] if c["cell_type"] == "code"]
    assert code and all(c["outputs"] == [] and c["execution_count"] is None for c in code)
    cells = [c for c in ran["cells"] if c["cell_type"] == "code"]
    assert [c["execution_count"] for c in cells] == list(range(1, len(cells) + 1))  # top to bottom, once
    for c in cells:
        assert c["outputs"] and not [o for o in c["outputs"] if o["output_type"] == "error"], c["id"]
    for kind, s in src(student):
        if kind == "markdown":
            assert s.startswith('<div dir="rtl"') and re.search(r"[֐-׿]", s)
    # Every section: predict, run, change one thing, observe.
    sections = re.split(r"<h2>\d", "\n".join(s for k, s in src(student) if k == "markdown"))[1:]
    for section in sections:
        assert "①" in section and "③" in section, section[:60]
    for path in (clean, executed):
        text = path.read_text(encoding="utf-8")
        for marker in ("/tmp/", "/home/", "/root/", "/Users/", "scratchpad", "site-packages", "api_key", "sk-"):
            assert marker not in text, f"{path.name}: {marker}"


def test_notebooks_do_what_each_part_needs():
    (src1, out1), (src2, out2) = _part(P1_NBS), _part(P2_NBS)
    # Part 1: a neuron by hand; a tiny network, learning rate / size changed, parameters counted; your own words.
    assert "def neuron(" in src1 and "MLPClassifier" in src1 and "my_words" in src1
    assert "baseline network (8 hidden): 33 parameters" in out1 and "learning rate" in out1
    assert "paraphrase-multilingual-MiniLM-L12-v2" in src1
    # Part 2: three tokenizers on your text; top-k; temperatures; REAL attention; grounding check.
    for name in ("o200k_base", "cl100k_base", "Qwen2.5"):
        assert re.search(rf"{re.escape(name)}\s+\d+ tokens", out2), name
    assert "output_attentions=True" in src2 and "MEASURED attention of Qwen2.5-0.5B" in src2
    assert all(f"T={t}:" in out2 for t in (0.3, 1.0, 1.5))
    assert "PASS  quantity is 3, as in the message" in out2


def test_every_number_the_page_quotes_is_in_the_executed_output(p1, p2):
    page1, page2 = json.dumps(p1, ensure_ascii=False), json.dumps(p2, ensure_ascii=False)
    (_, out1), (_, out2) = _part(P1_NBS), _part(P2_NBS)
    pairs = [
        (page1, "[[0.65]] ל-[[0.15]]", out1, "loss after 1 step: 0.647   after 300 steps: 0.151"),
        (page1, "מ-66% ל-92%", out1, "66% after 1 step, 92% after 300"),
        (page1, "33 פרמטרים", out1, "33 parameters"),
        (page2, "11 מול 7", out2, "o200k_base    11 tokens"),
        (page2, "נחתך ל-11 טוקנים ב-[[o200k_base]] ול-24 ב-[[cl100k_base]]", out2, "cl100k_base   24 tokens"),
        (page2, "[[coffee]] קיבלה כ-73%", out2, "coffee   73.3%"),
        (page2, "[[wine]] קיבלה כ-89%", out2, "wine   89.1%"),
        (page2, "כ-47% מהמשקל", out2, "'ה' 47%"),
        (page2, "בשעות כמו 17:30 ו-10:00", out2, "שעת האיסוף: 17:30"),
    ]
    for page, quoted, out, printed in pairs:
        assert quoted in page, quoted
        assert printed in out, printed


def test_lesson_5_glosses_the_key_before_explaining_it():
    lesson5 = json.dumps(load_fixture("42052-lesson-05"), ensure_ascii=False)
    assert "ולחשוף מפתח (סיסמה לשירות)" in lesson5
