"""Pre-execution import resolver for student notebooks.

Walks a notebook's code cells, finds top-level imports that are not currently
importable in the worker's Python, and attempts `pip install` for each one
into the worker's site-packages. nbclient's kernel sees those packages on its
next start, so the notebook executes against a freshly-augmented environment.

Worker concurrency is 1 (see `--concurrency=1` in docker-compose.yml), so
parallel install races aren't a concern. Installs persist across runs, which
is intentional — most subsequent submissions reuse the same packages.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# Names students write in `import X` that map to a different PyPI distribution.
# Only includes ones where the import name and the pip name actually differ —
# packages where they match (numpy, pandas, gdown, kagglehub, ...) don't need
# an entry here; we just `pip install <import_name>` and PyPI resolves it.
IMPORT_TO_PIP: dict[str, str] = {
    "cv2": "opencv-python",
    "sklearn": "scikit-learn",
    "PIL": "pillow",
    "skimage": "scikit-image",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "Levenshtein": "python-Levenshtein",
    "dateutil": "python-dateutil",
    "google.colab": "",  # explicit no-op — colab_stub already provides this
    "google": "",  # google.* is provided by various google-* packages already pinned
}

# Best-effort stdlib detection. Python 3.10+ exposes stdlib_module_names; we
# also defensively skip a few names that aren't in stdlib_module_names but
# still shouldn't trigger an install (relative-style fragments, etc).
_STDLIB: frozenset[str] = frozenset(getattr(sys, "stdlib_module_names", set())) | frozenset({
    "__future__",
    "typing_extensions",  # pulled in transitively by lots of pinned deps
})

# Names that are *almost certainly* a typo, malicious squat, or the student's
# own local module — never auto-install these.
_DENYLIST: frozenset[str] = frozenset({
    "your_module",
    "my_module",
    "test",
    "tests",
    "src",
    "app",
    "main",
    "utils",
    "helpers",
})

# PEP 503 normalized name shape — lets through real PyPI names, blocks shell
# metacharacters and path traversal.
_PKG_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")

# Find `import X`, `import X as Y`, `import X.Y`, `from X.Y import ...`
# Captures only the top-level package (X), one per line. Crude — doesn't
# parse the AST — but good enough for student notebooks and avoids ipykernel
# magics like `%matplotlib inline` and shell escapes like `!pip install gdown`.
_IMPORT_RE = re.compile(
    r"""^\s*
        (?:
            from\s+(?P<from>[A-Za-z_][\w.]*)\s+import\b
          | import\s+(?P<imp>[A-Za-z_][\w.]*)
        )
    """,
    re.MULTILINE | re.VERBOSE,
)


@dataclass
class InstallAttempt:
    pip_name: str
    import_name: str
    ok: bool
    duration_s: float
    output: str  # stdout+stderr, truncated for log readability


@dataclass
class AutoInstallReport:
    discovered: list[str]  # top-level imports found in the notebook
    skipped: list[tuple[str, str]]  # (name, reason) — already importable, stdlib, denied, ...
    attempts: list[InstallAttempt]
    log: str  # human-readable block to prepend to the run log


def _extract_top_level_imports(notebook_path: Path) -> list[str]:
    """Return the unique top-level package names imported by code cells."""
    try:
        nb = json.loads(notebook_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    seen: list[str] = []
    seen_set: set[str] = set()
    for cell in nb.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        if isinstance(src, list):
            src = "".join(src)
        for match in _IMPORT_RE.finditer(src or ""):
            raw = match.group("from") or match.group("imp")
            if not raw:
                continue
            top = raw.split(".")[0]
            if top and top not in seen_set:
                seen.append(top)
                seen_set.add(top)
    return seen


def _is_importable(name: str) -> bool:
    """Cheap probe — uses find_spec so we don't actually execute the module."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _pip_install(pip_name: str, timeout_s: int = 120) -> InstallAttempt:
    start = time.monotonic()
    cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check", pip_name]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        ok = proc.returncode == 0
        # Trim verbose output — "Successfully installed ..." or the last error stanza is what matters.
        out = (proc.stdout + proc.stderr).strip()
        if len(out) > 1500:
            out = out[:600] + "\n  ... (output trimmed) ...\n" + out[-600:]
    except subprocess.TimeoutExpired:
        ok = False
        out = f"pip install timed out after {timeout_s}s"
    except Exception as exc:
        ok = False
        out = f"pip install errored: {exc}"
    return InstallAttempt(
        pip_name=pip_name,
        import_name=pip_name,
        ok=ok,
        duration_s=round(time.monotonic() - start, 2),
        output=out,
    )


def auto_install_missing(
    notebook_path: Path,
    *,
    max_installs: int = 8,
    total_budget_s: int = 300,
    per_install_timeout_s: int = 120,
) -> AutoInstallReport:
    """Resolve as many missing imports as possible, within budget.

    Caps:
      - max_installs: at most N pip invocations per run
      - total_budget_s: stop after this many wall-clock seconds across all installs
      - per_install_timeout_s: kill any single install after this many seconds

    Returns a report including a `log` string suitable for prepending to the
    run log artifact. Never raises — failures are recorded and execution
    continues so the notebook can still run (and surface ModuleNotFoundError
    to the grader if needed).
    """
    discovered = _extract_top_level_imports(notebook_path)
    skipped: list[tuple[str, str]] = []
    attempts: list[InstallAttempt] = []

    deadline = time.monotonic() + total_budget_s

    for name in discovered:
        if len(attempts) >= max_installs:
            skipped.append((name, "max_installs reached"))
            continue
        if time.monotonic() >= deadline:
            skipped.append((name, "total budget exhausted"))
            continue
        if name in _STDLIB:
            skipped.append((name, "stdlib"))
            continue
        if name in _DENYLIST:
            skipped.append((name, "denylist"))
            continue
        if _is_importable(name):
            skipped.append((name, "already importable"))
            continue
        if not _PKG_NAME_RE.match(name):
            skipped.append((name, "invalid package name"))
            continue

        # Map import-name → pip-name. Empty string in the map means "skip".
        pip_name = IMPORT_TO_PIP.get(name, name)
        if pip_name == "":
            skipped.append((name, "explicitly mapped to no-op"))
            continue

        remaining = max(5, int(deadline - time.monotonic()))
        timeout = min(per_install_timeout_s, remaining)
        attempt = _pip_install(pip_name, timeout_s=timeout)
        attempt.import_name = name
        attempts.append(attempt)

    log_lines: list[str] = []
    log_lines.append("=== auto-install pre-pass ===")
    if discovered:
        log_lines.append(f"Discovered top-level imports: {', '.join(discovered)}")
    else:
        log_lines.append("No top-level imports discovered (notebook empty or unparsable).")
    for name, reason in skipped:
        log_lines.append(f"  · {name}: skipped ({reason})")
    for a in attempts:
        status = "ok" if a.ok else "FAILED"
        log_lines.append(f"  · {a.import_name} -> pip install {a.pip_name}: {status} in {a.duration_s}s")
        if not a.ok:
            for line in a.output.splitlines()[-6:]:
                log_lines.append(f"      {line}")
    log_lines.append("=== end auto-install pre-pass ===\n")

    return AutoInstallReport(
        discovered=discovered,
        skipped=skipped,
        attempts=attempts,
        log="\n".join(log_lines),
    )
