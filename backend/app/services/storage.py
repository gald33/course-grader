"""Artifact file storage: local disk (default) or Supabase Storage.

`Artifact.path` holds a location: a local filesystem path, or
`supabase://<bucket>/<key>` for an object in Supabase Storage. Writes go to
the configured backend (STORAGE_BACKEND); reads follow the location, so rows
written before switching backends keep working.

The Supabase bucket is private and accessed server-side with the secret key.
Browsers get short-lived signed URLs (see `signed_url`).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from urllib.parse import quote

import httpx

from app.core.config import get_settings
from app.services.paths import artifact_path, data_root

REMOTE_PREFIX = "supabase://"

# Tests swap in an httpx.MockTransport.
_transport: httpx.BaseTransport | None = None
_bucket_ready: set[str] = set()


class StorageError(RuntimeError):
    pass


def is_remote(location: str) -> bool:
    return location.startswith(REMOTE_PREFIX)


def _split(location: str) -> tuple[str, str]:
    bucket, _, key = location[len(REMOTE_PREFIX) :].partition("/")
    if not bucket or not key:
        raise StorageError(f"Malformed storage location: {location!r}")
    return bucket, key


def _client() -> httpx.Client:
    settings = get_settings()
    if not settings.supabase_project_url or not settings.supabase_secret_key:
        raise StorageError("SUPABASE_PROJECT_URL and SUPABASE_SECRET_KEY are required for Supabase storage")
    key = settings.supabase_secret_key.strip()
    return httpx.Client(
        base_url=settings.supabase_project_url.strip().rstrip("/") + "/storage/v1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=120,
        transport=_transport,
    )


def _object_path(bucket: str, key: str) -> str:
    return f"{quote(bucket)}/{quote(key)}"


def _check(response: httpx.Response, action: str) -> None:
    if response.is_error:
        raise StorageError(f"Supabase storage {action} failed ({response.status_code}): {response.text[:300]}")


def ensure_bucket(client: httpx.Client, bucket: str) -> None:
    """Create the private bucket on first use (idempotent)."""
    if bucket in _bucket_ready:
        return
    if client.get(f"/bucket/{quote(bucket)}").status_code != 200:
        res = client.post("/bucket", json={"id": bucket, "name": bucket, "public": False})
        if res.is_error and "already exists" not in res.text.lower():
            _check(res, "bucket creation")
    _bucket_ready.add(bucket)


def save(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Store `data` under `key` (e.g. "runs/12/executed_3.ipynb"); returns the
    location to keep in Artifact.path. Overwrites an existing object."""
    settings = get_settings()
    key = key.strip("/")
    if settings.storage_backend == "supabase":
        bucket = settings.supabase_storage_bucket
        with _client() as client:
            ensure_bucket(client, bucket)
            res = client.post(
                f"/object/{_object_path(bucket, key)}",
                content=data,
                headers={"content-type": content_type, "x-upsert": "true"},
            )
            _check(res, "upload")
        return f"{REMOTE_PREFIX}{bucket}/{key}"
    target = artifact_path(*key.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return str(target)


def read_bytes(location: str) -> bytes:
    if not is_remote(location):
        return Path(location).read_bytes()
    bucket, key = _split(location)
    with _client() as client:
        res = client.get(f"/object/authenticated/{_object_path(bucket, key)}")
        _check(res, "download")
        return res.content


def exists(location: str) -> bool:
    if not is_remote(location):
        return Path(location).exists()
    bucket, key = _split(location)
    with _client() as client:
        return client.get(f"/object/info/authenticated/{_object_path(bucket, key)}").status_code == 200


def local_path(location: str) -> Path:
    """A filesystem path with the file's current content, for code that needs
    a real file (notebook execution, PDF parsing). Remote objects are
    downloaded into DATA_DIR/cache, mirroring their key."""
    if not is_remote(location):
        return Path(location)
    bucket, key = _split(location)
    target = data_root().joinpath("cache", bucket, *key.split("/"))
    target.parent.mkdir(parents=True, exist_ok=True)
    data = read_bytes(location)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".download-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)
    return target


def signed_url(location: str, download_name: str | None = None, expires_in: int = 600) -> str:
    """Short-lived URL a browser can open directly. With `download_name` the
    file is served as an attachment under that name."""
    bucket, key = _split(location)
    with _client() as client:
        res = client.post(f"/object/sign/{_object_path(bucket, key)}", json={"expiresIn": expires_in})
        _check(res, "signing")
        signed = res.json().get("signedURL") or res.json().get("signedUrl")
    if not signed:
        raise StorageError("Supabase storage returned no signed URL")
    url = str(client.base_url).rstrip("/") + "/" + signed.lstrip("/")
    if download_name:
        url += ("&" if "?" in url else "?") + "download=" + quote(download_name)
    return url
