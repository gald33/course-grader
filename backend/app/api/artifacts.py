from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.models.entities import Artifact

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


_PDF_EXTS = {".pdf"}


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

    path = Path(artifact.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file missing")

    if artifact.mime_type.startswith("text/") or artifact.filename.endswith(('.html', '.log', '.txt', '.json')):
        return PlainTextResponse(path.read_text(encoding="utf-8", errors="ignore"), media_type=artifact.mime_type)

    return FileResponse(str(path), media_type=artifact.mime_type, filename=artifact.filename)
