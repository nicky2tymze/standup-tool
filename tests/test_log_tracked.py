"""
Acceptance tests for Story 13 — log.jsonl tracked, NOT gitignored.

Rolls up to PO v2 Requirement 12: commit-on-pause, log is a tracked file.

Verifies:
  - Tools/Standup/log.jsonl exists at the canonical path
  - The path matches LOG_PATH from the standup module
  - log.jsonl is a regular file (not a directory, not a symlink)
  - If non-empty, every line parses as JSON (no garbage initial content)
  - log.jsonl is NOT matched by any .gitignore pattern (verified via
    `git check-ignore` — non-zero exit means "not ignored")

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

import pytest


# --------------------------------------------------------------------------- #
# Path setup — mirror test_skeleton.py so the standup module imports cleanly
# regardless of where pytest is invoked from.
# --------------------------------------------------------------------------- #

THIS_FILE = pathlib.Path(__file__).resolve()
PACKAGE_DIR = THIS_FILE.parent.parent           # repo root (package lives at root)
PACKAGE_PARENT = PACKAGE_DIR.parent              # parent of repo root
REPO_ROOT = PACKAGE_DIR                          # standup-tool/ IS the repo root

for p in (str(PACKAGE_DIR), str(PACKAGE_PARENT)):
    if p not in sys.path:
        sys.path.insert(0, p)


EXPECTED_LOG_PATH = PACKAGE_DIR / "log.jsonl"


# --------------------------------------------------------------------------- #
# CRITERION 1 — log.jsonl exists at the canonical path
# --------------------------------------------------------------------------- #

def test_log_file_exists():
    """Tools/Standup/log.jsonl must exist on disk."""
    assert EXPECTED_LOG_PATH.exists(), (
        f"Expected log file at {EXPECTED_LOG_PATH}, not found. "
        "Coder Agent must create the file."
    )


# --------------------------------------------------------------------------- #
# CRITERION 2 — File matches LOG_PATH constant from standup module
# --------------------------------------------------------------------------- #

def test_log_file_path_matches_module_constant():
    """The file on disk must live at exactly the path standup.LOG_PATH
    points to. If these drift, the production code and test fixtures
    refer to different files."""
    from standup import LOG_PATH
    actual = pathlib.Path(LOG_PATH).resolve()
    expected = EXPECTED_LOG_PATH.resolve()
    assert actual == expected, (
        f"LOG_PATH ({actual}) must equal canonical log path ({expected})"
    )


def test_log_path_constant_points_to_existing_file():
    """The path standup.LOG_PATH names must resolve to a real file on
    disk — the constant alone isn't enough; the file must be there."""
    from standup import LOG_PATH
    assert pathlib.Path(LOG_PATH).exists(), (
        f"Path declared by LOG_PATH ({LOG_PATH}) does not exist on disk"
    )


# --------------------------------------------------------------------------- #
# CRITERION 3 — log.jsonl is a regular file (not directory, not symlink)
# --------------------------------------------------------------------------- #

def test_log_file_is_regular_file():
    """log.jsonl must be a regular file — not a directory, not a symlink,
    not a special device. Symlinks would let the tracked file resolve
    outside the repo, which violates the "checked into the repo" intent."""
    assert EXPECTED_LOG_PATH.is_file(), (
        f"{EXPECTED_LOG_PATH} must be a regular file"
    )


def test_log_file_is_not_directory():
    """Defensive: explicitly forbid the directory case so an accidental
    `mkdir log.jsonl` is caught with a clear error."""
    assert not EXPECTED_LOG_PATH.is_dir(), (
        f"{EXPECTED_LOG_PATH} is a directory, must be a regular file"
    )


def test_log_file_is_not_symlink():
    """log.jsonl must not be a symlink. Path.is_symlink() does not follow
    the link, so this catches symlinks even when their target exists and
    is itself a regular file."""
    assert not EXPECTED_LOG_PATH.is_symlink(), (
        f"{EXPECTED_LOG_PATH} is a symlink; must be a real file in the repo"
    )


# --------------------------------------------------------------------------- #
# CRITERION 4 — Initial content is empty OR valid JSONL
# --------------------------------------------------------------------------- #

def test_log_file_is_empty_or_valid_jsonl():
    """If the file is empty (zero bytes), pass. Otherwise every non-blank
    line must parse as JSON. Blank lines are tolerated only if they are
    purely whitespace — anything else is treated as garbage."""
    text = EXPECTED_LOG_PATH.read_text(encoding="utf-8")
    if text == "":
        # Zero bytes — explicitly allowed by acceptance.
        return

    lines = text.splitlines()
    bad: list[tuple[int, str, str]] = []
    for idx, line in enumerate(lines, start=1):
        if line.strip() == "":
            # Whitespace-only line — tolerated, JSONL readers skip these.
            continue
        try:
            json.loads(line)
        except json.JSONDecodeError as exc:
            bad.append((idx, line, str(exc)))

    assert not bad, (
        "log.jsonl is non-empty but contains non-JSON lines: "
        + "; ".join(f"line {n}: {msg} ({line!r})" for n, line, msg in bad)
    )


def test_log_file_size_is_zero_or_positive():
    """Sanity: stat() must succeed (file is readable) and report a size
    >= 0. Catches the case where the file exists per is_file() but the
    OS reports an error reading its metadata."""
    size = EXPECTED_LOG_PATH.stat().st_size
    assert size >= 0, (
        f"log.jsonl reported negative size {size} — filesystem error?"
    )


# --------------------------------------------------------------------------- #
# CRITERION 5 — log.jsonl is NOT matched by any .gitignore pattern
# --------------------------------------------------------------------------- #

def _git_check_ignore(path: pathlib.Path) -> subprocess.CompletedProcess:
    """Run `git check-ignore -v <path>` from the repo root. Returns the
    completed process. Exit 0 == path IS ignored (bad). Exit 1 == path is
    NOT ignored (good). Exit 128 or other == git error — surfaced as test
    failure with a clear message."""
    return subprocess.run(
        ["git", "check-ignore", "-v", str(path)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_log_file_not_matched_by_gitignore():
    """`git check-ignore` must return non-zero exit for log.jsonl. Exit 0
    means a .gitignore rule is excluding the file (violates the story).
    Exit 1 means "not ignored" — the desired state."""
    result = _git_check_ignore(EXPECTED_LOG_PATH)
    if result.returncode == 0:
        # Ignored — surface which rule and which file did it.
        pytest.fail(
            "log.jsonl is matched by a .gitignore pattern. "
            f"`git check-ignore -v` reported:\n{result.stdout}\n"
            "Coder Agent must adjust .gitignore so this file is tracked."
        )
    if result.returncode not in (0, 1):
        # 128 or similar — git error, not a "not ignored" signal.
        pytest.fail(
            f"git check-ignore failed unexpectedly (exit {result.returncode}). "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    # returncode == 1 — not ignored. Good.


def test_log_file_not_matched_by_gitignore_via_relative_path():
    """Same check using a path relative to the repo root. Defends against
    a .gitignore rule that only matches one of (absolute, relative) forms.
    `git check-ignore` is the source of truth, so we exercise both."""
    rel = EXPECTED_LOG_PATH.relative_to(REPO_ROOT)
    result = subprocess.run(
        ["git", "check-ignore", "-v", str(rel)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        pytest.fail(
            "log.jsonl (relative path) is matched by a .gitignore pattern. "
            f"`git check-ignore -v` reported:\n{result.stdout}"
        )
    if result.returncode not in (0, 1):
        pytest.fail(
            f"git check-ignore failed unexpectedly (exit {result.returncode}). "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )


# --------------------------------------------------------------------------- #
# EDGE CASES — adversarial checks beyond minimum criteria
# --------------------------------------------------------------------------- #

def test_git_is_available():
    """Sanity: the `git` executable must be on PATH and the repo must be
    a real git repo. If this fails, the gitignore tests above are
    meaningless and we want a clear early signal."""
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"git not available or {REPO_ROOT} is not a git work tree. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert result.stdout.strip() == "true", (
        f"Expected 'true' from git rev-parse, got {result.stdout!r}"
    )


def test_log_file_is_under_repo_root():
    """The canonical log path must live inside the repo so git can track
    it. A symlink test above already rejects symlinks, but this catches
    the case where someone moved the package outside the repo root."""
    try:
        EXPECTED_LOG_PATH.resolve().relative_to(REPO_ROOT.resolve())
    except ValueError:
        pytest.fail(
            f"log.jsonl resolves to {EXPECTED_LOG_PATH.resolve()}, "
            f"which is not under repo root {REPO_ROOT.resolve()}. "
            "git cannot track files outside the work tree."
        )


def test_log_file_uses_utf8_encoding():
    """Non-empty content must be valid UTF-8. JSONL is text; binary garbage
    written to the file would pass the JSON test only by accident. This
    test fails fast on encoding mistakes (e.g., UTF-16 BOM from PowerShell
    `Set-Content` without `-Encoding utf8`)."""
    raw = EXPECTED_LOG_PATH.read_bytes()
    if not raw:
        return  # empty file is fine
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(
            f"log.jsonl is not valid UTF-8: {exc}. "
            "If created on Windows, ensure -Encoding utf8 was used."
        )


def test_log_file_no_utf8_bom():
    """A UTF-8 BOM (EF BB BF) at the start of a JSONL file breaks naive
    json.loads on the first line. Forbid it explicitly."""
    raw = EXPECTED_LOG_PATH.read_bytes()
    if not raw:
        return
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        "log.jsonl starts with a UTF-8 BOM; strip it. "
        "json.loads on the first line will fail with a BOM present."
    )
