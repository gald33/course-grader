"""Every Colab button opens a notebook that exists (no fake links).

A colab block's "open in Colab" button opens the lesson's instructor-set link
when there is one, else the step's own notebook straight from the public
repository: COLAB_GITHUB_BASE + the asset's path under frontend/public on
main (the frontend builds the link; this mirrors its rule). The operator's
rule (2026-11-03): each notebook covers only its step; the block shows a
one-line lead and the button, with generic how-to collapsed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app.lessons import ASSETS_ROOT, FIXTURES, load_fixture

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
BLOCKS_TSX = REPO / "frontend" / "components" / "lessons" / "blocks.tsx"
COLAB_GITHUB_BASE = "https://colab.research.google.com/github/gald33/course-grader/blob/main/frontend/public"
# The lessons whose Colab steps each open their own notebook (lesson 1, and both parts of lesson 3).
PER_STEP = {"42052-lesson-01", "42052-lesson-03", "42052-lesson-03-deeper"}


def _blocks(blocks):
    for b in blocks:
        yield b
        yield from _blocks(b.get("blocks") or [])


def _colab_blocks(key: str):
    content = load_fixture(key)
    for step in content["steps"]:
        for block in _blocks(step["blocks"]):
            if block["type"] == "colab":
                yield content, step, block


def _github_url(path: str) -> str | None:
    """The frontend's colabGithubUrl()."""
    if re.fullmatch(r"/lessons/[A-Za-z0-9._/-]+\.ipynb", path) and ".." not in path:
        return COLAB_GITHUB_BASE + path
    return None


def test_the_frontend_builds_links_with_the_same_base_and_rule():
    source = BLOCKS_TSX.read_text(encoding="utf-8")
    assert f"export const COLAB_GITHUB_BASE = '{COLAB_GITHUB_BASE}';" in source
    assert r"/^\/lessons\/[A-Za-z0-9._/-]+\.ipynb$/" in source and "!assetPath.includes('..')" in source
    # The instructor's lesson-level link still wins over the step's own notebook.
    assert "safeColabUrl(api.colabUrl) ?? (notebook ? colabGithubUrl(notebook.path) : null)" in source


@pytest.mark.parametrize("key", sorted(FIXTURES))
def test_every_generated_colab_url_points_at_a_notebook_in_the_repository(key):
    for content, step, block in _colab_blocks(key):
        for asset_key in [block["notebook_asset"]]:
            path = content["assets"][asset_key]["path"]
            url = _github_url(path)
            assert url, (key, step["key"], path)
            file = REPO / url.removeprefix(COLAB_GITHUB_BASE.split("/blob/main/")[0] + "/blob/main/")
            assert file == ASSETS_ROOT / path.lstrip("/") and file.is_file(), (key, step["key"], url)
            assert json.loads(file.read_text(encoding="utf-8"))["cells"], url  # a real notebook


def _one_line(lead: str) -> bool:
    return bool(lead) and len(lead) <= 200 and lead.endswith(".") and lead.count(". ") == 0 and "\n" not in lead


def test_lessons_1_and_3_give_each_colab_step_its_own_notebook_and_a_lead():
    seen = set()
    for key in sorted(PER_STEP):
        blocks = list(_colab_blocks(key))
        assert blocks, key
        for content, step, block in blocks:
            path = content["assets"][block["notebook_asset"]]["path"]
            assert path not in seen, (key, step["key"])  # no two steps share a notebook
            seen.add(path)
            # One visible line: what to do in THIS notebook for THIS step.
            assert _one_line(block.get("lead", "")), (key, step["key"], block.get("lead"))
            # The collapsed help keeps only generic how-to: nothing names a section of the notebook.
            assert not any("סעיף" in i for i in block["instructions"]), (key, step["key"])
    assert len(seen) == 8  # lesson 1: 1; Part 1: 3; Part 2: 4


def test_lesson_2_gets_leads_and_keeps_everything_else():
    """Lesson 2 (from-data-to-prediction): each Colab block gains a lead (a new
    draft when installed); the step-only instruction moved into the lead."""
    blocks = [b for _, _, b in _colab_blocks("lesson-2")]
    assert [b["notebook_asset"] for b in blocks] == ["notebook", "notebook"]
    assert all(_one_line(b["lead"]) for b in blocks)
    assert set().union(*map(set, blocks)) == {"type", "notebook_asset", "section", "lead", "instructions", "return_note"}
    data = blocks[0]
    assert len(data["instructions"]) == 4 and "סעיף 1ב" in data["lead"]
    assert not any("בשלב הזה מריצים רק" in i for i in data["instructions"])


def test_the_lead_and_the_button_are_outside_the_collapsed_help():
    source = BLOCKS_TSX.read_text(encoding="utf-8")
    body = source[source.index("function ColabBlock(") : source.index("function LinkBlock(")]
    lead, button, help_ = body.index("block.lead ?"), body.index("פתיחה בקולאב ↗"), body.index("<details")
    assert lead < button < help_ and body.count("<details") == 1 and "<details open" not in body


def test_the_step_notebooks_are_built_from_the_script():
    run = subprocess.run(
        [sys.executable, "scripts/build_step_notebooks.py", "--check"], cwd=BACKEND, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr


def test_each_step_notebook_says_its_step_and_points_only_at_its_own_sections():
    """Reed's #46 B1/N1: a step's notebook holds only that step's sections, says
    which step it is for, and never sends the student to a section that now
    lives in another step's notebook."""
    for key in sorted(PER_STEP):
        for content, step, block in _colab_blocks(key):
            path = ASSETS_ROOT / content["assets"][block["notebook_asset"]]["path"].lstrip("/")
            cells = json.loads(path.read_text(encoding="utf-8"))["cells"]
            assert f"המחברת הזו היא לשלב {step['letter']} (" in "".join(cells[0]["source"]), (key, step["key"])
            text = "".join("".join(c["source"]) for c in cells)
            present = set(re.findall(r"(?:<h[23]>|## )(\d+[א-ת]?)[ .|]", text))
            mentioned = set(re.findall(r"סעיף (\d+[א-ת]?)", text))
            assert present and mentioned <= present, (key, step["key"], sorted(mentioned - present))


def test_lesson_1_step_b_notebook_is_the_calculator_only():
    cells = json.loads((ASSETS_ROOT / "lessons/lesson-01/v2/lesson-1-b-dessert-calculator-he.ipynb").read_text("utf-8"))["cells"]
    headings = [re.match(r"## (\d+)\.", "".join(c["source"])) for c in cells if c["cell_type"] == "markdown"]
    assert [h.group(1) for h in headings if h] == ["3", "4", "5", "6", "8"]  # not 1-2 (step A), 7 (step C), 9 (wrap-up)
    assert "def calculate_stall(" in "".join(cells[2]["source"])  # its first code cell defines what the rest uses
