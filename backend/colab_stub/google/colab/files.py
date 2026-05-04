"""Stub for google.colab.files.

In real Colab, `files.upload()` opens a file picker. Out-of-Colab, we look at
files in the current working directory and return them as if the user had
uploaded them. The grading worker copies a submission's data artifacts (.csv,
.xlsx, .zip, etc.) into the notebook's working dir before execution, so
`files.upload()` returns those same files transparently.
"""

from __future__ import annotations

import os
import warnings

DATA_EXTS = {
    ".csv",
    ".tsv",
    ".xlsx",
    ".xls",
    ".json",
    ".txt",
    ".zip",
    ".parquet",
    ".pkl",
    ".npy",
    ".npz",
    ".sqlite",
    ".db",
}


def upload() -> dict[str, bytes]:
    warnings.warn(
        "google.colab.files.upload() is stubbed — returning data files from cwd",
        stacklevel=2,
    )
    out: dict[str, bytes] = {}
    for fn in sorted(os.listdir(".")):
        if not os.path.isfile(fn):
            continue
        if os.path.splitext(fn)[1].lower() in DATA_EXTS:
            with open(fn, "rb") as f:
                out[fn] = f.read()
    return out


def download(filename: str) -> None:
    """No-op — Colab's download triggers a browser save; we just leave files on disk."""
    warnings.warn(
        f"google.colab.files.download({filename!r}) is a no-op outside Colab",
        stacklevel=2,
    )
