"""Precompute the "guess the next word" data for lesson 3 (42052).

Runs a small open model OFFLINE, once, and writes static JSON that the lesson
page ships: no model runs in the browser and nothing calls an API.

    pip install torch transformers   # CPU is enough
    python scripts/lesson-03/generate_next_word.py

Writes frontend/public/lessons/lesson-03/v1/next-word.json. For each prompt:
- top_tokens: the model's 10 most likely next tokens and their probabilities
  (of the whole vocabulary; the rest is reported as other_p);
- candidates: the word choices the student guesses from, each with its share
  AMONG THOSE CANDIDATES ONLY, from the probability of all of the word's
  tokens in sequence (a Hebrew word is often several tokens).
The model and revision are pinned, so a rerun gives the same numbers up to
floating-point differences between library versions.
"""

from __future__ import annotations

import datetime as dt
import json
import math
from pathlib import Path

import torch
import transformers
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL = "Qwen/Qwen2.5-0.5B"
REVISION = "060db6499f32faf8b98477b0a26969ef7d8b9987"
OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "lessons" / "lesson-03" / "v1" / "next-word.json"
TOP_K = 10

PROMPTS = [
    ("morning-he", "בבוקר, לפני העבודה, אני שותה כוס", ["קפה", "תה", "מים", "יין"]),
    ("dinner-he", "בערב, עם הארוחה החגיגית, שתינו כוס", ["קפה", "תה", "מים", "יין"]),
    ("morning-en", "Every morning before work I drink a cup of", ["coffee", "tea", "water", "wine"]),
    ("dinner-en", "At the festive dinner we drank a glass of", ["coffee", "tea", "water", "wine"]),
    ("bakery-he", "במאפייה שליד הבית אפשר לקנות כל בוקר", ["לחם", "עוגות", "פיצה", "נעליים"]),
    ("order-he", "שלום, אני רוצה להזמין שלוש", ["עוגיות", "לחמניות", "מכוניות", "שעות"]),
    ("pickup-he", "מיכל רוצה שלוש עוגיות למחר. שעת האיסוף:", ["10:00", "17:30", "לא ידוע", "מחר"]),
]


def main() -> None:
    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModelForCausalLM.from_pretrained(MODEL, revision=REVISION, dtype=torch.float32)
    model.eval()

    def log_probs(ids: list[int]) -> torch.Tensor:
        with torch.no_grad():
            return torch.log_softmax(model(torch.tensor([ids])).logits[0], dim=-1)

    prompts = []
    for pid, context, words in PROMPTS:
        ctx = tok(context).input_ids
        last = log_probs(ctx)[-1].exp()
        values, indices = last.topk(TOP_K)
        top = [{"token": tok.decode([i]), "p": round(p, 4)} for p, i in zip(values.tolist(), indices.tolist())]
        scores = {}
        for word in words:
            wid = tok(" " + word).input_ids
            lp = log_probs(ctx + wid)
            scores[word] = sum(lp[len(ctx) - 1 + j, t].item() for j, t in enumerate(wid))
        total = sum(math.exp(v) for v in scores.values())
        candidates = [{"word": w, "share": round(math.exp(scores[w]) / total, 4)} for w in words]
        prompts.append({
            "id": pid,
            "context": context,
            "lang": "en" if pid.endswith("-en") else "he",
            "candidates": candidates,
            "top_tokens": top,
            "other_p": round(max(0.0, 1 - sum(t["p"] for t in top)), 4),
        })
    data = {
        "format": 1,
        "model": MODEL,
        "revision": REVISION,
        "generated_at": dt.date.today().isoformat(),
        "script": "scripts/lesson-03/generate_next_word.py",
        "library": f"transformers {transformers.__version__}, torch {torch.__version__}",
        "note": "Precomputed offline from a small open model. Not the chatbot students use.",
        "prompts": prompts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
