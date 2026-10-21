"""LLM scoring of an assignment's custom rubric.

Same pattern as `llm_code_review.py` (cached system prompt, structured output
forced via tool_choice, the configured review model), but the criteria come
from the instructor's rubric instead of a fixed list. The rubric is part of
the cached system prompt, so every submission of one assignment reuses it.

The deterministic code metrics are handed to the model as evidence only; the
score of each criterion is the model's (clamped to [0, max]).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic
import nbformat

from app.core.config import get_settings

logger = logging.getLogger(__name__)

TOOL_NAME = "submit_rubric_scores"

SYSTEM_PROMPT = """You are an experienced TA assisting a senior lecturer in
grading data-science homework and project notebooks submitted in an Israeli
university course on Applied Machine Learning.

For every submission you will receive:
  - the executed Jupyter notebook, flattened to text with numbered cells
    ([cell N] markers) holding markdown, code and outputs;
  - sometimes the written report (text extracted from the PDF);
  - automatic measurements of the notebook (counts of models, plots,
    preprocessing calls, ...). They are EVIDENCE to weigh, not scores: they
    can miss things or count the wrong thing.

Score the submission on the lecturer's rubric below. Each criterion has its
own maximum; give any score from 0 up to that maximum (halves are fine).
When a criterion lists levels, use them to place the score.

Rubric:
{rubric}

Guidance:
  - These are undergraduate notebooks: calibrate against competent end-of-course
    work, not published research. Reserve the maximum for genuinely strong work
    and 0 for content that is missing or wholly off-topic.
  - Judge each criterion on its own description only.
  - Each rationale is one or two short sentences in Hebrew that cite the
    evidence by cell, e.g. "[cell 12]".

You must respond by calling the `{tool}` tool exactly once. Do not produce any
other output."""


@dataclass(frozen=True)
class CriterionSpec:
    id: int
    name: str
    description: str
    max_points: float
    levels: list[dict[str, Any]]

    @property
    def key(self) -> str:
        return f"c{self.id}"


@dataclass
class RubricReviewResult:
    model: str
    # {criterion_id: (score clamped to [0, max], rationale)}
    scores: dict[int, tuple[float, str]]
    usage: dict[str, int]


class LLMRubricReviewError(RuntimeError):
    pass


def _fmt_points(value: float) -> str:
    return f"{value:g}"


def format_rubric(criteria: list[CriterionSpec]) -> str:
    lines: list[str] = []
    for c in criteria:
        lines.append(f"  - {c.key}: {c.name} (max {_fmt_points(c.max_points)} points)")
        if c.description.strip():
            lines.append(f"      {c.description.strip()}")
        for level in c.levels:
            lines.append(f"      * {_fmt_points(float(level.get('points', 0)))} points: {level.get('description', '')}")
    return "\n".join(lines)


def _system_blocks(criteria: list[CriterionSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT.format(rubric=format_rubric(criteria), tool=TOOL_NAME),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def build_tool(criteria: list[CriterionSpec]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for c in criteria:
        properties[c.key] = {
            "type": "object",
            "additionalProperties": False,
            "description": c.name,
            "properties": {
                "score": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": c.max_points,
                    "description": f"0 to {_fmt_points(c.max_points)}.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One or two short Hebrew sentences citing cells, e.g. [cell 12].",
                },
            },
            "required": ["score", "rationale"],
        }
    return {
        "name": TOOL_NAME,
        "description": "Submit a score and rationale for every rubric criterion. Call exactly once.",
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "scores": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": properties,
                    "required": [c.key for c in criteria],
                }
            },
            "required": ["scores"],
        },
    }


def notebook_text_with_cells(ipynb_path: str, limit: int = 60_000) -> str:
    """Markdown, code and text outputs, each cell headed by [cell N] (1-based)
    so rationales can cite cells."""
    nb = nbformat.read(ipynb_path, as_version=4)
    chunks: list[str] = []
    for idx, cell in enumerate(nb.cells, start=1):
        parts = [f"[cell {idx}] ({cell.cell_type})", cell.get("source") or ""]
        if cell.cell_type == "code":
            for out in cell.get("outputs", []):
                kind = out.get("output_type")
                if kind == "stream":
                    parts.append(str(out.get("text", "")))
                elif kind in {"execute_result", "display_data"}:
                    data = out.get("data", {})
                    if "text/plain" in data:
                        parts.append(str(data["text/plain"]))
                    if any(k.startswith("image/") for k in data):
                        parts.append("<image output>")
                elif kind == "error":
                    parts.append(f"ERROR {out.get('ename', '')}: {out.get('evalue', '')}")
        chunks.append("\n".join(p for p in parts if p))
    text = "\n\n".join(chunks)
    if len(text) > limit:
        text = text[:limit] + "\n…[truncated]…"
    return text


def build_user_message(notebook_text: str, report_text: str | None, evidence: dict[str, Any]) -> str:
    sections = [
        "Here is one student submission to score.",
        "=== EXECUTED NOTEBOOK ===\n" + (notebook_text.strip() or "(no executed notebook text)"),
    ]
    if report_text is not None:
        report = report_text.strip() or "(the report PDF has no extractable text)"
        if len(report) > 30_000:
            report = report[:30_000] + "\n…[truncated]…"
        sections.append("=== WRITTEN REPORT ===\n" + report)
    sections.append(
        "=== AUTOMATIC MEASUREMENTS (evidence, not scores) ===\n"
        + json.dumps(evidence, ensure_ascii=False, indent=1)
    )
    sections.append(f"Call `{TOOL_NAME}` with a score and Hebrew rationale for every criterion.")
    return "\n\n".join(sections)


def clamp_score(value: Any, max_points: float) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMRubricReviewError(f"non-numeric score {value!r}") from exc
    if score != score:  # NaN
        raise LLMRubricReviewError("NaN score")
    return max(0.0, min(float(max_points), score))


def parse_scores(tool_input: Any, criteria: list[CriterionSpec]) -> dict[int, tuple[float, str]]:
    scores = tool_input.get("scores") if isinstance(tool_input, dict) else None
    if isinstance(scores, str):
        try:
            scores = json.loads(scores)
        except json.JSONDecodeError as exc:
            raise LLMRubricReviewError("scores payload is a malformed string") from exc
    if not isinstance(scores, dict):
        raise LLMRubricReviewError(f"scores is not an object: {type(scores).__name__}")

    out: dict[int, tuple[float, str]] = {}
    for c in criteria:
        payload = scores.get(c.key)
        if not isinstance(payload, dict) or "score" not in payload:
            continue
        try:
            score = clamp_score(payload["score"], c.max_points)
        except LLMRubricReviewError:
            logger.warning("llm_rubric_review: unusable score for %s: %r", c.key, payload.get("score"))
            continue
        out[c.id] = (score, str(payload.get("rationale", "")))
    return out


def review_rubric(
    criteria: list[CriterionSpec],
    notebook_text: str,
    report_text: str | None,
    evidence: dict[str, Any],
) -> RubricReviewResult:
    """Score every criterion via Claude. Synchronous.

    Raises LLMRubricReviewError on a missing API key or an unusable response;
    criteria the model left out are simply absent from `scores`."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise LLMRubricReviewError("ANTHROPIC_API_KEY is not set; custom rubric LLM scoring disabled.")
    if not criteria:
        raise LLMRubricReviewError("rubric has no criteria")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model=settings.llm_review_model,
        max_tokens=4000,
        system=_system_blocks(criteria),
        tools=[build_tool(criteria)],
        tool_choice={"type": "tool", "name": TOOL_NAME},
        messages=[{"role": "user", "content": build_user_message(notebook_text, report_text, evidence)}],
    )
    if response.stop_reason == "max_tokens":
        logger.warning("llm_rubric_review hit max_tokens; output likely truncated")

    tool_input = next(
        (b.input for b in response.content if b.type == "tool_use" and b.name == TOOL_NAME),
        None,
    )
    if tool_input is None:
        raise LLMRubricReviewError(f"Model did not call {TOOL_NAME}; stop_reason={response.stop_reason}")

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    logger.info(
        "llm_rubric_review usage model=%s in=%d out=%d cache_w=%d cache_r=%d",
        settings.llm_review_model,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_creation_input_tokens"],
        usage["cache_read_input_tokens"],
    )
    return RubricReviewResult(model=settings.llm_review_model, scores=parse_scores(tool_input, criteria), usage=usage)
