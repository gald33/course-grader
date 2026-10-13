from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Artifact
from app.services import storage

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


_PDF_EXTS = {".pdf"}
# Text artifacts in Supabase Storage are proxied up to this size (below
# Vercel's ~4.5 MB response limit); larger ones redirect to a signed URL.
RAW_PROXY_LIMIT = 4 * 1024 * 1024


def _better_mime(filename: str, stored: str | None) -> str:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext == ".docx":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if ext == ".pptx":
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    if ext == ".xlsx":
        return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    if ext == ".ipynb":
        return "application/x-ipynb+json"
    if stored and stored != "application/octet-stream":
        return stored
    return mimetypes.guess_type(filename)[0] or "application/octet-stream"


@router.get("/{artifact_id}")
def download_artifact(
    artifact_id: int,
    inline: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> Response:
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")
    if storage.is_remote(artifact.path):
        # Storage serves the bytes via a short-lived signed URL, so large files
        # never pass through the API (hosted functions cap response size).
        download_name = None if inline else artifact.filename
        return RedirectResponse(storage.signed_url(artifact.path, download_name=download_name), status_code=307)
    if not Path(artifact.path).exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    mime = _better_mime(artifact.filename, artifact.mime_type)
    # FastAPI's FileResponse(filename=...) forces Content-Disposition: attachment,
    # which prevents PDFs from embedding in <object>/<iframe>. Set the header
    # manually so callers can request inline rendering when desired.
    disposition = "inline" if inline else "attachment"
    quoted = quote(artifact.filename, safe="")
    headers = {
        "Content-Disposition": f"{disposition}; filename*=utf-8''{quoted}",
    }
    return FileResponse(artifact.path, media_type=mime, headers=headers)


@router.get("/{artifact_id}/raw")
def raw_artifact(artifact_id: int, db: Session = Depends(get_db)):
    artifact = db.get(Artifact, artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Artifact not found")

    is_text = artifact.mime_type.startswith("text/") or artifact.filename.endswith(('.html', '.log', '.txt', '.json'))
    if storage.is_remote(artifact.path):
        if is_text and artifact.size_bytes <= RAW_PROXY_LIMIT:
            text = storage.read_bytes(artifact.path).decode("utf-8", errors="ignore")
            return PlainTextResponse(text, media_type=artifact.mime_type)
        return RedirectResponse(storage.signed_url(artifact.path, download_name=artifact.filename), status_code=307)

    path = Path(artifact.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    if is_text:
        return PlainTextResponse(path.read_text(encoding="utf-8", errors="ignore"), media_type=artifact.mime_type)

    return FileResponse(str(path), media_type=artifact.mime_type, filename=artifact.filename)
