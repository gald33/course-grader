"""Deterministic auto-scoring for HW2 / project_code rubric dimensions.

Each scoring function returns a `Scored(score, rationale)` pair. The run
pipeline feeds the score through `apply_curve` and writes a
`RubricDimensionScore` row, and the rationale into `code_review_json` on the
submission for display next to the score in the rubric UI (mirrors how
project-report LLM rationales are surfaced).

Coverage (9 of the 12 code dimensions; english_comments stays in
`english_comments.py`; processing_description and models_quality are LLM-scored
in `llm_code_review.py`):

    data_scope_adequacy        — rows in the largest staged data file
    processing_implementation  — count of distinct preprocessing primitives used
    num_models_baseline        — distinct sklearn-style estimator classes
    experiments_comparison     — min(distinct .fit() calls, distinct metric fns)
    variable_plots             — plot calls in cells before the first .fit()
    results_plots              — plot calls in cells after the first .fit()
    order                      — markdown headings + recognized section titles
    clarity                    — non-trivial markdown chars / code chars
    code_quality               — ruff warnings per 100 LOC on flattened code
"""

from __future__ import annotations

import logging
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, NamedTuple

import nbformat

logger = logging.getLogger(__name__)


class Scored(NamedTuple):
    """A 0–5 raw score with a short human-readable explanation."""
    score: float
    rationale: str


# ---------- Vocabulary ----------

ESTIMATOR_PATTERNS: tuple[str, ...] = (
    "LogisticRegression", "LinearRegression", "Ridge", "Lasso", "ElasticNet",
    "RandomForestClassifier", "RandomForestRegressor",
    "GradientBoostingClassifier", "GradientBoostingRegressor",
    "HistGradientBoostingClassifier", "HistGradientBoostingRegressor",
    "DecisionTreeClassifier", "DecisionTreeRegressor",
    "SVC", "SVR", "LinearSVC", "LinearSVR",
    "KNeighborsClassifier", "KNeighborsRegressor",
    "GaussianNB", "MultinomialNB", "BernoulliNB",
    "MLPClassifier", "MLPRegressor",
    "XGBClassifier", "XGBRegressor", "XGBRanker",
    "LGBMClassifier", "LGBMRegressor",
    "CatBoostClassifier", "CatBoostRegressor",
    "DummyClassifier", "DummyRegressor",
    "AdaBoostClassifier", "AdaBoostRegressor",
    "ExtraTreesClassifier", "ExtraTreesRegressor",
    "VotingClassifier", "VotingRegressor",
    "StackingClassifier", "StackingRegressor",
    "BaggingClassifier", "BaggingRegressor",
    "Sequential",
)

PREPROCESSING_TOKENS: tuple[str, ...] = (
    ".dropna(", ".fillna(",
    "StandardScaler(", "MinMaxScaler(", "RobustScaler(", "Normalizer(",
    "OneHotEncoder(", "LabelEncoder(", "OrdinalEncoder(",
    "get_dummies(", "train_test_split(",
    "Pipeline(", "ColumnTransformer(", "make_pipeline(", "make_column_transformer(",
    "SimpleImputer(", "KNNImputer(",
    ".astype(", ".apply(", ".map(",
    "PolynomialFeatures(",
)

METRIC_TOKENS: tuple[str, ...] = (
    "accuracy_score", "f1_score", "precision_score", "recall_score",
    "roc_auc_score", "confusion_matrix", "classification_report",
    "mean_squared_error", "mean_absolute_error", "r2_score",
    "log_loss", "balanced_accuracy_score", "matthews_corrcoef",
    "explained_variance_score", "median_absolute_error",
)

PLOT_TOKENS: tuple[str, ...] = (
    "plt.figure", "plt.show", "plt.plot", "plt.hist", "plt.bar", "plt.scatter",
    "plt.boxplot", "plt.imshow", "plt.subplots",
    "sns.histplot", "sns.boxplot", "sns.scatterplot", "sns.pairplot",
    "sns.heatmap", "sns.countplot", "sns.barplot", "sns.lineplot",
    "sns.violinplot", "sns.kdeplot", "sns.regplot", "sns.jointplot",
    ".plot(", ".hist(", ".boxplot(",
    "px.scatter", "px.line", "px.bar", "px.histogram",
)

EXPECTED_SECTIONS: tuple[str, ...] = (
    "data", "preprocess", "model", "result",
    "introduction", "intro", "conclusion", "evaluation",
    "exploration", "eda", "analysis", "feature",
)


# ---------- Notebook helpers ----------

def _read_notebook(path: str | Path) -> nbformat.NotebookNode:
    return nbformat.read(str(path), as_version=4)


def _code_cells(nb) -> list:
    return [c for c in nb.cells if c.cell_type == "code" and (c.source or "").strip()]


def _markdown_cells(nb) -> list:
    return [c for c in nb.cells if c.cell_type == "markdown" and (c.source or "").strip()]


def _all_code_text(nb) -> str:
    return "\n".join(c.source or "" for c in _code_cells(nb))


def _split_at_first_fit(nb) -> tuple[list, list]:
    code_cells = _code_cells(nb)
    for i, c in enumerate(code_cells):
        if re.search(r"\.fit\s*\(", c.source or ""):
            return code_cells[:i], code_cells[i:]
    return code_cells, []


def _curve(value: float, breakpoints: tuple[tuple[float, float], ...]) -> float:
    """Step function. breakpoints = ((threshold, score), …) sorted ascending.
    Returns the score for the highest threshold ≤ value."""
    score = 0.0
    for threshold, s in breakpoints:
        if value >= threshold:
            score = s
        else:
            break
    return float(score)


# ---------- Data scope ----------

def _count_rows(file: Path) -> int | None:
    """Best-effort row count without loading the whole file into memory."""
    try:
        suffix = file.suffix.lower()
        if suffix == ".csv" or suffix == ".tsv" or suffix == ".txt":
            with file.open("rb") as fh:
                lines = sum(1 for _ in fh)
            return max(0, lines - 1)
        if suffix in (".xlsx", ".xls"):
            from openpyxl import load_workbook
            wb = load_workbook(file, read_only=True, data_only=True)
            try:
                ws = wb.active
                return max(0, (ws.max_row or 1) - 1)
            finally:
                wb.close()
        if suffix == ".json":
            with file.open("rb") as fh:
                lines = sum(1 for _ in fh)
            return lines  # works for newline-delimited JSON; over-estimates for arrays
        if suffix == ".parquet":
            try:
                import pyarrow.parquet as pq
                return pq.ParquetFile(str(file)).metadata.num_rows
            except Exception:  # noqa: BLE001
                return None
    except Exception:  # noqa: BLE001
        logger.exception("data_scope: failed to count rows in %s", file)
    return None


def data_scope_adequacy_score(staged_data_dir: str | Path) -> Scored:
    """Score by max rows across staged data files. Per assignment instructions,
    students should have hundreds of data points minimum."""
    p = Path(staged_data_dir)
    if not p.exists():
        return Scored(0.0, "No staged data directory found.")

    largest_file: str | None = None
    max_rows = 0
    counted = 0
    for f in p.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".csv", ".tsv", ".txt", ".xlsx", ".xls", ".json", ".parquet"):
            continue
        rows = _count_rows(f)
        if rows is None:
            continue
        counted += 1
        if rows > max_rows:
            max_rows = rows
            largest_file = f.name

    if counted == 0:
        return Scored(0.0, "No data files staged for this submission.")

    score = _curve(max_rows, ((0, 0), (50, 1), (100, 2), (250, 3), (1000, 4), (5000, 5)))
    rationale = f"Largest data file: {largest_file} with {max_rows:,} rows ({counted} data file{'s' if counted != 1 else ''} staged)."
    return Scored(score, rationale)


# ---------- Processing implementation ----------

def processing_implementation_score(notebook_path: str | Path) -> Scored:
    nb = _read_notebook(notebook_path)
    code = _all_code_text(nb)
    found = [tok.rstrip("(").lstrip(".") for tok in PREPROCESSING_TOKENS if tok in code]
    distinct = len(found)
    score = _curve(distinct, ((0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (6, 5)))
    if distinct == 0:
        rationale = "No preprocessing primitives detected in code."
    else:
        names = ", ".join(found[:8]) + (", …" if distinct > 8 else "")
        rationale = f"{distinct} distinct preprocessing primitive{'s' if distinct != 1 else ''}: {names}."
    return Scored(score, rationale)


# ---------- Models / baseline ----------

def num_models_baseline_score(notebook_path: str | Path) -> Scored:
    """≥3 models → 5 per assignment requirement. Counts distinct estimator
    classes that are *instantiated* (followed by an opening paren)."""
    nb = _read_notebook(notebook_path)
    code = _all_code_text(nb)
    found = [cls for cls in ESTIMATOR_PATTERNS if re.search(rf"\b{cls}\s*\(", code)]
    distinct = len(found)
    score = _curve(distinct, ((0, 0), (1, 1), (2, 3), (3, 5)))
    if distinct == 0:
        rationale = "No sklearn-style estimator classes instantiated."
    else:
        names = ", ".join(found[:6]) + (", …" if distinct > 6 else "")
        meets = " — meets the ≥3 requirement" if distinct >= 3 else f" — short of the ≥3 requirement (need {3 - distinct} more)"
        rationale = f"{distinct} distinct estimator{'s' if distinct != 1 else ''} ({names}){meets}."
    return Scored(score, rationale)


# ---------- Experiments comparison ----------

def experiments_comparison_score(notebook_path: str | Path) -> Scored:
    nb = _read_notebook(notebook_path)
    code = _all_code_text(nb)
    fit_count = len(re.findall(r"\.fit\s*\(", code))
    metrics_used = [m for m in METRIC_TOKENS if m in code]
    distinct_metrics = len(metrics_used)
    val = min(fit_count, distinct_metrics)
    score = _curve(val, ((0, 0), (1, 1), (2, 3), (3, 4), (4, 5)))
    metric_names = ", ".join(metrics_used[:5]) + (", …" if distinct_metrics > 5 else "") if metrics_used else "none"
    rationale = (
        f"{fit_count} .fit() call{'s' if fit_count != 1 else ''} × "
        f"{distinct_metrics} distinct metric function{'s' if distinct_metrics != 1 else ''} "
        f"({metric_names}); score = min({fit_count}, {distinct_metrics}) → {int(val)}."
    )
    return Scored(score, rationale)


# ---------- Plots ----------

def _count_plots(cells: list) -> int:
    text = "\n".join(c.source or "" for c in cells)
    return sum(text.count(tok) for tok in PLOT_TOKENS)


def variable_plots_score(notebook_path: str | Path) -> Scored:
    nb = _read_notebook(notebook_path)
    before, after = _split_at_first_fit(nb)
    n = _count_plots(before)
    score = _curve(n, ((0, 0), (1, 1), (2, 2), (3, 3), (4, 4), (6, 5)))
    if not after:
        location = "no .fit() found, so all plot calls counted here"
    else:
        location = f"in {len(before)} cell{'s' if len(before) != 1 else ''} before the first .fit()"
    rationale = f"{n} plot call{'s' if n != 1 else ''} {location}."
    return Scored(score, rationale)


def results_plots_score(notebook_path: str | Path) -> Scored:
    nb = _read_notebook(notebook_path)
    _, after = _split_at_first_fit(nb)
    n = _count_plots(after)
    code = "\n".join(c.source or "" for c in after)
    bonus_present = ("confusion_matrix" in code or "feature_importances_" in code or "ConfusionMatrixDisplay" in code)
    bonus = 1 if bonus_present else 0
    score = _curve(min(n + bonus, 6), ((0, 0), (1, 1), (2, 3), (3, 4), (4, 5)))
    if not after:
        rationale = "No code cells found after the first .fit() call."
    else:
        bits = [f"{n} plot call{'s' if n != 1 else ''} after the first .fit()"]
        if bonus:
            bits.append("bonus +1 for confusion_matrix or feature_importances_")
        rationale = "; ".join(bits) + "."
    return Scored(score, rationale)


# ---------- Order ----------

def order_score(notebook_path: str | Path) -> Scored:
    nb = _read_notebook(notebook_path)
    headings: list[str] = []
    for c in _markdown_cells(nb):
        for line in (c.source or "").splitlines():
            stripped = line.lstrip()
            if stripped.startswith("#"):
                headings.append(stripped.lstrip("#").strip().lower())
    n = len(headings)
    if n == 0:
        return Scored(0.0, "No markdown headings (#) found.")

    sections_present = [s for s in EXPECTED_SECTIONS if any(s in h for h in headings)]
    if n >= 4 and len(sections_present) >= 3:
        score = 5.0
    else:
        score = _curve(n, ((0, 0), (1, 1), (3, 2), (4, 3), (5, 4)))
    sec_str = ", ".join(sections_present[:5]) if sections_present else "none recognized"
    rationale = (
        f"{n} markdown heading{'s' if n != 1 else ''}; "
        f"{len(sections_present)} expected section{'s' if len(sections_present) != 1 else ''} present ({sec_str})."
    )
    return Scored(score, rationale)


# ---------- Clarity ----------

def clarity_score(notebook_path: str | Path) -> Scored:
    """Ratio of substantive markdown chars (cells ≥30 chars) to code chars.
    Captures whether explanation accompanies the code at the cell level."""
    nb = _read_notebook(notebook_path)
    md_cells = [c for c in _markdown_cells(nb) if len(c.source or "") >= 30]
    md_chars = sum(len(c.source or "") for c in md_cells)
    code_chars = sum(len(c.source or "") for c in _code_cells(nb))
    if code_chars == 0:
        return Scored(0.0, "No code cells in the notebook.")
    ratio = md_chars / code_chars
    score = _curve(ratio, ((0, 0), (0.05, 1), (0.10, 2), (0.20, 3), (0.35, 4), (0.55, 5)))
    rationale = (
        f"{len(md_cells)} substantive markdown cell{'s' if len(md_cells) != 1 else ''} "
        f"({md_chars:,} chars) vs {code_chars:,} code chars → ratio {ratio:.2f}."
    )
    return Scored(score, rationale)


# ---------- Code quality ----------

def code_quality_score(notebook_path: str | Path) -> Scored:
    """Run `ruff check` on flattened code; score by real-bug warnings per 100 LOC.

    We restrict to pyflakes (`F`) checks — undefined names, unused imports —
    because they're meaningful in *any* Python file. Style rules (E/W) and
    F811 (redefinition) produce false positives when notebook cells are
    flattened (each cell legitimately imports its deps at the top), so we
    skip them.

    Falls back to 3.0 (neutral) if ruff isn't available — keeps the pipeline
    from failing on environments without the binary."""
    nb = _read_notebook(notebook_path)
    code = _all_code_text(nb)
    loc = max(1, sum(1 for line in code.splitlines() if line.strip()))

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            tmp_path = Path(f.name)
        result = subprocess.run(
            ["ruff", "check", "--select", "F", "--ignore", "F811",
             "--output-format=concise", "--no-fix", str(tmp_path)],
            capture_output=True, text=True, timeout=15,
        )
        warnings = sum(1 for line in result.stdout.splitlines() if ":" in line and tmp_path.name in line)
    except (subprocess.SubprocessError, FileNotFoundError):
        logger.warning("ruff unavailable; code_quality falling back to neutral 3.0")
        return Scored(3.0, "ruff not available — neutral fallback score.")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    per_100 = (warnings / loc) * 100
    if per_100 >= 10:
        score = 0.0
    elif per_100 >= 6:
        score = 1.0
    elif per_100 >= 4:
        score = 2.0
    elif per_100 >= 2:
        score = 3.0
    elif per_100 >= 0.5:
        score = 4.0
    else:
        score = 5.0
    rationale = (
        f"{warnings} ruff F warning{'s' if warnings != 1 else ''} on {loc} LOC "
        f"= {per_100:.2f} per 100 LOC."
    )
    return Scored(score, rationale)


# ---------- Aggregate driver ----------

def all_deterministic_scores(
    notebook_path: str | Path,
    staged_data_dir: str | Path,
) -> dict[str, Scored]:
    """Run every deterministic scorer; failures are logged and the dim is
    omitted (caller can decide to leave the row alone or write a 0)."""
    scorers: dict[str, Callable[[], Scored]] = {
        "data_scope_adequacy": lambda: data_scope_adequacy_score(staged_data_dir),
        "processing_implementation": lambda: processing_implementation_score(notebook_path),
        "num_models_baseline": lambda: num_models_baseline_score(notebook_path),
        "experiments_comparison": lambda: experiments_comparison_score(notebook_path),
        "variable_plots": lambda: variable_plots_score(notebook_path),
        "results_plots": lambda: results_plots_score(notebook_path),
        "order": lambda: order_score(notebook_path),
        "clarity": lambda: clarity_score(notebook_path),
        "code_quality": lambda: code_quality_score(notebook_path),
    }
    out: dict[str, Scored] = {}
    for key, fn in scorers.items():
        try:
            out[key] = fn()
        except Exception:  # noqa: BLE001
            logger.exception("code_metrics: %s failed", key)
    return out
