"""Stub for google.colab.drive.

Real Colab mounts the user's Google Drive at the given path. We can't do that
outside Colab, but most student code only uses `drive.mount("/content/drive")`
and then reads files at paths like `/content/drive/MyDrive/data.csv` — they
typically also have the same files in `/content/` directly. We:

  1. Make the mount call a no-op (returns silently — no `from google.colab
     import drive; drive.mount(...)` failures).
  2. Create the requested mount path so anything that checks `os.path.exists`
     for the mount root is satisfied.
  3. Symlink the data files staged in /content/ under
     `<mount_path>/MyDrive/` so paths like
     `/content/drive/MyDrive/data.csv` resolve to the real file.
"""

from __future__ import annotations

import os
from pathlib import Path


def _mirror_content(into: Path) -> None:
    content = Path("/content")
    if not content.exists():
        return
    into.mkdir(parents=True, exist_ok=True)
    for src in content.iterdir():
        # don't recurse into the mount itself
        try:
            if src.resolve() == into.resolve():
                continue
        except Exception:
            pass
        dst = into / src.name
        if dst.exists() or dst.is_symlink():
            try:
                dst.unlink()
            except Exception:
                pass
        try:
            dst.symlink_to(src)
        except (OSError, NotImplementedError):
            pass


def mount(mountpoint: str = "/content/drive", *_, **__) -> None:
    mp = Path(mountpoint)
    try:
        mp.mkdir(parents=True, exist_ok=True)
        # Mirror /content into <mountpoint>/MyDrive so absolute Drive-style
        # paths like /content/drive/MyDrive/data.csv resolve.
        _mirror_content(mp / "MyDrive")
    except Exception:
        # A failed stub mount shouldn't blow up the kernel.
        pass


def flush_and_unmount(*_, **__) -> None:
    pass
