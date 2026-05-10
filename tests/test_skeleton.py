"""
Acceptance tests for Story 1 — Module skeleton and log path constant.

Verifies:
  - Package structure (Tools/Standup/__init__.py, standup.py)
  - Module is importable
  - LOG_PATH is a pathlib.Path resolving to Tools/Standup/log.jsonl
  - Public API stubs (open_standup, close_standup, history) are importable
  - Each stub raises NotImplementedError when called
  - Stubs have correct signatures (parameter names and type hints)

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib
import sys
import typing

import pytest


# --------------------------------------------------------------------------- #
# Path setup — ensure Tools/Standup/ is importable regardless of where pytest
# is invoked from. The tests file lives at Tools/Standup/tests/test_skeleton.py
# so the package directory is the parent of `tests/`.
# --------------------------------------------------------------------------- #

THIS_FILE = pathlib.Path(__file__).resolve()
PACKAGE_DIR = THIS_FILE.parent.parent           # .../Tools/Standup
PACKAGE_PARENT = PACKAGE_DIR.parent              # .../Tools

# Insert the package's PARENT on sys.path so `from Standup import ...` and
# `import standup` (when run from inside Tools/Standup) both work. We add the
# package dir directly so `from standup import X` (lowercase) resolves.
for p in (str(PACKAGE_DIR), str(PACKAGE_PARENT)):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------- #
# CRITERION 1 — Package structure exists on disk
# --------------------------------------------------------------------------- #

def test_package_directory_exists():
    """Tools/Standup/ must exist as a directory."""
    assert PACKAGE_DIR.is_dir(), (
        f"Expected package directory at {PACKAGE_DIR}, not found"
    )


def test_standup_module_file_exists():
    """standup.py must exist (the main module file)."""
    module_file = PACKAGE_DIR / "standup.py"
    assert module_file.is_file(), (
        f"Expected {module_file} to exist (main module)"
    )


# --------------------------------------------------------------------------- #
# CRITERION 2 — Module is importable
# --------------------------------------------------------------------------- #

def test_module_importable():
    """`import standup` must succeed without error."""
    # Use importlib so a clean import error surfaces clearly.
    standup = importlib.import_module("standup")
    assert standup is not None


def test_public_api_importable_via_from_import():
    """`from standup import open_standup, close_standup, history, LOG_PATH`
    must work without error (acceptance criterion verbatim)."""
    # Force reimport to ensure we exercise the actual import statement
    # behavior, not a cached module from a prior test.
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import (  # noqa: F401
        open_standup,
        close_standup,
        history,
        LOG_PATH,
    )


# --------------------------------------------------------------------------- #
# CRITERION 3 — LOG_PATH constant
# --------------------------------------------------------------------------- #

def test_log_path_is_pathlib_path():
    """LOG_PATH must be a pathlib.Path object (not a string)."""
    from standup import LOG_PATH
    assert isinstance(LOG_PATH, pathlib.PurePath), (
        f"LOG_PATH must be a pathlib.Path, got {type(LOG_PATH).__name__}"
    )


def test_log_path_filename_is_log_jsonl():
    """LOG_PATH must point at a file named log.jsonl."""
    from standup import LOG_PATH
    assert LOG_PATH.name == "log.jsonl", (
        f"LOG_PATH filename must be 'log.jsonl', got '{LOG_PATH.name}'"
    )


def test_log_path_resolves_inside_standup_package():
    """LOG_PATH must resolve to Tools/Standup/log.jsonl, computed relative
    to the module file (not hardcoded). Verified by checking parent
    directory matches the package directory on disk."""
    from standup import LOG_PATH
    # Resolve both sides so symlinks/relative segments don't cause spurious
    # mismatches. We compare the parent directory rather than the file
    # itself because the file isn't required to exist yet.
    expected_parent = PACKAGE_DIR.resolve()
    actual_parent = pathlib.Path(LOG_PATH).resolve().parent
    assert actual_parent == expected_parent, (
        f"LOG_PATH parent must be {expected_parent}, got {actual_parent}"
    )


def test_log_path_not_hardcoded_absolute_string():
    """LOG_PATH must be derived from __file__ (pathlib), not a hardcoded
    absolute string. Indirect check: re-import the module from a different
    cwd and confirm LOG_PATH still resolves under the package directory."""
    import os
    cwd_before = os.getcwd()
    try:
        # Move cwd somewhere unrelated.
        os.chdir(PACKAGE_DIR.parent.parent)  # repo root-ish
        if "standup" in sys.modules:
            del sys.modules["standup"]
        from standup import LOG_PATH as LOG_PATH_2
        actual_parent = pathlib.Path(LOG_PATH_2).resolve().parent
        assert actual_parent == PACKAGE_DIR.resolve(), (
            "LOG_PATH must be computed from __file__ — it changed when cwd "
            f"changed. Got parent {actual_parent}, expected {PACKAGE_DIR}"
        )
    finally:
        os.chdir(cwd_before)


# --------------------------------------------------------------------------- #
# CRITERION 4 — Public function stubs exist
# --------------------------------------------------------------------------- #

def test_open_standup_is_callable():
    from standup import open_standup
    assert callable(open_standup)


def test_close_standup_is_callable():
    from standup import close_standup
    assert callable(close_standup)


def test_history_is_callable():
    from standup import history
    assert callable(history)


# --------------------------------------------------------------------------- #
# CRITERION 5 — Each stub raises NotImplementedError
# --------------------------------------------------------------------------- #

# NOTE: test_open_standup_raises_not_implemented was removed in Story 8.
# Story 1 verified the stub state (raises NotImplementedError); Story 8
# replaces that stub with a working implementation, so the stub-state
# test no longer reflects the contract for open_standup. The Story-8
# acceptance tests in test_open_standup.py now own that surface.
#
# NOTE: test_close_standup_raises_not_implemented and
# test_close_standup_signature were removed in Story 10. Story 1
# verified the stub state (raises NotImplementedError) and the 1-arg
# signature; Story 10 replaces that stub with a working implementation
# whose signature widens to 4 parameters
# (session_id, shifted, tomorrows_first_move, blocking), so the
# stub-state and old-signature tests no longer reflect the contract for
# close_standup. The Story-10 acceptance tests in test_close_standup.py
# now own that surface.
#
# NOTE: test_history_raises_not_implemented was removed in Story 12.
# Story 1 verified the stub state (raises NotImplementedError); Story 12
# replaces that stub with a working implementation, so the stub-state
# test no longer reflects the contract for history. The Story-12
# acceptance tests in test_history.py now own that surface.
#
# All three public-API stubs are now implemented; no stub-state tests
# remain in this file.


# --------------------------------------------------------------------------- #
# CRITERION 6 — Stub signatures (parameter names + type hints)
# --------------------------------------------------------------------------- #

def test_open_standup_signature():
    """open_standup() takes no parameters and is annotated -> dict."""
    from standup import open_standup
    sig = inspect.signature(open_standup)
    assert list(sig.parameters.keys()) == [], (
        f"open_standup must take no parameters, got {list(sig.parameters)}"
    )
    hints = typing.get_type_hints(open_standup)
    assert hints.get("return") is dict, (
        f"open_standup return annotation must be dict, got {hints.get('return')}"
    )


# NOTE: test_close_standup_signature was removed in Story 10. The
# original 1-arg signature (session_id only) was widened to 4
# parameters (session_id, shifted, tomorrows_first_move, blocking) when
# the stub was replaced with a working implementation. The Story-10
# acceptance tests in test_close_standup.py now pin the new signature.


def test_history_signature():
    """history(window: str) -> str."""
    from standup import history
    sig = inspect.signature(history)
    params = list(sig.parameters.keys())
    assert params == ["window"], (
        f"history must accept exactly ['window'], got {params}"
    )
    hints = typing.get_type_hints(history)
    assert hints.get("window") is str, (
        f"window annotation must be str, got {hints.get('window')}"
    )
    assert hints.get("return") is str, (
        f"history return annotation must be str, got {hints.get('return')}"
    )


# --------------------------------------------------------------------------- #
# EDGE CASES — adversarial checks beyond minimum criteria
# --------------------------------------------------------------------------- #

def test_log_path_does_not_have_to_exist_yet():
    """The log file itself need not exist at skeleton time — only the path
    constant. This test documents that expectation so a future contributor
    doesn't add a file-existence assertion by mistake."""
    from standup import LOG_PATH
    # No assertion on existence — both states are acceptable at skeleton.
    # Just confirm it's a path-like and not, say, an open file handle.
    assert isinstance(LOG_PATH, pathlib.PurePath)


def test_stubs_do_not_swallow_args_silently():
    """close_standup must not accept arbitrary keyword arguments — the
    signature is fixed. Guards against `def close_standup(*args, **kwargs)`
    style stubs that would mask later signature mistakes."""
    from standup import close_standup
    sig = inspect.signature(close_standup)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"close_standup must not use *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_history_does_not_swallow_args_silently():
    """Same guard for history."""
    from standup import history
    sig = inspect.signature(history)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"history must not use *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_open_standup_does_not_swallow_args_silently():
    """Same guard for open_standup."""
    from standup import open_standup
    sig = inspect.signature(open_standup)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"open_standup must not use *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )
