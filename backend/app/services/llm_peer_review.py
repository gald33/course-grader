"""LLM grader for a peer-review round.

The LLM acts as one more reviewer: it scores every presentation in the round
with the round's frozen rubric. All teams go into a single request so the
model judges them side by side — like a student who sees the whole round —
which is what the per-reviewer normalisation in peer_scoring assumes.

Inputs per team: name, project title, demo link (not visited), the team's
written materials, and their slides PDF when uploaded. The model does not
watch the live presentation; the prompt says so.

Output is constrained with structured outputs (output_config.format) and the
request opts into server-side refusal fallbacks.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.entities import Artifact, PeerReview, Presentation, ReviewRound, Team
from app.services.peer_review import PeerReviewError, utcnow

logger = logging.getLogger(__name__)

MAX_PDF_BYTES = 10 * 1024 * 1024
FALLBACK_BETA = "server-side-fallback-2026-07-01"

SYSTEM_PROMPT = """You are one of the reviewers in a university course where student teams
build AI-powered products over a semester and present their progress to the class.

You review every team presenting in one review round, using the same rubric the
students use. You do not watch the live presentation or try the product: judge
only from each team's written materials and slides. A demo link is listed for
context but you cannot open it, so do not give credit for things you cannot see
and do not penalise a team just because a claim cannot be verified from the link.

Score each criterion with an integer from the rubric scale. Your scores are
compared across teams in this round, so use the scale deliberately and keep the
same standard for every team. In a progress round, judge the stage that was
reached rather than expecting a finished product.

Write the text answers in Hebrew, addressed to the team (second person plural),
one or two sentences each. Give a short English rationale per criterion for the
instructor."""


@dataclass
class TeamMaterials:
    presentation_id: int
    team_name: str
    project_title: str
    demo_url: str
    materials_text: str
    slides_pdf: bytes | None


def _key(presentation_id: int) -> str:
    return f"p{presentation_id}"


def output_schema(criteria: list[dict], scale_values: list[int], prompts: list[dict], ids: list[int]) -> dict:
    crit_keys = [c["key"] for c in criteria]
    prompt_keys = [p["key"] for p in prompts]
    team_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scores": {
                "type": "object",
                "additionalProperties": False,
                "properties": {k: {"type": "integer", "enum": scale_values} for k in crit_keys},
                "required": crit_keys,
            },
            "rationales": {
                "type": "object",
                "additionalProperties": False,
                "properties": {k: {"type": "string"} for k in crit_keys},
                "required": crit_keys,
            },
            "responses": {
                "type": "object",
                "additionalProperties": False,
                "properties": {k: {"type": "string"} for k in prompt_keys},
                "required": prompt_keys,
            },
        },
        "required": ["scores", "rationales", "responses"],
    }
    keys = [_key(i) for i in ids]
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {k: team_schema for k in keys},
        "required": keys,
    }


def build_request(rnd_kind: str, rubric: dict, teams: list[TeamMaterials]) -> dict[str, Any]:
    """Pure request builder (model/effort are added by the caller)."""
    rubric_lines = ["Rubric criteria (weight in parentheses):"]
    for c in rubric["criteria"]:
        rubric_lines.append(f"- {c['key']} ({c['weight']:g}): {c['label']} — {c.get('description', '')}")
    rubric_lines.append(
        "Scale: " + ", ".join(f"{s['value']} = {s['label']}" for s in rubric["scale"])
    )
    rubric_lines.append(
        "Text answers: " + "; ".join(f"{p['key']}: {p['label']}" for p in rubric["prompts"])
    )
    if rubric.get("instructions"):
        rubric_lines.append(f"Reviewer instructions shown to students: {rubric['instructions']}")
    round_line = (
        "This is a PROGRESS round: evaluate the demonstrated stage, not a finished product."
        if rnd_kind == "progress"
        else "This is the FINAL presentation round: evaluate the product as presented."
    )

    content: list[dict[str, Any]] = [
        {"type": "text", "text": round_line + "\n\n" + "\n".join(rubric_lines)},
    ]
    for t in teams:
        content.append(
            {
                "type": "text",
                "text": (
                    f"=== Team key {_key(t.presentation_id)} ===\n"
                    f"Team: {t.team_name}\n"
                    f"Project: {t.project_title or '(no title)'}\n"
                    f"Demo link (not visited): {t.demo_url or '(none)'}\n"
                    f"Materials:\n{t.materials_text.strip() or '(no written materials)'}"
                ),
            }
        )
        if t.slides_pdf:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": base64.standard_b64encode(t.slides_pdf).decode("ascii"),
                    },
                    "title": f"Slides for {_key(t.presentation_id)}",
                }
            )
    content.append(
        {
            "type": "text",
            "text": "Review every team above. Return one entry per team key.",
        }
    )
    scale_values = [int(s["value"]) for s in rubric["scale"]]
    return {
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": content}],
        "schema": output_schema(rubric["criteria"], scale_values, rubric["prompts"], [t.presentation_id for t in teams]),
    }


def parse_result(text: str, rubric: dict, presentation_ids: list[int]) -> dict[int, dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PeerReviewError("llm_error", f"LLM returned invalid JSON: {exc}", 502)
    allowed = {int(s["value"]) for s in rubric["scale"]}
    out: dict[int, dict] = {}
    for pid in presentation_ids:
        entry = data.get(_key(pid))
        if not isinstance(entry, dict):
            raise PeerReviewError("llm_error", f"LLM output is missing team {_key(pid)}", 502)
        scores = entry.get("scores") or {}
        clean: dict[str, int] = {}
        for c in rubric["criteria"]:
            v = scores.get(c["key"])
            if not isinstance(v, int) or v not in allowed:
                raise PeerReviewError("llm_error", f"LLM score for {c['key']} of {_key(pid)} is invalid", 502)
            clean[c["key"]] = v
        responses = entry.get("responses") or {}
        out[pid] = {
            "scores": clean,
            "responses": {p["key"]: str(responses.get(p["key"], "")).strip() for p in rubric["prompts"]},
            "rationales": {k: str(v) for k, v in (entry.get("rationales") or {}).items()},
        }
    return out


def _load_materials(db: Session, presentations: list[Presentation]) -> list[TeamMaterials]:
    out = []
    for p in presentations:
        team = db.get(Team, p.team_id)
        pdf: bytes | None = None
        if p.slides_artifact_id:
            artifact = db.get(Artifact, p.slides_artifact_id)
            path = Path(artifact.path) if artifact else None
            if path and path.exists() and path.stat().st_size <= MAX_PDF_BYTES:
                pdf = path.read_bytes()
        out.append(
            TeamMaterials(
                presentation_id=p.id,
                team_name=team.name if team else f"Team {p.team_id}",
                project_title=team.project_title if team else "",
                demo_url=p.demo_url,
                materials_text=p.materials_text,
                slides_pdf=pdf,
            )
        )
    return out


def _call_model(request: dict[str, Any], client: Any | None = None) -> tuple[str, str]:
    settings = get_settings()
    if client is None:
        if not settings.anthropic_api_key:
            raise PeerReviewError(
                "llm_unavailable",
                "ANTHROPIC_API_KEY is not set — configure it in the backend environment to run the LLM grader.",
                503,
            )
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Streaming keeps a long, multi-team request clear of HTTP timeouts.
    with client.beta.messages.stream(
        model=settings.llm_peer_review_model,
        max_tokens=64000,
        system=request["system"],
        messages=request["messages"],
        betas=[FALLBACK_BETA],
        extra_body={
            "fallbacks": "default",
            "output_config": {
                "effort": settings.llm_peer_review_effort,
                "format": {"type": "json_schema", "schema": request["schema"]},
            },
        },
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise PeerReviewError("llm_error", "The model declined to review this round", 502)
    if response.stop_reason == "max_tokens":
        raise PeerReviewError("llm_error", "LLM output was truncated (max_tokens)", 502)
    text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
    model = getattr(response, "model", None) or settings.llm_peer_review_model
    usage = getattr(response, "usage", None)
    if usage is not None:
        logger.info(
            "llm_peer_review model=%s in=%s out=%s",
            model,
            getattr(usage, "input_tokens", "?"),
            getattr(usage, "output_tokens", "?"),
        )
    return text, model


def run_llm_round_review(db: Session, rnd: ReviewRound, client: Any | None = None) -> list[PeerReview]:
    if not rnd.llm_enabled:
        raise PeerReviewError("llm_disabled", "The LLM grader is turned off for this round", 409)
    if rnd.rubric_version is None:
        raise PeerReviewError("invalid_state", "Open reviewing first so the rubric is frozen", 409)
    if rnd.released_at is not None:
        raise PeerReviewError("invalid_state", "Results are already released for this round", 409)
    presentations = list(
        db.scalars(select(Presentation).where(Presentation.round_id == rnd.id).order_by(Presentation.id))
    )
    if not presentations:
        raise PeerReviewError("invalid_state", "This round has no presentations", 409)

    rubric = {
        "criteria": json.loads(rnd.rubric_version.criteria_json),
        "scale": json.loads(rnd.rubric_version.scale_json),
        "prompts": json.loads(rnd.rubric_version.prompts_json),
        "instructions": rnd.rubric_version.instructions,
    }
    request = build_request(rnd.kind, rubric, _load_materials(db, presentations))
    text, model = _call_model(request, client)
    results = parse_result(text, rubric, [p.id for p in presentations])

    saved = []
    for p in presentations:
        r = results[p.id]
        review = db.scalar(
            select(PeerReview).where(PeerReview.presentation_id == p.id, PeerReview.reviewer_kind == "llm")
        )
        if review is None:
            review = PeerReview(
                round_id=rnd.id,
                presentation_id=p.id,
                rubric_version_id=rnd.rubric_version.id,
                reviewer_kind="llm",
            )
            db.add(review)
        review.scores_json = json.dumps(r["scores"])
        review.responses_json = json.dumps(r["responses"], ensure_ascii=False)
        review.llm_rationale_json = json.dumps(r["rationales"], ensure_ascii=False)
        review.llm_model = model
        review.updated_at = utcnow()
        saved.append(review)
    db.commit()
    return saved
