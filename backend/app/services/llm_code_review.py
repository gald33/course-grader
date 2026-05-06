"""LLM scoring for the two HW2 / project_code rubric dimensions that resist
deterministic auto-grading: `processing_description` and `models_quality`.

Mirrors the structure of `llm_review.py` (system prompt cached, structured
output forced via tool_choice) but takes only the executed notebook (no PDF
report) and returns just the two dimension scores plus rationales.

Called from `run_notebook` after the deterministic scorers in `code_metrics.py`.
Best-effort — if the API key is missing or the call fails, the run still
succeeds and the two dims simply don't get a fresh score (existing rows are
left untouched).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)


CODE_REVIEW_DIMENSIONS: dict[str, str] = {
    "processing_description": (
        "Do the markdown cells in the notebook EXPLAIN the preprocessing — "
        "WHY missing values were handled this way, WHY this encoding/scaling "
        "was chosen, what feature engineering was done and why. This is about "
        "the narrative quality, not whether preprocessing happened."
    ),
    "models_quality": (
        "Are the model choices appropriate for the task and dataset? Consider "
        "task fit (classification vs regression, binary vs multi-class), "
        "variety beyond a single family, and whether nonlinear/ensemble methods "
        "are present where the data warrants. Penalize 'kitchen sink' submissions "
        "that throw every estimator without thought, and reward thoughtful selection."
    ),
}


SYSTEM_PROMPT = """You are an experienced TA assisting a senior lecturer in
grading data-science homework and project notebooks submitted in an Israeli
university course on Applied Machine Learning.

For every submission you will receive the executed Jupyter notebook (text-only
flatten of code + outputs + markdown). Usually Python with English code and
Hebrew or English markdown / comments.

Your job is to score TWO rubric dimensions from 0 to 5, each with a one-sentence
Hebrew rationale that points to concrete evidence in the notebook.

Rubric dimensions:
{rubric}

Scoring scale (use whole numbers only):
  0 — Missing or unintelligible
  1 — Present but seriously inadequate
  2 — Below expectations; major gaps
  3 — Adequate; meets minimum bar with some weaknesses
  4 — Good; clearly addressed with minor gaps
  5 — Excellent; thorough, well justified, well presented

Calibration guidance:
  - These are undergraduate notebooks — calibrate against "competent end-of-course
    work", not against published research. Most scores should land in 2–4.
  - Reserve 5 for genuinely strong work and 0 for content that is missing or
    wholly off-topic. Don't hand out 5s reflexively.
  - For `processing_description`: judge the markdown narrative around
    preprocessing, NOT the code itself. Counts of `dropna`/`fillna`/etc. are
    scored separately by a deterministic check — your job is to assess whether
    a reader can understand WHY the student made those choices.
  - For `models_quality`: count of models is scored separately (≥3 deterministic).
    Your job is to assess whether the chosen models make sense for the task.
  - Rationales must be ≤1 short sentence in Hebrew, citing concrete evidence.

You must respond by calling the `submit_code_scores` tool exactly once. Do not
produce any other output."""


@dataclass
class CodeReviewResult:
    """LLM-produced scores for the two judgment dims."""

    model: str
    scores: dict[str, dict[str, Any]]  # {dim_key: {"score": int, "rationale": str}}
    usage: dict[str, int]


def _build_tool() -> dict[str, Any]:
    score_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": list(CODE_REVIEW_DIMENSIONS.keys()),
    }
    for key in CODE_REVIEW_DIMENSIONS:
        score_schema["properties"][key] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 5,
                    "description": "Whole number 0–5 per the scale in the system prompt.",
                },
                "rationale": {
                    "type": "string",
                    "description": "One short Hebrew sentence citing concrete evidence.",
                },
            },
            "required": ["score", "rationale"],
        }

    return {
        "name": "submit_code_scores",
        "description": (
            "Submit scores for the two code rubric dimensions. Call exactly once."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"scores": score_schema},
            "required": ["scores"],
        },
    }


def _format_rubric() -> str:
    return "\n".join(f"  - {key}: {desc}" for key, desc in CODE_REVIEW_DIMENSIONS.items())


def _system_blocks() -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT.format(rubric=_format_rubric()),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _build_user_message(notebook_text: str) -> str:
    nb_section = notebook_text.strip() or "(no executed notebook text)"
    if len(nb_section) > 50_000:
        nb_section = nb_section[:50_000] + "\n…[truncated]…"
    return (
        "Here is one student submission's executed notebook to score.\n\n"
        "=== EXECUTED NOTEBOOK (code + outputs + markdown) ===\n"
        f"{nb_section}\n\n"
        "Call `submit_code_scores` with your scores and Hebrew rationales."
    )


class LLMCodeReviewError(RuntimeError):
    pass


def review_code_dimensions(notebook_text: str) -> CodeReviewResult:
    """Score the two judgment code dims via Claude. Synchronous.

    Raises LLMCodeReviewError on missing API key or unexpected response shape.
    Caller should catch and continue (best-effort scoring)."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise LLMCodeReviewError(
            "ANTHROPIC_API_KEY is not set — code-dimension LLM scoring disabled."
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tool = _build_tool()

    response = client.messages.create(
        model=settings.llm_review_model,
        max_tokens=2000,
        system=_system_blocks(),
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_code_scores"},
        messages=[{"role": "user", "content": _build_user_message(notebook_text)}],
    )

    if response.stop_reason == "max_tokens":
        logger.warning("llm_code_review hit max_tokens — output likely truncated")

    tool_input: dict[str, Any] | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_code_scores":
            tool_input = block.input  # type: ignore[assignment]
            break
    if tool_input is None:
        raise LLMCodeReviewError(
            f"Model did not call submit_code_scores; stop_reason={response.stop_reason}"
        )

    scores = tool_input.get("scores", {})
    if isinstance(scores, str):
        try:
            scores = json.loads(scores)
        except json.JSONDecodeError as exc:
            raise LLMCodeReviewError(
                f"submit_code_scores payload malformed (string scores; "
                f"stop_reason={response.stop_reason})"
            ) from exc

    if not isinstance(scores, dict):
        raise LLMCodeReviewError(
            f"submit_code_scores scores not a dict: type={type(scores).__name__}"
        )

    missing = [k for k in CODE_REVIEW_DIMENSIONS if k not in scores]
    if missing:
        raise LLMCodeReviewError(f"submit_code_scores missing dimensions: {missing}")

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }
    logger.info(
        "llm_code_review usage model=%s in=%d out=%d cache_w=%d cache_r=%d",
        settings.llm_review_model,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_creation_input_tokens"],
        usage["cache_read_input_tokens"],
    )

    return CodeReviewResult(
        model=settings.llm_review_model,
        scores=scores,
        usage=usage,
    )
