from __future__ import annotations

import copy
import json

import pytest
from lesson_samples import sample_content, write_assets

from app.lessons import ASSETS_ROOT, FIXTURES, assets_root, load_fixture
from app.lessons.schema import (
    ContentError,
    canonical_hash,
    parse_content_json,
    question_hash,
    sanitize_for_student,
    validate_content,
)

ANSWER_KEYS = {"answer", "correct", "misconceptions", "sample_reasoning", "rubric", "explanation", "feedback"}


def _keys(value) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in _keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in _keys(v)}
    return set()


def _errors(content: dict, root=None) -> list[str]:
    with pytest.raises(ContentError) as exc:
        validate_content(content, root)
    return exc.value.errors


@pytest.fixture
def root(tmp_path):
    return write_assets(tmp_path / "public")


def test_sample_validates_with_assets(root):
    content = validate_content(sample_content(), root)
    assert [s.key for s in content.steps] == ["intro", "write", "lab", "extra"]


def test_real_lesson_fixture_validates_with_assets():
    """The shipped lesson-2 fixture: schema, cross-references, and every asset
    file present in frontend/public with the declared sha256."""
    assert FIXTURES["lesson-2"].name == "lesson-2.json"
    assert assets_root() == ASSETS_ROOT and ASSETS_ROOT.is_dir()
    raw = load_fixture("lesson-2")
    content = validate_content(raw, assets_root())
    assert content.slug == "from-data-to-prediction" and content.course_code == "42052"
    assert [s.key for s in content.steps] == [
        "orientation", "data", "tree", "actual-tree", "colab", "evaluate", "wrap-up", "clustering"
    ]
    assert set(content.assets) == {"csv", "tree_json", "tree_png", "notebook", "handout", "homework"}
    assert not ANSWER_KEYS & _keys(sanitize_for_student(raw)["questions"])


def _mutate(path_fn):
    content = sample_content()
    path_fn(content)
    return content


def _step(c, key):
    return next(s for s in c["steps"] if s["key"] == key)


def _block(c, step, type_):
    return next(b for b in _step(c, step)["blocks"] if b["type"] == type_)


MUTATIONS = [
    ("unknown block type", lambda c: _step(c, "intro")["blocks"].append({"type": "video", "src": "x"}), "does not match any of the expected tags"),
    ("unknown field", lambda c: _step(c, "intro").update(colour="red"), "Extra inputs are not permitted"),
    ("optional field set to null", lambda c: _step(c, "intro").update(next_hint=None), "may be left out but not null"),
    ("wrong JSON type", lambda c: _block(c, "lab", "experiment_log").update(min_complete="1"), "valid integer"),
    ("duplicate step key", lambda c: _step(c, "extra").update(key="intro"), "duplicate step key 'intro'"),
    ("question key differs from entry", lambda c: c["questions"]["q_pick"].update(key="q_other"), "does not match its entry"),
    ("question step missing", lambda c: c["questions"]["q_extra"].update(step="nowhere"), "step 'nowhere' does not exist"),
    ("question not shown", lambda c: _step(c, "extra").update(blocks=[{"type": "summary"}]), "not shown by any question block"),
    ("question shown in another step", lambda c: _step(c, "intro")["blocks"].append({"type": "question", "question": "q_extra"}), "belongs to step 'extra'"),
    ("question block unknown question", lambda c: _step(c, "intro")["blocks"].append({"type": "question", "question": "q_nope"}), "unknown question 'q_nope'"),
    ("rule unknown question", lambda c: _step(c, "intro")["completion"].append({"type": "answered", "question": "q_nope"}), "unknown question 'q_nope'"),
    ("rule ack not declared in step", lambda c: _step(c, "write")["completion"].append({"type": "ack", "key": "read_intro"}), "ack 'read_intro' is not declared"),
    ("rule experiments without log", lambda c: _step(c, "intro")["completion"].append({"type": "experiments", "min_complete": 1}), "without an experiment_log block"),
    ("duplicate option id", lambda c: c["questions"]["q_pick"]["options"].append({"id": "a", "text": "again"}), "duplicate option id 'a'"),
    ("correct not an option", lambda c: c["questions"]["q_pick"]["answer"].update(correct=["zz"]), "answer.correct 'zz' is not an option"),
    ("correct empty", lambda c: c["questions"]["q_pick"]["answer"].update(correct=[]), "answer.correct is empty"),
    ("feedback missing", lambda c: c["questions"]["q_pick"]["answer"]["feedback"].pop("c"), "feedback missing for option 'c'"),
    ("misconception on correct option", lambda c: c["questions"]["q_pick"]["answer"]["misconceptions"].update(a="x"), "'a' is not a wrong option"),
    ("answer key missing", lambda c: c["questions"]["q_free"].pop("answer"), "questions.q_free.free_text.answer: Field required"),
    ("download asset missing", lambda c: _block(c, "write", "download").update(asset="pdf"), "unknown asset 'pdf'"),
    ("colab asset missing", lambda c: _block(c, "lab", "colab").update(notebook_asset="nb"), "unknown asset 'nb'"),
    ("actual tree asset missing", lambda c: _block(c, "write", "actual_tree").update(asset="png"), "unknown asset 'png'"),
    ("unbalanced bold", lambda c: c.update(guiding_question="**שאלה"), "guiding_question: unbalanced ** (bold)"),
    ("unbalanced code", lambda c: _step(c, "intro")["blocks"][0]["body"].append("`raw"), "unbalanced ` (code)"),
    ("unbalanced ltr", lambda c: c["questions"]["q_pick"]["options"][0].update(text="[[A"), "unclosed [[ (ltr)"),
    ("manual tree broken child", lambda c: _block(c, "write", "manual_tree")["nodes"][0].update(right=7), "right child 7 does not exist"),
    ("manual tree unknown root", lambda c: _block(c, "write", "manual_tree").update(root=9), "root 9 is not a node"),
    ("optional step before required", lambda c: c["steps"].insert(0, c["steps"].pop()), "required step comes after optional step 'extra'"),
    ("suggested run depth 0", lambda c: _block(c, "lab", "experiment_log")["suggested_runs"][0].update(depth=0), "0 in Colab means unlimited"),
    ("table row width", lambda c: _block(c, "intro", "table")["rows"].append(["only one"]), "row 2 has 1 cells for 2 columns"),
]


@pytest.mark.parametrize("name,mutate,expected", MUTATIONS, ids=[m[0] for m in MUTATIONS])
def test_each_error_class_is_detected(root, name, mutate, expected):
    errors = _errors(_mutate(mutate), root)
    assert any(expected in e for e in errors), errors


def test_asset_files_and_hashes_are_checked(root):
    content = sample_content()
    content["assets"]["csv"]["sha256"] = "0" * 64
    content["assets"]["tree_json"]["path"] = "/lessons/test/v1/missing.json"
    errors = _errors(content, root)
    assert any("assets.csv: sha256" in e for e in errors), errors
    assert any("assets.tree_json: file /lessons/test/v1/missing.json is missing" in e for e in errors), errors
    # Without an assets root (the hosted API bundle) files aren't checked.
    validate_content(sample_content(), None)


def test_actual_tree_asset_references_are_checked(tmp_path):
    root = write_assets(tmp_path / "public")
    tree_file = root / "lessons" / "test" / "v1" / "tree.json"
    tree = json.loads(tree_file.read_bytes())
    tree["nodes"][0]["left"] = 5
    tree_file.write_bytes(json.dumps(tree).encode())
    content = sample_content()
    content["assets"]["tree_json"]["sha256"] = __import__("hashlib").sha256(tree_file.read_bytes()).hexdigest()
    errors = _errors(content, root)
    assert any("left child 5 does not exist" in e for e in errors), errors


def test_every_problem_is_reported_at_once(root):
    content = sample_content()
    _step(content, "extra")["key"] = "intro"
    content["questions"]["q_pick"]["answer"]["correct"] = []
    content["guiding_question"] = "[[x"
    _block(content, "write", "download")["asset"] = "nope"
    errors = _errors(content, root)
    for expected in ("duplicate step key", "answer.correct is empty", "unclosed [[", "unknown asset 'nope'"):
        assert any(expected in e for e in errors), (expected, errors)


def test_duplicate_json_keys_are_refused():
    text = json.dumps(sample_content())
    duplicated = text.replace('"questions": {', '"questions": {"q_pick": {}, ', 1)
    with pytest.raises(ContentError) as exc:
        parse_content_json(duplicated)
    assert exc.value.errors == ["duplicate JSON key 'q_pick'"]
    assert parse_content_json(text) == sample_content()
    with pytest.raises(ContentError):
        parse_content_json("{not json")


def test_sanitize_strips_every_answer_key():
    content = sample_content()
    clean = sanitize_for_student(content)
    assert not ANSWER_KEYS & _keys(clean["questions"])
    assert "answer" not in json.dumps(clean["questions"])
    assert clean["questions"]["q_pick"]["options"] == content["questions"]["q_pick"]["options"]
    assert content["questions"]["q_pick"]["answer"]["correct"] == ["a"]  # the input is untouched
    assert sanitize_for_student(validate_content(sample_content())) == clean


def test_hashes_are_canonical():
    content = sample_content()
    reordered = json.loads(json.dumps(content, sort_keys=True))
    assert canonical_hash(content) == canonical_hash(reordered)
    q = copy.deepcopy(content["questions"]["q_pick"])
    before = question_hash(q)
    q["answer"]["correct"] = ["b"]
    assert question_hash(q) != before
