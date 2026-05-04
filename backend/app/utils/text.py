from __future__ import annotations

import re
import unicodedata


def normalize_id(value: str) -> str:
    return re.sub(r"\D", "", str(value or ""))


def sanitize_filename(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("_")
    return ascii_name or "file"


def coerce_score_to_0_5(value: float | int | str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric > 5:
        numeric = numeric / 20.0
    return max(0.0, min(5.0, numeric))
