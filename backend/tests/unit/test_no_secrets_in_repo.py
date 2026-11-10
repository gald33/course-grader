"""No API key, token or filled-in .env anywhere in the repository (lesson 7
has students put a real Gemini API key in a local .env; none of that may ever
be committed, and the downloads ship without one). Every tracked file is read
as bytes, including the zips, which are stored uncompressed."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]

KEY_LIKE = {
    "Google API key": re.compile(rb"AIza[0-9A-Za-z_\-]{35}"),
    "OpenAI key": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"),
    "Anthropic key": re.compile(rb"\bsk-ant-[A-Za-z0-9_\-]{20,}"),
    "GitHub token": re.compile(rb"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{30,}"),
    "a provider key with a value": re.compile(
        rb"\b(?:GEMINI|GOOGLE|OPENAI|ANTHROPIC)_API_KEY[ \t]*=[ \t]*[\"']?[A-Za-z0-9_\-]{12,}"),
}


def _repo_files() -> list[Path]:
    try:
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=REPO,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [REPO / p.decode() for p in out.split(b"\0") if p and (REPO / p.decode()).is_file()]


def test_the_patterns_catch_what_they_should():
    fake_google = b"AIza" + b"x" * 35
    assert KEY_LIKE["Google API key"].search(b"key: " + fake_google)
    assert KEY_LIKE["OpenAI key"].search(b"sk-" + b"a1" * 12)
    assert KEY_LIKE["a provider key with a value"].search(b"GEMINI_API_KEY=" + b"abc123def456ghi")  # built here, so this file stays clean
    # An empty line in a template, or code that reads the variable, is fine.
    assert not KEY_LIKE["a provider key with a value"].search(b"GEMINI_API_KEY=\nAI_MODE=live")
    assert not KEY_LIKE["a provider key with a value"].search(b"const key = process.env.GEMINI_API_KEY || '';")
    assert not KEY_LIKE["a provider key with a value"].search("אחרי `GEMINI_API_KEY=`.".encode())
    assert not KEY_LIKE["a provider key with a value"].search(b"ANTHROPIC_API_KEY=sk-ant-...")  # a placeholder


def test_no_key_like_string_or_env_file_is_in_the_repository():
    files = _repo_files()
    assert len(files) > 100
    assert not [f for f in files if f.name == ".env"], "a .env file is in the repository"
    found = []
    for path in files:
        data = path.read_bytes()
        for name, pattern in KEY_LIKE.items():
            if pattern.search(data):
                found.append(f"{path.relative_to(REPO)}: {name}")
    assert not found, found
