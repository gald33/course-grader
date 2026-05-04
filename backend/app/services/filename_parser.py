from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.utils.text import normalize_id


@dataclass
class ParsedSubmissionFilename:
    ids: list[str]
    workcode: int | None
    originality_score: float | None
    is_originality_pdf: bool


ID_SEGMENT_RE = re.compile(r"ID_(\d+)", re.IGNORECASE)
WORKCODE_RE = re.compile(r"WorkCode_(\d+)", re.IGNORECASE)
ORIGINALITY_RE = re.compile(r"OriginalityReturn[_-]?(\d+(?:\.\d+)?)", re.IGNORECASE)


def parse_filename(filename: str) -> ParsedSubmissionFilename:
    name = Path(filename).name
    ids = [normalize_id(match) for match in ID_SEGMENT_RE.findall(name)]
    ids = [x for x in ids if x]

    workcode_match = WORKCODE_RE.search(name)
    workcode = int(workcode_match.group(1)) if workcode_match else None

    originality_match = ORIGINALITY_RE.search(name)
    originality_score = float(originality_match.group(1)) if originality_match else None

    is_originality_pdf = "originalityreturn" in name.lower() and name.lower().endswith(".pdf")

    return ParsedSubmissionFilename(
        ids=ids,
        workcode=workcode,
        originality_score=originality_score,
        is_originality_pdf=is_originality_pdf,
    )


def group_identifier_from_ids(ids: list[str]) -> str:
    ordered = sorted({normalize_id(x) for x in ids if normalize_id(x)})
    return "+".join(ordered)
