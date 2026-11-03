"""Build lesson 4's starter project zip (the bakery order summary students
open in Google Antigravity) from its source folder.

    python scripts/build_lesson_4_starter.py            # write the zip
    python scripts/build_lesson_4_starter.py --check    # exit 1 if it is stale

Source: content/course-42052/materials/lesson-04/bakery-orders-starter/.
Output: frontend/public/lessons/lesson-04/v1/bakery-orders-starter.zip, with
fixed timestamps, order and no compression so the same files always give the same bytes (the
lesson fixture records its sha256).
"""

from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SOURCE = REPO / "content" / "course-42052" / "materials" / "lesson-04" / "bakery-orders-starter"
OUTPUT = REPO / "frontend" / "public" / "lessons" / "lesson-04" / "v1" / "bakery-orders-starter.zip"
FOLDER = "bakery-orders-starter"


def build(source: Path = SOURCE) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for path in sorted(p for p in source.rglob("*") if p.is_file()):
            info = zipfile.ZipInfo(f"{FOLDER}/{path.relative_to(source).as_posix()}", date_time=(2026, 11, 3, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED  # no compression: the bytes do not depend on the zlib version
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="report a stale zip; write nothing")
    args = parser.parse_args(argv)
    data = build()
    stale = not OUTPUT.is_file() or OUTPUT.read_bytes() != data
    if args.check:
        if stale:
            print(f"stale: {OUTPUT}", file=sys.stderr)
        return 1 if stale else 0
    if stale:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_bytes(data)
        print(f"wrote {OUTPUT}")
    else:
        print("up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
