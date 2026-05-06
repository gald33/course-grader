"""LLM review of project reports via Claude Sonnet 4.6.

Reads the project report PDF + executed notebook, returns suggested 0–5 scores
per project_report rubric dimension (with a Hebrew rationale each) plus a draft
Hebrew feedback paragraph the grader can edit.

Design:
- The static system prompt (rubric dim definitions, output instructions) is
  cached via `cache_control: ephemeral`. Sonnet 4.6's minimum cacheable prefix
  is 2048 tokens; ours sits comfortably above that.
- Structured output is enforced via tool use — `tool_choice` pins the
  `submit_review` tool so the model can only respond by calling it.
- Synchronous (no streaming) — invoked from a FastAPI handler that finishes
  inside the request lifecycle.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import anthropic

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# Rubric dimension keys mirror DIMENSIONS["project_report"] in the frontend.
PROJECT_REPORT_DIMENSIONS: dict[str, str] = {
    "research_question_hypothesis": (
        "Is there a clearly stated research question and hypothesis? Is it specific, "
        "answerable from the dataset, and motivated?"
    ),
    "data_description": (
        "Does the report describe the dataset (source, size, fields, time range, "
        "limitations)? Is there enough for a reader to know what's being analyzed?"
    ),
    "data_processing": (
        "Are cleaning, encoding, missing-value handling, and feature engineering "
        "described and justified? Do the choices make sense for the data?"
    ),
    "models_comparison": (
        "Does the report compare multiple models (or a model vs. a sensible baseline)? "
        "Are the choices justified, and is hyperparameter tuning addressed?"
    ),
    "results_analysis": (
        "Are results presented with appropriate metrics and visualizations? Are they "
        "interpreted — not just reported — and limitations acknowledged?"
    ),
    "consistency_with_code": (
        "Does the report match what the executed notebook actually does? Models, "
        "metrics, and conclusions in the report should be reflected in the code."
    ),
}


SYSTEM_PROMPT = """You are an experienced TA assisting a senior lecturer in grading
end-of-semester data-science project reports submitted in an Israeli university
course on Applied Machine Learning.

For every submission you will receive two pieces of student work:
  1. The project report (a PDF, given to you as plain text). Usually written in
     Hebrew, sometimes mixed with English technical terms.
  2. The executed Jupyter notebook (text-only flatten of code + outputs +
     markdown). Usually Python with English code and Hebrew comments.

Your job is to suggest a 0–5 score for each of these report-only rubric
dimensions, along with a one or two sentence rationale per dimension in Hebrew,
and to draft a short Hebrew feedback paragraph the lecturer can edit and send
to the students.

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
  - These are undergraduate projects — calibrate against "competent end-of-course
    work", not against published research. Most scores should land in the 2–4 range.
  - Reserve 5 for genuinely strong work and 0 for content that is missing or wholly
    off-topic. Don't hand out 5s reflexively.
  - The report PDF text may be incomplete (extracted from PDF). Score what's
    present; don't penalize missing content that's clearly an extraction artifact
    (e.g. images, charts, equations rendered as figures).
  - For `consistency_with_code`, base the score on whether the methods, models,
    and results described in the report match what the notebook actually
    contains. If the report mentions XGBoost but the notebook only has Random
    Forest, that's a real inconsistency.
  - Rationales must be in Hebrew, ≤2 short sentences, concrete (cite what you
    saw, not vague language).

The feedback paragraph (`feedback_he`) is what the students will read:
  - 3–5 sentences in Hebrew, written in second person plural (אתם / קיבלתם / כתבתם).
  - Open with one concrete strength.
  - Then 1–2 specific things they should improve, tied to what's actually in
    their submission.
  - Constructive and respectful — this is end of semester, the work is done.
  - Don't list scores; the lecturer will attach those separately.

You must respond by calling the `submit_review` tool exactly once with the full
structured payload. Do not produce any other output."""


@dataclass
class LLMReviewResult:
    """What the LLM produced. Persisted as JSON on the submission."""

    model: str
    dimensions: dict[str, dict[str, Any]]  # {dim_key: {"score": int, "rationale": str}}
    feedback_he: str
    usage: dict[str, int]  # input/output/cache token counts for cost telemetry


def _build_tool() -> dict[str, Any]:
    """JSON schema that forces the model into our exact output shape."""
    dim_schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
        "required": list(PROJECT_REPORT_DIMENSIONS.keys()),
    }
    for key in PROJECT_REPORT_DIMENSIONS:
        dim_schema["properties"][key] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "score": {
                    "type": "integer",
                    "description": "Whole number 0–5 per the scale in the system prompt. Must be exactly one of 0, 1, 2, 3, 4, or 5.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Up to 2 short sentences in Hebrew, concrete.",
                },
            },
            "required": ["score", "rationale"],
        }

    return {
        "name": "submit_review",
        # Strict mode forces the model to emit each typed field separately —
        # without it, Sonnet 4.6 sometimes serializes the whole object into the
        # first string-typed field and drops the rest.
        "strict": True,
        "description": (
            "Submit a complete review: per-dimension scores with Hebrew rationales, "
            "plus a Hebrew feedback paragraph for the students. Call this exactly once."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "dimensions": dim_schema,
                "feedback_he": {
                    "type": "string",
                    "description": "3–5 Hebrew sentences, second person plural.",
                },
            },
            "required": ["dimensions", "feedback_he"],
        },
    }


def _format_rubric() -> str:
    return "\n".join(
        f"  - {key}: {desc}" for key, desc in PROJECT_REPORT_DIMENSIONS.items()
    )


def _system_blocks() -> list[dict[str, Any]]:
    """System prompt as a single cacheable text block."""
    return [
        {
            "type": "text",
            "text": SYSTEM_PROMPT.format(rubric=_format_rubric()),
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _build_user_message(pdf_text: str, notebook_text: str) -> str:
    """Per-submission content. Sits after the cached system block."""
    pdf_section = pdf_text.strip() or "(no report PDF text — extraction returned empty)"
    nb_section = notebook_text.strip() or "(no executed notebook text)"
    # Truncate aggressively — Sonnet 4.6 has a 1M context but we don't need it
    # and the cost adds up. ~50k chars is plenty for a project report + notebook.
    if len(pdf_section) > 50_000:
        pdf_section = pdf_section[:50_000] + "\n…[truncated]…"
    if len(nb_section) > 50_000:
        nb_section = nb_section[:50_000] + "\n…[truncated]…"
    return (
        "Here is one student project submission to review.\n\n"
        "=== PROJECT REPORT (PDF text) ===\n"
        f"{pdf_section}\n\n"
        "=== EXECUTED NOTEBOOK (code + outputs + markdown) ===\n"
        f"{nb_section}\n\n"
        "Call `submit_review` with your scores, rationales, and feedback paragraph."
    )


class LLMReviewError(RuntimeError):
    pass


def dims_raw_trailing(raw: str, end: int) -> str:
    """Return text after a parsed JSON prefix in `raw`, trimmed."""
    if not isinstance(raw, str):
        return ""
    return raw[end:].strip()


def review_project_report(pdf_text: str, notebook_text: str) -> LLMReviewResult:
    """Run one LLM review pass. Synchronous — call from a FastAPI handler.

    Raises LLMReviewError on missing API key or unexpected response shape.
    """
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise LLMReviewError(
            "ANTHROPIC_API_KEY is not set — configure it in the backend environment "
            "to enable LLM reviews."
        )

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    tool = _build_tool()

    response = client.messages.create(
        model=settings.llm_review_model,
        max_tokens=8000,
        system=_system_blocks(),
        tools=[tool],
        tool_choice={"type": "tool", "name": "submit_review"},
        messages=[{"role": "user", "content": _build_user_message(pdf_text, notebook_text)}],
    )

    if response.stop_reason == "max_tokens":
        logger.warning("llm_review hit max_tokens — output likely truncated")

    # Forced tool_choice guarantees a tool_use block; pull the first one.
    tool_input: dict[str, Any] | None = None
    for block in response.content:
        if block.type == "tool_use" and block.name == "submit_review":
            tool_input = block.input  # type: ignore[assignment]
            break
    if tool_input is None:
        raise LLMReviewError(
            f"Model did not call submit_review; stop_reason={response.stop_reason}"
        )

    dims = tool_input.get("dimensions", {})
    feedback = tool_input.get("feedback_he", "")

    # When the model truncates mid-stream (max_tokens), the SDK sometimes hands us
    # `dimensions` as a partial JSON-encoded string instead of a parsed object —
    # try to recover.
    if isinstance(dims, str):
        # Sonnet 4.6 occasionally jams the entire output (dimensions object +
        # trailing feedback paragraph) into one string. raw_decode parses just
        # the leading JSON object and lets us pull the rest as feedback.
        try:
            dims = json.loads(dims)
            logger.warning("llm_review recovered dimensions from JSON string")
        except json.JSONDecodeError:
            decoder = json.JSONDecoder()
            try:
                obj, end = decoder.raw_decode(dims.lstrip())
                dims = obj
                trailing = dims_raw_trailing(tool_input.get("dimensions", ""), end)
                if trailing and not feedback:
                    feedback = trailing
                    logger.warning(
                        "llm_review recovered both dimensions and feedback from one string"
                    )
                else:
                    logger.warning("llm_review recovered dimensions; trailing was empty")
            except json.JSONDecodeError as exc:
                logger.error(
                    "submit_review payload shape: keys=%s types=%s stop=%s\n"
                    "dims string head: %r\n"
                    "dims string tail: %r",
                    list(tool_input.keys()),
                    {k: type(v).__name__ for k, v in tool_input.items()},
                    response.stop_reason,
                    tool_input.get("dimensions", "")[:300],
                    tool_input.get("dimensions", "")[-300:],
                )
                raise LLMReviewError(
                    f"submit_review payload malformed (dimensions returned as unparseable "
                    f"string, stop_reason={response.stop_reason}, json error: {exc}). "
                    f"Try Re-run."
                )

    if not isinstance(dims, dict) or not isinstance(feedback, str):
        logger.error(
            "submit_review payload shape: keys=%s types=%s",
            list(tool_input.keys()),
            {k: type(v).__name__ for k, v in tool_input.items()},
        )
        raise LLMReviewError(
            f"submit_review payload is malformed: keys={list(tool_input.keys())}"
        )

    # Validate every required dimension is present and well-formed
    missing_dims = [k for k in PROJECT_REPORT_DIMENSIONS if k not in dims]
    if missing_dims:
        raise LLMReviewError(
            f"submit_review payload missing dimensions: {missing_dims}"
        )

    usage = {
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cache_creation_input_tokens": getattr(
            response.usage, "cache_creation_input_tokens", 0
        )
        or 0,
        "cache_read_input_tokens": getattr(
            response.usage, "cache_read_input_tokens", 0
        )
        or 0,
    }
    logger.info(
        "llm_review usage model=%s in=%d out=%d cache_w=%d cache_r=%d",
        settings.llm_review_model,
        usage["input_tokens"],
        usage["output_tokens"],
        usage["cache_creation_input_tokens"],
        usage["cache_read_input_tokens"],
    )

    return LLMReviewResult(
        model=settings.llm_review_model,
        dimensions=dims,
        feedback_he=feedback,
        usage=usage,
    )
