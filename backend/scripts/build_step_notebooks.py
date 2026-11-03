"""Build one small notebook per Colab step of lesson 3 (both parts).

The operator asked that each notebook cover only what its step of the lesson
shows. This slices the clean v2 notebooks of lesson-03 (Part 1) and
lesson-03-deeper (Part 2) into per-step notebooks under v3/: each opens with
one line saying which step of which lesson it is for, has its own minimal
setup cell (so it runs top to bottom on a fresh CPU runtime), holds only that
step's sections (with the section numbers the lesson page refers to), and
ends by sending the student back to the course page.

The code cells are the v2 cells unchanged (a model-loading cell is rewritten
only where it read a tokenizer loaded by an earlier section), so the numbers
the page quotes come out the same; tests check them against the executed
copies. Writes clean notebooks only; executing them (nbclient on a CPU
runtime) produces the "-executed" copies next to them.

Usage (from backend/):  python scripts/build_step_notebooks.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PUBLIC = Path(__file__).resolve().parents[2] / "frontend" / "public" / "lessons"
P1_V2 = PUBLIC / "lesson-03" / "v2" / "lesson-3-part-1-he.ipynb"
P2_V2 = PUBLIC / "lesson-03-deeper" / "v2" / "lesson-3-part-2-he.ipynb"

_RTL = '<div dir="rtl" style="text-align:right">'

_HOW = (
    "<p>מריצים תא אחרי תא בלחיצה על ▶, מלמעלה למטה. מעבד רגיל (<code>CPU</code>) מספיק; "
    "אין צורך ב-<code>GPU</code>, במפתח <code>API</code> או במנוי. <b>אין חובת הגשת מחברת.</b>{extra}</p>"
)
_HF = " אם מופיעה אזהרה על <code>HF_TOKEN</code> – אפשר להתעלם ממנה: המודל ציבורי."

_SETUP_PLAIN = """# Setup: this step needs plain Python only - nothing to install.
import sys

print("Python", sys.version.split()[0], "- setup done")
"""

_SETUP_TRAINING = """# Setup. Everything below is preinstalled on Google Colab.
import warnings

import matplotlib.pyplot as plt
import numpy as np
import sklearn
from sklearn.exceptions import ConvergenceWarning
from sklearn.neural_network import MLPClassifier

warnings.filterwarnings("ignore", category=ConvergenceWarning)
print("scikit-learn", sklearn.__version__, "- setup done")
"""

_SETUP_EMBEDDINGS = """# Setup. Everything below is preinstalled on Google Colab.
import matplotlib.pyplot as plt
import numpy as np
import torch
import transformers

print("transformers", transformers.__version__, "| torch", torch.__version__, "- setup done")


def rtl(text):
    # matplotlib draws left to right; reversing a Hebrew word displays it correctly.
    return text[::-1] if any("\\u0590" <= ch <= "\\u05ff" for ch in text) else text
"""

_SETUP_TOKENS = """# Setup: tiktoken is the open-source tokenizer library OpenAI publishes.
# transformers is already installed on Google Colab.
%pip install -q tiktoken

import tiktoken
import transformers
from transformers import AutoTokenizer

print("tiktoken", tiktoken.__version__, "| transformers", transformers.__version__, "- setup done")
"""

_SETUP_MODEL = """# Setup: transformers and torch are already installed on Google Colab.
# Loads the small open model Qwen/Qwen2.5-0.5B (about 1GB; usually a minute or two).
import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_NAME = "Qwen/Qwen2.5-0.5B"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
# "eager" attention lets the model return its attention weights; the predictions are the same.
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, dtype=torch.float32, attn_implementation="eager")
model.eval()
print(f"Loaded {MODEL_NAME}: {sum(p.numel() for p in model.parameters()) / 1e9:.2f} billion parameters")
"""

# Next-token step: compare_words() adds probabilities up with math.exp.
_SETUP_NEXT = _SETUP_MODEL.replace("import torch\n", "import math\n\nimport torch\n", 1)

# Part 2's v2 cell 9 loaded the model with the tokenizer section 1 had loaded.
# In the next-token notebook the setup cell loads both, and the cell's helper
# (otherwise the v2 code) joins the setup cell.
_V2_LOAD = '''MODEL_NAME = "Qwen/Qwen2.5-0.5B"
tokenizer = TOKENIZERS["Qwen2.5"]
# "eager" attention lets section 3 read the attention weights; the predictions are the same.
model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, dtype=torch.float32, attn_implementation="eager")
model.eval()
print(f"Loaded {MODEL_NAME}: {sum(p.numel() for p in model.parameters()) / 1e9:.2f} billion parameters")


'''

# (filename, part, lesson title, step letter, step title, setup, v2 cell range, extra run note)
PART_1 = "שיעור 3, חלק 1: מנוירון לייצוג – איך מחשב לומד"
PART_2 = "שיעור 3, חלק 2: איך מודל שפה כותב"
NOTEBOOKS = [
    (P1_V2, "lesson-03", "lesson-3-part-1-a-neuron-he.ipynb", PART_1, "A", "נוירון אחד", _SETUP_PLAIN, (2, 5), ""),
    (P1_V2, "lesson-03", "lesson-3-part-1-b-network-he.ipynb", PART_1, "B", "רשת שלומדת", _SETUP_TRAINING, (5, 12), ""),
    (P1_V2, "lesson-03", "lesson-3-part-1-c-embeddings-he.ipynb", PART_1, "C", "ייצוגים: מילים כמספרים",
     _SETUP_EMBEDDINGS, (12, 17), " המחברת מורידה מודל ייצוגים פתוח של כ-470MB." + _HF),
    (P2_V2, "lesson-03-deeper", "lesson-3-part-2-a-tokens-he.ipynb", PART_2, "A", "המודל מקבל רצף יחידות",
     _SETUP_TOKENS, (2, 8), _HF),
    (P2_V2, "lesson-03-deeper", "lesson-3-part-2-b-next-token-he.ipynb", PART_2, "B", "המודל בוחר את ההמשך",
     _SETUP_NEXT, (8, 21), " תא ההכנה מוריד מודל פתוח של כ-1GB; ההורדה לוקחת בדרך כלל דקה או שתיים." + _HF),
    (P2_V2, "lesson-03-deeper", "lesson-3-part-2-c-attention-he.ipynb", PART_2, "C", "ייצוג ומשמעות תלויים בהקשר",
     _SETUP_MODEL, (21, 25), " תא ההכנה מוריד מודל פתוח של כ-1GB; ההורדה לוקחת בדרך כלל דקה או שתיים." + _HF),
    (P2_V2, "lesson-03-deeper", "lesson-3-part-2-f-grounding-he.ipynb", PART_2, "F", "תשובה רהוטה עדיין דורשת ראיות",
     _SETUP_MODEL, (25, 29), " תא ההכנה מוריד מודל פתוח של כ-1GB; ההורדה לוקחת בדרך כלל דקה או שתיים." + _HF),
]


def _md(cid: str, html: str) -> dict:
    return {"cell_type": "markdown", "id": cid, "metadata": {}, "source": html.splitlines(keepends=True)}


def _code(cid: str, src: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "id": cid,
        "metadata": {},
        "outputs": [],
        "source": src.rstrip("\n").splitlines(keepends=True),
    }


def build() -> dict[Path, str]:
    """{target path: notebook JSON text} for every per-step notebook."""
    out: dict[Path, str] = {}
    sources = {P1_V2: json.loads(P1_V2.read_text(encoding="utf-8")), P2_V2: json.loads(P2_V2.read_text(encoding="utf-8"))}
    for src, slug, name, lesson, letter, title, setup, (start, stop), extra in NOTEBOOKS:
        nb = sources[src]
        stem = name.removesuffix("-he.ipynb")
        header = (
            f"{_RTL}<h1>{lesson} – שלב {letter}: {title}</h1>\n"
            f"<p><b>המחברת הזו היא לשלב {letter} («{title}») בשיעור באתר הקורס – ורק לו.</b> "
            "את ההסבר קוראים באתר; כאן מריצים ומשנים.</p>\n" + _HOW.format(extra=extra) + "</div>"
        )
        cells = [_md(f"{stem}-intro", header), _code(f"{stem}-setup", setup)]
        for cell in nb["cells"][start:stop]:
            cell = json.loads(json.dumps(cell))
            text = "".join(cell["source"])
            if cell["cell_type"] == "code":
                if text.startswith(_V2_LOAD):
                    cells[1] = _code(f"{stem}-setup", setup.rstrip("\n") + "\n\n\n" + text.removeprefix(_V2_LOAD))
                    continue
                cell = _code(f"{stem}-{cell['id']}", text)
            else:
                if "| מה ראינו</h2>" in text:  # the whole part's summary: the lesson page's wrap-up has it
                    text = text[: text.index("\n<h2>")] + "</div>"
                cell = _md(f"{stem}-{cell['id']}", text)
            cells.append(cell)
        cells.append(
            _md(
                f"{stem}-back",
                f"{_RTL}<p><b>סיימתם את המחברת של שלב {letter}.</b> חזרו ללשונית של אתר הקורס "
                "וענו שם על שאלות השלב.</p></div>",
            )
        )
        doc = {"cells": cells, "metadata": nb["metadata"], "nbformat": nb["nbformat"], "nbformat_minor": nb["nbformat_minor"]}
        out[PUBLIC / slug / "v3" / name] = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if a committed notebook differs from the build")
    args = parser.parse_args()
    stale = []
    for path, text in build().items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(path.name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print("wrote", path.relative_to(PUBLIC.parents[1]))
    if stale:
        print("stale:", ", ".join(stale), "- run scripts/build_step_notebooks.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
