from __future__ import annotations

import json
import re
from dataclasses import dataclass

import nbformat

MODEL_KEYWORDS = [
    "logistic regression",
    "random forest",
    "xgboost",
    "lightgbm",
    "svm",
    "knn",
    "naive bayes",
    "neural network",
    "decision tree",
    "catboost",
]
METRIC_KEYWORDS = ["accuracy", "precision", "recall", "f1", "auc", "roc", "rmse", "mae", "r2"]


@dataclass
class ConsistencyResult:
    summary: str
    flags: list[str]


def _extract_signals(text: str) -> dict[str, set[str]]:
    lower = text.lower()
    models = {m for m in MODEL_KEYWORDS if m in lower}
    metrics = {m for m in METRIC_KEYWORDS if re.search(rf"\b{re.escape(m)}\b", lower)}
    hyperparams = set(re.findall(r"\b(?:max_depth|n_estimators|learning_rate|alpha|lambda|dropout)\s*=\s*[^\s,]+", lower))
    splits = set(re.findall(r"\b\d{1,2}/\d{1,2}\b", lower))
    if "train_test_split" in lower:
        splits.add("train_test_split")
    if "cross" in lower and "validation" in lower:
        splits.add("cross_validation")
    return {"models": models, "metrics": metrics, "hyperparams": hyperparams, "splits": splits}


def notebook_text_from_ipynb(ipynb_path: str) -> str:
    nb = nbformat.read(ipynb_path, as_version=4)
    chunks: list[str] = []
    for cell in nb.cells:
        if cell.cell_type == "code":
            chunks.append(cell.source or "")
            for out in cell.get("outputs", []):
                if out.get("output_type") == "stream":
                    chunks.append(out.get("text", ""))
                elif out.get("output_type") in {"execute_result", "display_data"}:
                    data = out.get("data", {})
                    if "text/plain" in data:
                        chunks.append(str(data.get("text/plain")))
                elif out.get("output_type") == "error":
                    chunks.extend(out.get("traceback", []))
    return "\n".join(chunks)


def compare_report_and_notebook(report_text: str, notebook_text: str) -> ConsistencyResult:
    report_signals = _extract_signals(report_text)
    notebook_signals = _extract_signals(notebook_text)

    flags: list[str] = []
    for key in ["models", "metrics", "hyperparams", "splits"]:
        missing_in_report = notebook_signals[key] - report_signals[key]
        missing_in_notebook = report_signals[key] - notebook_signals[key]
        if missing_in_report:
            flags.append(f"Missing in report ({key}): {', '.join(sorted(missing_in_report))}")
        if missing_in_notebook:
            flags.append(f"Missing in notebook ({key}): {', '.join(sorted(missing_in_notebook))}")

    if not flags:
        return ConsistencyResult(summary="Report and notebook appear consistent based on extracted signals.", flags=[])

    summary = "Potential mismatches detected between report and notebook artifacts."
    return ConsistencyResult(summary=summary, flags=flags)


def flags_to_json(flags: list[str]) -> str:
    return json.dumps(flags, ensure_ascii=False)
