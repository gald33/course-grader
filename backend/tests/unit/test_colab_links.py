"""Every Colab button opens a notebook that exists (no fake links).

A colab block's "open in Colab" button opens the lesson's instructor-set link
when there is one, else the step's own notebook straight from the public
repository: COLAB_GITHUB_BASE + the asset's path under frontend/public on
main (the frontend builds the link; this mirrors its rule). The operator's
rule (2026-11-03): each notebook covers only its step, and the colab block
shows one line and the button, with everything else collapsed.
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
        for asset_key in filter(None, (block["notebook_asset"], block.get("executed_asset"))):
            path = content["assets"][asset_key]["path"]
            url = _github_url(path)
            assert url, (key, step["key"], path)
            file = REPO / url.removeprefix(COLAB_GITHUB_BASE.split("/blob/main/")[0] + "/blob/main/")
            assert file == ASSETS_ROOT / path.lstrip("/") and file.is_file(), (key, step["key"], url)
            assert json.loads(file.read_text(encoding="utf-8"))["cells"], url  # a real notebook


def test_lessons_1_and_3_give_each_colab_step_its_own_notebook_and_one_line():
    seen = set()
    for key in sorted(PER_STEP):
        blocks = list(_colab_blocks(key))
        assert blocks, key
        notebooks = [b["notebook_asset"] for _, _, b in blocks]
        assert len(set(notebooks)) == len(notebooks), key  # no two steps share a notebook
        for content, step, block in blocks:
            path = content["assets"][block["notebook_asset"]]["path"]
            assert path not in seen
            seen.add(path)
            lead = block.get("lead") or ""
            # One sentence: a single full stop or dash-joined clause, at the end.
            assert lead and len(lead) <= 200 and lead.count(". ") == 0 and lead.endswith("."), (key, step["key"], lead)
            assert not block.get("instructions"), (key, step["key"])  # the generic how-to lives in the help
    assert len(seen) == 8  # lesson 1: 1; Part 1: 3; Part 2: 4


def test_the_live_lesson_2_content_is_untouched():
    """The renderer change reaches lesson 2; its published content does not change."""
    blocks = [b for _, _, b in _colab_blocks("lesson-2")]
    assert [b["notebook_asset"] for b in blocks] == ["notebook", "notebook"]
    assert all("lead" not in b and "executed_asset" not in b and b["instructions"] for b in blocks)


def test_the_colab_block_collapses_everything_but_the_line_and_the_button():
    source = BLOCKS_TSX.read_text(encoding="utf-8")
    body = source[source.index("function ColabBlock(") : source.index("function LinkBlock(")]
    button = body.index("פתיחה בקולאב")
    help_ = body.index("<details")
    assert body.index("block.lead") < button < help_  # the line, then the button, both outside the expander
    assert body.count("<details") == 1 and "<details open" not in body and "עזרה וחלופות" in body
    for inside in ("block.instructions", "הורדת המחברת", "colab.research.google.com/\"", "href={executed.path}", "block.return_note"):
        assert body.index(inside) > help_, inside


def test_the_step_notebooks_are_built_from_the_script():
    run = subprocess.run(
        [sys.executable, "scripts/build_step_notebooks.py", "--check"], cwd=BACKEND, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr
