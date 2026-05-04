from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


def data_root() -> Path:
    root = Path(settings.data_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_structure() -> None:
    for rel in [
        "artifacts/uploads",
        "artifacts/snapshots",
        "artifacts/runs",
        "artifacts/reports",
        "exports",
        "secrets",
    ]:
        (data_root() / rel).mkdir(parents=True, exist_ok=True)


def artifact_path(*parts: str) -> Path:
    path = data_root().joinpath("artifacts", *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def export_path(*parts: str) -> Path:
    path = data_root().joinpath("exports", *parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
