"""A small synthetic guided lesson for the lesson tests, independent of the
real lesson-2 fixture (which has its own test in test_lesson_content.py).

Steps: intro (A: practice choice + ack), write (B: practice free text + an
individual check), lab (C: experiment log + commitment), extra (optional:
one practice question). Assets live under /lessons/test/v1/ in an assets root
the tests create with write_assets().
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

CSV_BYTES = "customer_id,visits_30d,days_since_purchase,bought_next_week\n1001,4,8,0\n1002,12,7,1\n".encode()
TREE = {
    "root": 0,
    "feature_labels_he": {"visits_30d": "ביקורים ב-30 ימים", "days_since_purchase": "ימים מאז הרכישה"},
    "nodes": [
        {"id": 0, "is_leaf": False, "feature": "visits_30d", "threshold": 13.5, "left": 1, "right": 2,
         "training_examples": 10, "class_counts": [6, 4], "prediction": 0},
        {"id": 1, "is_leaf": True, "feature": None, "threshold": None, "left": None, "right": None,
         "training_examples": 6, "class_counts": [5, 1], "prediction": 0},
        {"id": 2, "is_leaf": True, "feature": None, "threshold": None, "left": None, "right": None,
         "training_examples": 4, "class_counts": [1, 3], "prediction": 1},
    ],
}
TREE_BYTES = json.dumps(TREE).encode()
ASSET_DIR = ("lessons", "test", "v1")


def write_assets(root: Path) -> Path:
    folder = root.joinpath(*ASSET_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "data.csv").write_bytes(CSV_BYTES)
    (folder / "tree.json").write_bytes(TREE_BYTES)
    return root


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _leaf(node_id: int, prediction: int) -> dict:
    return {"id": node_id, "is_leaf": True, "feature": None, "threshold": None, "left": None, "right": None,
            "prediction": prediction}


def sample_content(course_code: str = "AI") -> dict:
    return {
        "schema_version": 1,
        "slug": "test-lesson",
        "title": "שיעור ניסוי",
        "guiding_question": "מתי **אפשר** לסמוך על `model`?",
        "course_code": course_code,
        "intro": "שיעור קצר [[A/B]] לבדיקות.",
        "assets": {
            "csv": {"path": "/lessons/test/v1/data.csv", "filename": "data.csv", "mime": "text/csv",
                    "label": "נתונים", "sha256": _sha(CSV_BYTES)},
            "tree_json": {"path": "/lessons/test/v1/tree.json", "filename": "tree.json", "mime": "application/json",
                          "label": "העץ", "sha256": _sha(TREE_BYTES)},
        },
        "steps": [
            {
                "key": "intro",
                "letter": "A",
                "title": "פתיחה",
                "goal": "מה מנבאים?",
                "blocks": [
                    {"type": "text", "body": ["שורה אחת = לקוח אחד.", "העמודה `bought_next_week` היא התווית."]},
                    {"type": "table", "caption": "דוגמה", "columns": [{"label": "לקוח", "ltr": True}, {"label": "ביקורים"}],
                     "rows": [["1001", "4"], ["1002", "12"]]},
                    {"type": "section", "label": "check", "title": "בודקים", "blocks": [
                        {"type": "question", "question": "q_pick"},
                    ]},
                    {"type": "ack", "key": "read_intro", "label": "קראתי"},
                    {"type": "link", "target": "peer_review", "label": "להצגות"},
                ],
                "completion": [{"type": "answered", "question": "q_pick"}, {"type": "ack", "key": "read_intro"}],
                "next_hint": "ממשיכים לכתיבה.",
            },
            {
                "key": "write",
                "letter": "B",
                "title": "כותבים",
                "goal": "איך מסבירים?",
                "blocks": [
                    {"type": "download", "asset": "csv", "label": "הורדה"},
                    {"type": "prompt", "title": "פרומפט", "text": "Check `raw` **without** changing it."},
                    {"type": "expander", "title": "עוד", "blocks": [{"type": "list", "ordered": True, "items": ["א", "ב"]}]},
                    {"type": "question", "question": "q_free"},
                    {"type": "callout", "tone": "info", "body": ["בדיקה אישית"]},
                    {"type": "question", "question": "q_check"},
                    {"type": "manual_tree", "feature_labels": {"visits_30d": "ביקורים"}, "root": 0,
                     "nodes": [{"id": 0, "is_leaf": False, "feature": "visits_30d", "threshold": 5, "left": 1, "right": 2,
                                "prediction": 0}, _leaf(1, 0), _leaf(2, 1)],
                     "customers": [{"id": "A", "label": "לקוח A", "visits_30d": 4, "days_since_purchase": 8}]},
                    {"type": "actual_tree", "asset": "tree_json", "examples": [{"visits_30d": 14, "days_since_purchase": 7}]},
                ],
                "completion": [{"type": "answered", "question": "q_free"}, {"type": "answered", "question": "q_check"}],
            },
            {
                "key": "lab",
                "letter": "C",
                "title": "מעבדה",
                "goal": "מה קורה כשמשנים עומק?",
                "blocks": [
                    {"type": "colab", "notebook_asset": "csv", "instructions": ["פותחים"], "return_note": "חוזרים לכאן"},
                    {"type": "code", "code": "tree_depth = 2\ntraining_examples = 100", "highlight_lines": [1, 2]},
                    {"type": "split_illustration", "feature_label": "ביקורים",
                     "points": [{"value": 2, "label": 0}, {"value": 9, "label": 1}], "candidate_thresholds": [3, 6.5]},
                    {"type": "experiment_log", "min_complete": 1, "suggested_runs": [
                        {"depth_kind": "limited", "depth": 2, "training_examples": 100, "note": "ריצה ראשונה"},
                        {"depth_kind": "unlimited", "depth": None, "training_examples": 100, "note": "ללא הגבלה"},
                    ]},
                    {"type": "commitment"},
                    {"type": "summary"},
                ],
                "completion": [{"type": "experiments", "min_complete": 1}, {"type": "commitment"}],
            },
            {
                "key": "extra",
                "letter": "+",
                "title": "הרחבה",
                "goal": "ומה עם אשכולות?",
                "optional": True,
                "blocks": [{"type": "question", "question": "q_extra"}],
                "completion": [{"type": "answered", "question": "q_extra"}],
            },
        ],
        "questions": {
            "q_pick": {
                "key": "q_pick", "step": "intro", "mode": "practice", "type": "single_choice",
                "prompt": "מהי התווית?",
                "options": [{"id": "a", "text": "`bought_next_week`"}, {"id": "b", "text": "`visits_30d`"},
                            {"id": "c", "text": "`customer_id`"}],
                "answer": {
                    "correct": ["a"],
                    "feedback": {"a": "נכון: זה מה שמנבאים.", "b": "זו תכונה, לא תווית.", "c": "זה מזהה."},
                    "misconceptions": {"b": "feature-as-label", "c": "id-as-label"},
                    "explanation": "התווית היא מה שמנסים לחזות.",
                },
            },
            "q_free": {
                "key": "q_free", "step": "write", "mode": "practice", "type": "free_text",
                "prompt": "תארו ממצא אחד.", "min_chars": 5,
                "answer": {"sample_reasoning": ["יש ערך חסר."], "rubric": ["מתאר ממצא", "מציע בדיקה"]},
            },
            "q_check": {
                "key": "q_check", "step": "write", "mode": "check", "type": "single_choice",
                "prompt": "לאן הולך לקוח (15, 60)?", "explain": "required", "explain_prompt": "הסבירו",
                "options": [{"id": "x", "text": "ימינה"}, {"id": "y", "text": "שמאלה"}, {"id": "z", "text": "לא ידוע"}],
                "answer": {
                    "correct": ["x"],
                    "feedback": {"x": "נכון.", "y": "15 > 13.5.", "z": "אפשר לדעת."},
                    "misconceptions": {"y": "threshold-direction"},
                    "explanation": "15 גדול מ-13.5 ולכן ימינה.",
                },
            },
            "q_extra": {
                "key": "q_extra", "step": "extra", "mode": "practice", "type": "single_choice",
                "prompt": "מספר אשכול הוא…",
                "options": [{"id": "id", "text": "מזהה"}, {"id": "rank", "text": "דירוג"}],
                "answer": {
                    "correct": ["id"],
                    "feedback": {"id": "נכון.", "rank": "המספרים שרירותיים."},
                    "misconceptions": {"rank": "cluster-id-as-rank"},
                    "explanation": "מספרי אשכולות הם מזהים.",
                },
            },
        },
    }
