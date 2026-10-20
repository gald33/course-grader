from __future__ import annotations

import logging
import json
import re
import shutil
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.entities import Artifact, Assignment, ColabSnapshot, NotebookRun, RubricDimensionScore, Submission
from app.services.auto_install import auto_install_missing
from app.services.code_metrics import all_deterministic_scores
from app.services.consistency import compare_report_and_notebook, flags_to_json, notebook_text_from_ipynb
from app.services.english_comments import english_comments_score_from_notebook
from app.services.exporter import export_student_reports_hebrew
from app.services.llm_code_review import LLMCodeReviewError, review_code_dimensions
from app.services.notebook_runner import execute_notebook, serialize_notebook
from app.services.pdf_service import extract_originality_score, extract_text_from_pdf
from app.services import storage
from app.services.scoring import apply_curve, get_active_curve, parse_curve_mapping
from app.services.snapshot_service import build_snapshot_artifact, fetch_snapshot_content, persist_snapshot_file
from app.tasks.queue import job

logger = logging.getLogger(__name__)
settings = get_settings()


_DATA_EXTS = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".json",
    ".txt",
    ".zip",
    ".parquet",
    ".pkl",
    ".npy",
    ".npz",
    ".sqlite",
    ".db",
}

_ID_PREFIX_RE = re.compile(r"^(ID_\d+(?:\+ID_\d+)*)_+(.+)$")


def _strip_id_prefix(filename: str) -> str:
    """Turn "ID_213+ID_324_data.csv" into "data.csv".

    Files ingested through the submissions ZIP carry ID_ prefixes that encode
    group membership; student code uses the bare filename.
    """
    match = _ID_PREFIX_RE.match(filename)
    return match.group(2) if match else filename


def _stage_data_files(db, submission_id: int, target_dir: Path) -> None:
    """Stage a submission's data artifacts so the notebook can read them.

    Files are placed both:
      - In the notebook's working directory (relative paths like "data.csv")
      - At /content/<name> (the Colab convention; many student notebooks hard-code
        '/content/data.csv' or use `drive.mount('/content/drive')` then read paths
        under /content/...)

    Worker concurrency is 1, so /content/ is wiped and re-populated each run to
    avoid leaking files between submissions.
    """
    artifacts = db.scalars(
        select(Artifact).where(
            Artifact.submission_id == submission_id,
            Artifact.kind.in_(("data_file", "submission_file")),
        )
    ).all()
    target_dir.mkdir(parents=True, exist_ok=True)

    content_dir = Path("/content")
    # Wipe stale per-run staging — only files that look like data, never
    # arbitrary system paths. The dir is created fresh by the worker image.
    if content_dir.exists():
        for child in content_dir.iterdir():
            try:
                if child.is_file() or child.is_symlink():
                    child.unlink()
            except Exception:  # noqa: BLE001
                logger.exception("Could not clear stale /content/%s", child.name)
    else:
        try:
            content_dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            logger.exception("Could not create /content")

    for art in artifacts:
        try:
            if Path(art.path).suffix.lower() not in _DATA_EXTS or not storage.exists(art.path):
                continue
            src = storage.local_path(art.path)
            clean_name = _strip_id_prefix(art.filename)

            dst = target_dir / clean_name
            if not dst.exists():
                shutil.copy2(src, dst)

            # Also expose at the Colab-style absolute path
            try:
                content_dst = content_dir / clean_name
                if content_dst.exists() or content_dst.is_symlink():
                    content_dst.unlink()
                content_dst.symlink_to(dst)
            except (OSError, NotImplementedError):
                # Filesystem doesn't support symlinks (rare on Linux) — fall back to copy
                try:
                    shutil.copy2(dst, content_dir / clean_name)
                except Exception:  # noqa: BLE001
                    logger.exception("Could not mirror %s to /content/", clean_name)

            logger.info("Staged data file %s -> %s (and /content/%s)", src.name, dst, clean_name)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to stage data file %s", art.filename)


@job("app.tasks.jobs.parse_originality_pdf")
def parse_originality_pdf(artifact_id: int) -> dict:
    with SessionLocal() as db:
        artifact = db.get(Artifact, artifact_id)
        if artifact is None:
            return {"status": "missing_artifact"}

        try:
            text = extract_text_from_pdf(storage.local_path(artifact.path))
            score = extract_originality_score(text)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to parse originality PDF")
            return {"status": "error", "error": str(exc)}

        submission = db.get(Submission, artifact.submission_id) if artifact.submission_id else None
        if submission is None:
            return {"status": "orphan_artifact"}

        submission.originality_score_pdf = score
        if submission.originality_score_filename is not None and score is not None:
            submission.originality_mismatch = abs(submission.originality_score_filename - score) > 0.01
        db.commit()

        return {"status": "ok", "score": score}


@job("app.tasks.jobs.fetch_colab_snapshot")
def fetch_colab_snapshot(snapshot_id: int) -> dict:
    with SessionLocal() as db:
        snapshot = db.get(ColabSnapshot, snapshot_id)
        if snapshot is None:
            return {"status": "missing_snapshot"}

        snapshot.status = "FETCHING"
        db.commit()

        fetched = fetch_snapshot_content(snapshot)
        if fetched is None:
            snapshot.status = "OAUTH_REQUIRED"
            snapshot.error_message = "Unable to fetch notebook publicly. OAuth may be required."
            db.commit()
            return {"status": snapshot.status}

        status, content = fetched
        file_path, digest = persist_snapshot_file(snapshot, content)
        artifact = build_snapshot_artifact(
            submission_id=snapshot.submission_id,
            file_path=file_path,
            file_name=Path(file_path).name,
            size=len(content),
        )
        db.add(artifact)
        db.flush()

        snapshot.status = status
        snapshot.content_hash = digest
        snapshot.fetched_at = datetime.utcnow()
        snapshot.artifact_id = artifact.id
        snapshot.error_message = ""
        db.commit()
        return {"status": status, "snapshot_id": snapshot.id, "artifact_id": artifact.id}


def _create_artifact(db, submission_id: int, kind: str, file_name: str, content: bytes, mime_type: str) -> Artifact:
    location = storage.save(f"runs/{submission_id}/{file_name}", content, mime_type)

    artifact = Artifact(
        submission_id=submission_id,
        kind=kind,
        filename=file_name,
        path=location,
        mime_type=mime_type,
        size_bytes=len(content),
        metadata_json=json.dumps({}),
    )
    db.add(artifact)
    db.flush()
    return artifact


@job("app.tasks.jobs.run_notebook")
def run_notebook(run_id: int) -> dict:
    with SessionLocal() as db:
        run = db.get(NotebookRun, run_id)
        if run is None:
            return {"status": "missing_run"}

        snapshot = db.get(ColabSnapshot, run.snapshot_id)
        if snapshot is None or snapshot.artifact_id is None:
            run.status = "FAILED"
            run.error_summary = "Snapshot artifact missing"
            db.commit()
            return {"status": "failed", "reason": run.error_summary}

        snapshot_artifact = db.get(Artifact, snapshot.artifact_id)
        if snapshot_artifact is None:
            run.status = "FAILED"
            run.error_summary = "Snapshot artifact row not found"
            db.commit()
            return {"status": "failed", "reason": run.error_summary}

        run.status = "RUNNING"
        run.started_at = datetime.utcnow()
        db.commit()

        # A local copy when the snapshot lives in Supabase Storage; its folder
        # is also the notebook's working directory for staged data files.
        snapshot_path = storage.local_path(snapshot_artifact.path)

        # Stage data artifacts (csv/xlsx/json/zip/etc.) alongside the notebook
        # so cells like `pd.read_csv("data.csv")` resolve. Filenames stored on
        # disk look like "ID_213+ID_324_data.csv" — strip the ID_ prefix back to
        # the original "data.csv" the students wrote in their code.
        _stage_data_files(db, run.submission_id, snapshot_path.parent)

        # Resolve missing imports in the worker before nbclient spawns a kernel.
        # Anything that was already importable (numpy, tensorflow, ...) is a
        # no-op; anything new is pip-installed into the worker's site-packages.
        install_report = auto_install_missing(snapshot_path)
        logger.info("auto-install pre-pass: %s discovered, %s installed", len(install_report.discovered), len(install_report.attempts))

        try:
            result = execute_notebook(
                snapshot_path,
                total_timeout_seconds=settings.notebook_total_timeout_seconds,
                penalty_power=settings.notebook_penalty_power,
            )
        except Exception as exc:  # noqa: BLE001
            run.status = "FAILED"
            run.error_summary = str(exc)
            run.ended_at = datetime.utcnow()
            db.commit()
            return {"status": "failed", "reason": str(exc)}

        # Prepend the auto-install report to the run log so it's visible
        # alongside the cell output when the grader opens the .log artifact.
        result.logs = install_report.log + result.logs

        executed_bytes = serialize_notebook(result.executed_notebook)
        html_bytes = result.html.encode("utf-8")
        logs_bytes = result.logs.encode("utf-8")

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        executed_artifact = _create_artifact(
            db,
            run.submission_id,
            "executed_ipynb",
            f"executed_{run.id}_{ts}.ipynb",
            executed_bytes,
            "application/x-ipynb+json",
        )
        html_artifact = _create_artifact(
            db,
            run.submission_id,
            "executed_html",
            f"executed_{run.id}_{ts}.html",
            html_bytes,
            "text/html",
        )
        log_artifact = _create_artifact(
            db,
            run.submission_id,
            "run_logs",
            f"run_{run.id}_{ts}.log",
            logs_bytes,
            "text/plain",
        )
        executed_path = str(storage.local_path(executed_artifact.path))

        run.ok_cells = result.ok_cells
        run.failed_cells = result.failed_cells
        run.run_ratio = result.run_ratio
        run.penalty_multiplier = result.penalty_multiplier
        run.error_count = result.failed_cells
        run.error_summary = result.error_summary
        run.executed_notebook_artifact_id = executed_artifact.id
        run.executed_html_artifact_id = html_artifact.id
        run.log_artifact_id = log_artifact.id
        run.ended_at = datetime.utcnow()
        run.status = "TIMEOUT" if result.timed_out else "SUCCESS"

        submission = db.get(Submission, run.submission_id)
        if submission is not None:
            assignment = db.get(Assignment, submission.assignment_id)
            if assignment is not None and assignment.assignment_type in {"HW2", "PROJECT"}:
                component = "hw2_code" if assignment.assignment_type == "HW2" else "project_code"
                curve = parse_curve_mapping(get_active_curve(db, submission.course_id))

                # explanations: {dim_key: {"score": int, "rationale": str, "source": "auto" | "claude"}}
                # Persisted as JSON in submission.code_review_json so the rubric UI can
                # show a per-dim explanation under each row, mirroring the project_report
                # llm_review pattern.
                explanations: dict[str, dict[str, object]] = {}
                raw_scores: dict[str, float] = {}

                ec_score, ec_rationale = english_comments_score_from_notebook(executed_path)
                raw_scores["english_comments_compliance"] = ec_score
                explanations["english_comments_compliance"] = {
                    "score": ec_score,
                    "rationale": ec_rationale,
                    "source": "auto",
                }

                for dim_key, scored in all_deterministic_scores(
                    notebook_path=executed_path,
                    staged_data_dir=snapshot_path.parent,
                ).items():
                    raw_scores[dim_key] = scored.score
                    explanations[dim_key] = {
                        "score": scored.score,
                        "rationale": scored.rationale,
                        "source": "auto",
                    }

                # LLM scores the two judgment dims (processing_description,
                # models_quality). Best-effort — if the API call fails the run
                # still succeeds; existing rows for those dims are left alone.
                try:
                    nb_text = notebook_text_from_ipynb(executed_path)
                    llm_result = review_code_dimensions(nb_text)
                    for dim_key, payload in llm_result.scores.items():
                        if isinstance(payload, dict) and "score" in payload:
                            score = float(payload["score"])
                            raw_scores[dim_key] = score
                            explanations[dim_key] = {
                                "score": score,
                                "rationale": str(payload.get("rationale", "")),
                                "source": "claude",
                            }
                except LLMCodeReviewError as exc:
                    logger.warning("LLM code review skipped: %s", exc)
                except Exception:  # noqa: BLE001
                    logger.exception("LLM code review failed unexpectedly")

                # Upsert every collected score, applying the active curve.
                for dim_key, raw in raw_scores.items():
                    cfg = curve.get(dim_key, {"points": [0, 1, 2, 3, 4, 5]})
                    adjusted = apply_curve(raw, cfg["points"])
                    row = db.scalar(
                        select(RubricDimensionScore).where(
                            RubricDimensionScore.submission_id == submission.id,
                            RubricDimensionScore.component == component,
                            RubricDimensionScore.dimension_key == dim_key,
                        )
                    )
                    if row is None:
                        db.add(
                            RubricDimensionScore(
                                submission_id=submission.id,
                                component=component,
                                dimension_key=dim_key,
                                raw_score=raw,
                                adjusted_score=adjusted,
                            )
                        )
                    else:
                        row.raw_score = raw
                        row.adjusted_score = adjusted

                # Persist all explanations for the rubric UI.
                submission.code_review_json = json.dumps(
                    {"component": component, "dimensions": explanations},
                    ensure_ascii=False,
                )

            report_artifact = db.scalar(
                select(Artifact)
                .where(Artifact.submission_id == submission.id, Artifact.kind == "project_report_pdf")
                .order_by(Artifact.id.desc())
            )
            if report_artifact:
                try:
                    report_text = extract_text_from_pdf(storage.local_path(report_artifact.path))
                    nb_text = notebook_text_from_ipynb(executed_path)
                    consistency = compare_report_and_notebook(report_text, nb_text)
                    submission.consistency_summary = consistency.summary
                    submission.consistency_flags_json = flags_to_json(consistency.flags)
                except Exception:  # noqa: BLE001
                    logger.exception("Consistency analysis failed")

        db.commit()
        return {
            "status": run.status,
            "run_id": run.id,
            "ok_cells": run.ok_cells,
            "failed_cells": run.failed_cells,
            "run_ratio": run.run_ratio,
            "penalty_multiplier": run.penalty_multiplier,
        }


@job("app.tasks.jobs.fetch_and_run_latest")
def fetch_and_run_latest(submission_id: int, snapshot_id: int) -> dict:
    fetch_result = fetch_colab_snapshot(snapshot_id)
    if fetch_result.get("status") not in {"PUBLIC_FETCHED", "PRIVATE_FETCHED"}:
        return {"status": "snapshot_fetch_failed", "snapshot": fetch_result}

    with SessionLocal() as db:
        run = NotebookRun(
            submission_id=submission_id,
            snapshot_id=snapshot_id,
            mode="latest",
            status="QUEUED",
        )
        db.add(run)
        db.commit()
        db.refresh(run)

    run_result = run_notebook(run.id)
    return {"status": "ok", "fetch": fetch_result, "run": run_result}


@job("app.tasks.jobs.export_student_reports")
def export_student_reports(course_id: int) -> dict:
    with SessionLocal() as db:
        result = export_student_reports_hebrew(db, course_id)
        return {
            "status": "ok",
            "csv_path": result.csv_path,
            "zip_location": result.zip_location,
            "report_count": result.report_count,
        }
