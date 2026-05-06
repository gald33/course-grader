from __future__ import annotations

import re

import nbformat

HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
DOCSTRING_RE = re.compile(r"('''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\")", re.MULTILINE)


def extract_comment_blocks(source: str) -> list[str]:
    blocks: list[str] = []
    for line in source.splitlines():
        if "#" in line:
            comment = line.split("#", 1)[1].strip()
            if comment:
                blocks.append(comment)

    for match in DOCSTRING_RE.findall(source):
        cleaned = match.strip("'\"\n ")
        if cleaned:
            blocks.append(cleaned)

    return blocks


def english_comments_score_from_notebook(ipynb_path: str) -> tuple[float, str]:
    """Returns (score, rationale) so callers can persist both."""
    nb = nbformat.read(ipynb_path, as_version=4)
    comments: list[str] = []

    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        source = cell.source or ""
        if not source.strip():
            continue
        comments.extend(extract_comment_blocks(source))

    if not comments:
        return 5.0, "No comments or docstrings found — no Hebrew to flag."

    english_like = sum(1 for comment in comments if not HEBREW_RE.search(comment))
    ratio = english_like / len(comments)
    score = round(max(0.0, min(5.0, ratio * 5.0)), 2)
    rationale = (
        f"{english_like} of {len(comments)} comments / docstrings have no Hebrew "
        f"characters ({round(ratio * 100)}%)."
    )
    return score, rationale
