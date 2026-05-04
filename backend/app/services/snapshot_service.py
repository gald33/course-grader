from __future__ import annotations

import hashlib
import io
import json
import re
from dataclasses import dataclass
from datetime import datetime

import httpx
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.models.entities import Artifact, ColabSnapshot
from app.services.oauth_google import load_credentials
from app.services.paths import artifact_path


@dataclass
class SnapshotFetchResult:
    status: str
    content_hash: str | None = None
    artifact: Artifact | None = None
    error_message: str = ""
    file_id: str | None = None


def extract_google_file_id(url: str) -> str | None:
    patterns = [
        r"/drive/([a-zA-Z0-9_-]{20,})",
        r"/d/([a-zA-Z0-9_-]{20,})",
        r"id=([a-zA-Z0-9_-]{20,})",
        r"fileId=([a-zA-Z0-9_-]{20,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def _try_public_fetch(file_id: str) -> bytes | None:
    urls = [
        f"https://colab.research.google.com/drive/{file_id}?format=ipynb",
        f"https://colab.research.google.com/drive/{file_id}?export=download",
        f"https://drive.google.com/uc?id={file_id}&export=download",
    ]
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        for url in urls:
            resp = client.get(url)
            if resp.status_code >= 400:
                continue
            text = resp.text.strip()
            if text.startswith("{") and '"cells"' in text and '"nbformat"' in text:
                return resp.content
    return None


def _private_drive_fetch(file_id: str) -> bytes | None:
    creds = load_credentials()
    if creds is None:
        return None
    service = build("drive", "v3", credentials=creds, cache_discovery=False)
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    content = buf.getvalue()
    if content.strip().startswith(b"{") and b'"cells"' in content:
        return content
    return None


def persist_snapshot_file(snapshot: ColabSnapshot, content: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(content).hexdigest()
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    file_name = f"snapshot_{snapshot.submission_id}_{timestamp}_{digest[:10]}.ipynb"
    target = artifact_path("snapshots", str(snapshot.submission_id), file_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return str(target), digest


def fetch_snapshot(snapshot: ColabSnapshot) -> SnapshotFetchResult:
    file_id = extract_google_file_id(snapshot.url)
    if not file_id:
        return SnapshotFetchResult(status="FAILED", error_message="Unable to extract Google file ID from URL")

    public_content = _try_public_fetch(file_id)
    if public_content:
        return SnapshotFetchResult(status="PUBLIC_FETCHED", file_id=file_id)

    private_content = _private_drive_fetch(file_id)
    if private_content:
        return SnapshotFetchResult(status="PRIVATE_FETCHED", file_id=file_id)

    if load_credentials() is None:
        return SnapshotFetchResult(status="OAUTH_REQUIRED", file_id=file_id, error_message="Notebook is private, OAuth is required")

    return SnapshotFetchResult(status="FAILED", file_id=file_id, error_message="Could not download notebook")


def fetch_snapshot_content(snapshot: ColabSnapshot) -> tuple[str, bytes] | None:
    file_id = extract_google_file_id(snapshot.url)
    if not file_id:
        return None

    public_content = _try_public_fetch(file_id)
    if public_content:
        return "PUBLIC_FETCHED", public_content

    private_content = _private_drive_fetch(file_id)
    if private_content:
        return "PRIVATE_FETCHED", private_content

    return None


def build_snapshot_artifact(submission_id: int, file_path: str, file_name: str, size: int) -> Artifact:
    return Artifact(
        submission_id=submission_id,
        kind="snapshot_ipynb",
        filename=file_name,
        path=file_path,
        mime_type="application/x-ipynb+json",
        size_bytes=size,
        metadata_json=json.dumps({}),
    )
