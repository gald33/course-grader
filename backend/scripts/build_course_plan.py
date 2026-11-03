"""Build a course plan and its draft lesson fixtures from a course-content
handoff (see app/lessons/course_plan.py).

    python scripts/build_course_plan.py                 # content/course-42052
    python scripts/build_course_plan.py --check         # exit 1 if the built files are stale
    python scripts/build_course_plan.py --handoff ../content/course-42052

Writes app/lessons/content/course-<code>/plan.json and lesson-NN.json, and
copies the prepared lesson files the plan links to into frontend/public. The
handoff carries no private fields (answer keys, instructor email), so neither
does anything written here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.lessons import ASSETS_ROOT, CONTENT_DIR  # noqa: E402
from app.lessons.course_plan import build_plan, dump  # noqa: E402

DEFAULT_HANDOFF = ROOT.parent / "content" / "course-42052"


def outputs(handoff: Path) -> dict[Path, bytes]:
    """Every file the build writes, with its content."""
    plan, contents, copies = build_plan(handoff)
    out_dir = CONTENT_DIR / f"course-{plan['course_code']}"
    files = {out_dir / "plan.json": dump(plan).encode("utf-8")}
    for slug, content in contents.items():
        files[out_dir / f"{slug}.json"] = dump(content).encode("utf-8")
    for site_path, source in copies.items():
        files[ASSETS_ROOT / site_path.lstrip("/")] = source.read_bytes()
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--handoff", type=Path, default=DEFAULT_HANDOFF)
    parser.add_argument("--check", action="store_true", help="report stale files; write nothing")
    args = parser.parse_args(argv)
    stale = [path for path, data in outputs(args.handoff).items() if not path.is_file() or path.read_bytes() != data]
    if args.check:
        for path in stale:
            print(f"stale: {path}", file=sys.stderr)
        return 1 if stale else 0
    for path, data in outputs(args.handoff).items():
        if path in stale:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            print(f"wrote {path}")
    print(f"{len(stale)} file(s) written" if stale else "up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
