"""Precompute the embedding map for lesson 3 part B (42052).

Embeds ~36 Hebrew and English words with a small open multilingual embedding
model OFFLINE and writes static JSON for the lesson page:
- x, y: a 2D projection (PCA of the full vectors). Distances on the map are
  approximate: two dimensions cannot keep every distance;
- neighbors: each word's 5 nearest words by cosine similarity of the FULL
  vectors (384 numbers), which is what "similar" means here.

    pip install torch transformers numpy
    python scripts/lesson-03/generate_embedding_map.py

Writes frontend/public/lessons/lesson-03/v1/embedding-map.json. Model and
revision are pinned.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import torch
import transformers
from transformers import AutoModel, AutoTokenizer

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"
OUT = Path(__file__).resolve().parents[2] / "frontend" / "public" / "lessons" / "lesson-03" / "v1" / "embedding-map.json"

GROUPS = {
    "bakery": ["לחם", "עוגה", "עוגיות", "מאפייה", "bread", "cake", "cookies", "bakery"],
    "drinks": ["קפה", "תה", "מים", "coffee", "tea", "water"],
    "days": ["יום ראשון", "יום שני", "מחר", "אתמול", "Monday", "Sunday", "tomorrow"],
    "feelings": ["שמח", "עצוב", "כועס", "happy", "sad", "angry"],
    "people": ["אמא", "אבא", "מורה", "לקוח", "mother", "father", "teacher", "customer"],
}


def embed(tok, model, texts: list[str]) -> np.ndarray:
    batch = tok(texts, padding=True, return_tensors="pt")
    with torch.no_grad():
        out = model(**batch).last_hidden_state
    mask = batch["attention_mask"].unsqueeze(-1).float()
    vectors = (out * mask).sum(1) / mask.sum(1)  # mean pooling, as the model card says
    return vectors.numpy()


def main() -> None:
    tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION)
    model = AutoModel.from_pretrained(MODEL, revision=REVISION)
    model.eval()
    words = [(w, g) for g, ws in GROUPS.items() for w in ws]
    vectors = embed(tok, model, [w for w, _ in words])
    unit = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    cosine = unit @ unit.T
    centered = vectors - vectors.mean(0)
    _, singular, vt = np.linalg.svd(centered, full_matrices=False)
    xy = centered @ vt[:2].T
    xy = (xy - xy.min(0)) / (xy.max(0) - xy.min(0))  # 0..1 for drawing
    explained = float((singular[:2] ** 2).sum() / (singular**2).sum())
    items = []
    for i, (word, group) in enumerate(words):
        order = [j for j in np.argsort(-cosine[i]) if j != i][:5]
        items.append({
            "id": f"w{i:02d}",
            "text": word,
            "group": group,
            "lang": "en" if word.isascii() else "he",
            "x": round(float(xy[i, 0]), 4),
            "y": round(float(xy[i, 1]), 4),
            "neighbors": [{"id": f"w{j:02d}", "cosine": round(float(cosine[i, j]), 3)} for j in order],
        })
    data = {
        "format": 1,
        "model": MODEL,
        "revision": REVISION,
        "dimensions": int(vectors.shape[1]),
        "projection": "PCA to 2D",
        "explained_variance_2d": round(explained, 3),
        "generated_at": dt.date.today().isoformat(),
        "script": "scripts/lesson-03/generate_embedding_map.py",
        "library": f"transformers {transformers.__version__}, torch {torch.__version__}, numpy {np.__version__}",
        "words": items,
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("wrote", OUT, "explained", explained)


if __name__ == "__main__":
    main()
