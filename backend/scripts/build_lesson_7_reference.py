"""Build lesson 7's downloads from their source folder: the bakery AI
reference implementation (zip) and its .env.example on its own.

    python scripts/build_lesson_7_reference.py            # write the files
    python scripts/build_lesson_7_reference.py --check    # exit 1 if one is stale

Source: content/course-42052/materials/lesson-07/bakery-ai-reference/.
Output: frontend/public/lessons/lesson-07/v1/bakery-ai-reference.zip (fixed
timestamps and order, no compression, so the same files always give the same
bytes; the lesson fixture records its sha256) and
frontend/public/lessons/lesson-07/v1/env.example (byte-equal to the folder's
.env.example). A local .env or node_modules is never packed.
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SOURCE = REPO / "content" / "course-42052" / "materials" / "lesson-07" / "bakery-ai-reference"
OUT_DIR = REPO / "frontend" / "public" / "lessons" / "lesson-07" / "v1"
ZIP = OUT_DIR / "bakery-ai-reference.zip"
ENV_EXAMPLE = OUT_DIR / "env.example"
FOLDER = "bakery-ai-reference"
NEVER = {".env", "node_modules"}


def files(source: Path = SOURCE) -> list[Path]:
    return sorted(
        p for p in source.rglob("*") if p.is_file() and not NEVER & set(p.relative_to(source).parts)
    )


def build(source: Path = SOURCE) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in files(source):
            info = zipfile.ZipInfo(f"{FOLDER}/{path.relative_to(source).as_posix()}", date_time=(2026, 11, 4, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED  # no compression: the bytes do not depend on the zlib version
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def outputs() -> dict[Path, bytes]:
    return {ZIP: build(), ENV_EXAMPLE: (SOURCE / ".env.example").read_bytes()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report a stale output; write nothing")
    args = parser.parse_args(argv)
    stale = [path for path, data in outputs().items() if not path.is_file() or path.read_bytes() != data]
    if args.check:
        for path in stale:
            print(f"stale: {path}", file=sys.stderr)
        return 1 if stale else 0
    for path, data in outputs().items():
        if path in stale:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(f"wrote {path}")
    if not stale:
        print("up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
