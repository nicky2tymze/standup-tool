"""
Acceptance tests for Story 5 — Append-only write to JSONL log.

Rolls up to PO v2 Requirements 1 (persistent JSONL log) and 8 (append-only).

Verifies the private helper ``_append_entry(entry: dict) -> None`` in
``standup``:

  - importable as ``from standup import _append_entry``
  - NOT exported in ``standup.__all__`` (private)
  - writes one JSON-encoded line per call to ``LOG_PATH``
  - opens in append mode, UTF-8 encoded, no BOM
  - lines end with ``\\n``
  - never reads existing log content, never truncates
  - rejects non-dict input loudly (TypeError)
  - propagates a clear error for non-JSON-serializable entry values
  - returns None
  - preserves unicode (non-ASCII, emoji) and nested structures verbatim
  - call order on disk matches call order in code (FIFO append)

Test isolation: every test monkeypatches ``standup.LOG_PATH`` to a
tmp_path file so the real ``Tools/Standup/log.jsonl`` is never written.

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import datetime
import importlib
import io
import json
import pathlib
import sys

import pytest


# --------------------------------------------------------------------------- #
# Path setup — mirror the other test files so the standup module imports
# cleanly regardless of where pytest is invoked from.
# --------------------------------------------------------------------------- #

THIS_FILE = pathlib.Path(__file__).resolve()
PACKAGE_DIR = THIS_FILE.parent.parent           # .../Tools/Standup
PACKAGE_PARENT = PACKAGE_DIR.parent              # .../Tools

for p in (str(PACKAGE_DIR), str(PACKAGE_PARENT)):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------- #
# Fixture — redirect LOG_PATH to a per-test tmp file so the real log is
# never touched. Using monkeypatch ensures the original is restored even
# if a test fails.
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Monkeypatch ``standup.LOG_PATH`` to a tmp file for one test.

    Returns the path object so the test can read it back. The file does
    NOT exist on entry — exercising "first append creates the file" is
    a normal use of the helper.
    """
    # Reload defensively so a previous test's monkeypatch didn't leak.
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402  (import after sys.path setup)

    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file


@pytest.fixture
def isolated_log_existing(tmp_path, monkeypatch):
    """Same as ``isolated_log`` but seeded with one pre-existing line so
    tests can assert ``_append_entry`` does not truncate."""
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402

    log_file = tmp_path / "log.jsonl"
    seed = {"_seed": True, "n": 0}
    log_file.write_text(json.dumps(seed) + "\n", encoding="utf-8")
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file, seed


# --------------------------------------------------------------------------- #
# CRITERION — _append_entry is importable from `standup`
# --------------------------------------------------------------------------- #

def test_append_entry_importable():
    """`from standup import _append_entry` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import _append_entry  # noqa: F401
    assert callable(_append_entry)


def test_append_entry_is_callable_attribute_on_module():
    """The helper must live on the standup module (not in a submodule)."""
    import standup
    assert hasattr(standup, "_append_entry"), (
        "standup module must define _append_entry"
    )
    assert callable(standup._append_entry)


# --------------------------------------------------------------------------- #
# CRITERION — _append_entry is NOT in __all__ (private)
# --------------------------------------------------------------------------- #

def test_append_entry_not_in_dunder_all():
    """Private helpers must not be re-exported via __all__."""
    import standup
    assert "_append_entry" not in standup.__all__, (
        "_append_entry must be private (excluded from __all__); "
        f"current __all__ = {standup.__all__}"
    )


def test_append_entry_name_is_underscore_prefixed():
    """Adversarial guard: even if a future refactor renames the function,
    its public-facing name must remain underscore-prefixed."""
    import standup
    # Search module for callables that look like the implementation under
    # any name; the canonical name is _append_entry, but reject any public
    # alias that exposes the same callable.
    for name in standup.__all__:
        obj = getattr(standup, name, None)
        if obj is getattr(standup, "_append_entry", object()):
            pytest.fail(
                f"Public alias {name!r} exposes _append_entry; "
                "private helpers must not be re-exported"
            )


# --------------------------------------------------------------------------- #
# CRITERION — Single dict call appends one valid JSON line
# --------------------------------------------------------------------------- #

def test_single_call_writes_one_line(isolated_log):
    """One call -> one line in the file."""
    from standup import _append_entry
    _append_entry({"event": "open", "id": "abc"})

    text = isolated_log.read_text(encoding="utf-8")
    # Exactly one newline-terminated line, no trailing extras.
    assert text.count("\n") == 1, (
        f"expected 1 newline, got {text.count(chr(10))}; content={text!r}"
    )


def test_single_call_line_is_valid_json(isolated_log):
    """The line written must parse cleanly with json.loads."""
    from standup import _append_entry
    entry = {"event": "open", "id": "abc"}
    _append_entry(entry)

    line = isolated_log.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(line)  # raises -> test fails
    assert isinstance(parsed, dict)


def test_single_call_round_trip_equals_input(isolated_log):
    """The parsed JSON must equal the input dict exactly."""
    from standup import _append_entry
    entry = {"event": "close", "id": "xyz", "n": 42, "ok": True}
    _append_entry(entry)

    line = isolated_log.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(line)
    assert parsed == entry


def test_returns_none(isolated_log):
    """The helper must return None per the signature."""
    from standup import _append_entry
    result = _append_entry({"k": "v"})
    assert result is None


# --------------------------------------------------------------------------- #
# CRITERION — Multiple calls append in order, one line each
# --------------------------------------------------------------------------- #

def test_two_calls_produce_two_lines_in_order(isolated_log):
    """Sequential calls write sequential lines; order is preserved."""
    from standup import _append_entry
    a = {"i": 1, "tag": "first"}
    b = {"i": 2, "tag": "second"}
    _append_entry(a)
    _append_entry(b)

    lines = isolated_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, f"expected 2 lines, got {len(lines)}"
    assert json.loads(lines[0]) == a
    assert json.loads(lines[1]) == b


def test_fifty_calls_produce_fifty_lines(isolated_log):
    """Stress: 50 sequential calls produce 50 ordered lines."""
    from standup import _append_entry
    expected = [{"i": i, "v": f"row-{i}"} for i in range(50)]
    for entry in expected:
        _append_entry(entry)

    lines = isolated_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 50
    parsed = [json.loads(L) for L in lines]
    assert parsed == expected, "lines did not preserve call order"


# --------------------------------------------------------------------------- #
# CRITERION — Each line ends with \n (newline terminator)
# --------------------------------------------------------------------------- #

def test_line_ends_with_lf_newline(isolated_log):
    """The line terminator must be a single LF (\\n), not CRLF or none."""
    from standup import _append_entry
    _append_entry({"k": "v"})

    raw = isolated_log.read_bytes()
    assert raw.endswith(b"\n"), f"file does not end with LF; raw={raw!r}"
    # Forbid CRLF terminators; the spec mandates platform-independent \n.
    assert b"\r\n" not in raw, (
        f"file contains CRLF — must use LF only; raw={raw!r}"
    )


def test_each_of_many_lines_ends_with_lf(isolated_log):
    """Every appended line must terminate with LF, including the last."""
    from standup import _append_entry
    for i in range(5):
        _append_entry({"i": i})

    raw = isolated_log.read_bytes()
    # Five LFs; nothing else as terminator.
    assert raw.count(b"\n") == 5
    assert b"\r" not in raw, f"CR byte present in log: {raw!r}"


# --------------------------------------------------------------------------- #
# CRITERION — UTF-8 encoding, no BOM, unicode preserved
# --------------------------------------------------------------------------- #

def test_unicode_chinese_preserved(isolated_log):
    """Non-ASCII text must round-trip exactly."""
    from standup import _append_entry
    entry = {"note": "中文测试"}
    _append_entry(entry)

    line = isolated_log.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(line)
    assert parsed == entry
    assert parsed["note"] == "中文测试"


def test_unicode_emoji_preserved(isolated_log):
    """Emoji (4-byte UTF-8 sequences) must round-trip exactly."""
    from standup import _append_entry
    entry = {"mood": "🔥💧✨", "ok": True}
    _append_entry(entry)

    line = isolated_log.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(line)
    assert parsed == entry
    assert parsed["mood"] == "🔥💧✨"


def test_no_utf8_bom_at_start(isolated_log):
    """The file must NOT begin with a UTF-8 BOM (EF BB BF). On Windows
    a careless `open(..., encoding='utf-8-sig')` would inject one and
    break naive json.loads on the first line."""
    from standup import _append_entry
    _append_entry({"k": "v"})

    raw = isolated_log.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), (
        f"log file starts with UTF-8 BOM; raw={raw[:6]!r}"
    )


def test_file_is_valid_utf8(isolated_log):
    """Raw bytes must decode cleanly as UTF-8."""
    from standup import _append_entry
    _append_entry({"latin": "café", "cyr": "Привет"})

    raw = isolated_log.read_bytes()
    # Will raise UnicodeDecodeError -> test failure if encoding is wrong.
    raw.decode("utf-8")


# --------------------------------------------------------------------------- #
# CRITERION — Append mode: never truncates existing content
# --------------------------------------------------------------------------- #

def test_does_not_truncate_existing_content(isolated_log_existing):
    """Pre-existing line in the log must survive an append."""
    log_file, seed = isolated_log_existing
    from standup import _append_entry
    new_entry = {"i": 1, "added": True}
    _append_entry(new_entry)

    lines = log_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2, (
        f"expected seed + 1 appended = 2 lines, got {len(lines)}"
    )
    assert json.loads(lines[0]) == seed, "seed line was modified or removed"
    assert json.loads(lines[1]) == new_entry, "new entry not at end"


def test_append_preserves_byte_prefix(isolated_log_existing):
    """Defensive byte-level check: the bytes that were in the file before
    the append must still be the first N bytes after the append. Catches
    any implementation that silently rewrites the file."""
    log_file, _seed = isolated_log_existing
    before = log_file.read_bytes()

    from standup import _append_entry
    _append_entry({"x": 1})

    after = log_file.read_bytes()
    assert after.startswith(before), (
        "append modified pre-existing bytes; not append-only.\n"
        f"before={before!r}\nafter={after!r}"
    )
    assert len(after) > len(before), "file did not grow"


def test_append_does_not_read_existing_content(
    isolated_log_existing, monkeypatch
):
    """Replace ``open`` with a wrapper that records mode flags; assert
    the helper never opens the log for reading. Append-only is a contract
    on intent, not just outcome."""
    log_file, _seed = isolated_log_existing
    import builtins
    import standup

    real_open = builtins.open
    opens: list[tuple[str, str]] = []

    def tracking_open(file, mode="r", *args, **kwargs):
        # Only record opens that touch the LOG_PATH file specifically.
        try:
            same = pathlib.Path(file).resolve() == log_file.resolve()
        except (TypeError, OSError):
            same = False
        if same:
            opens.append((str(file), mode))
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", tracking_open)

    standup._append_entry({"k": "v"})

    assert opens, "log file was never opened — implementation suspicious"
    for path, mode in opens:
        # 'a' or 'ab' is fine; 'r', 'r+', 'w', 'w+' are not.
        assert "r" not in mode and "w" not in mode, (
            f"_append_entry opened {path!r} with mode {mode!r}; "
            "must use append-only mode (e.g. 'a')"
        )
        assert "a" in mode, (
            f"_append_entry opened {path!r} with mode {mode!r}; "
            "expected an append mode containing 'a'"
        )


# --------------------------------------------------------------------------- #
# CRITERION — First call creates the file (no preexistence required)
# --------------------------------------------------------------------------- #

def test_first_call_creates_file(isolated_log):
    """Append mode must create the file if it does not yet exist."""
    assert not isolated_log.exists(), (
        "fixture invariant: log should not exist before first append"
    )
    from standup import _append_entry
    _append_entry({"first": True})
    assert isolated_log.is_file(), "file was not created on first append"
    parsed = json.loads(isolated_log.read_text(encoding="utf-8").rstrip("\n"))
    assert parsed == {"first": True}


# --------------------------------------------------------------------------- #
# CRITERION — Type errors: non-dict input must fail loudly
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad",
    [
        None,
        "a string",
        42,
        3.14,
        True,
        [{"a": 1}],
        ("tuple",),
        {"a", "set"},
        b"bytes",
        object(),
    ],
    ids=[
        "None", "str", "int", "float", "bool",
        "list", "tuple", "set", "bytes", "object",
    ],
)
def test_non_dict_input_raises(isolated_log, bad):
    """Calling with anything that is not a dict must raise TypeError
    (or a subclass thereof). Silent acceptance would let a list of dicts
    overwrite a single line per spec violation."""
    from standup import _append_entry
    with pytest.raises(TypeError):
        _append_entry(bad)


def test_non_dict_input_does_not_write(isolated_log):
    """A failing TypeError call must NOT have written anything."""
    from standup import _append_entry
    try:
        _append_entry("not a dict")
    except TypeError:
        pass
    # File either does not exist or is empty.
    if isolated_log.exists():
        assert isolated_log.read_bytes() == b"", (
            "rejected input still produced output; file must remain empty"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Non-JSON-serializable values must raise loudly
# --------------------------------------------------------------------------- #

def test_non_serializable_value_raises(isolated_log):
    """A dict containing a value json can't encode (e.g. datetime) must
    raise — the failure is loud, not a silent skip. We accept any
    Exception subtype here because json.dumps's default raises TypeError
    but a wrapping implementation may raise a custom error; the contract
    is "loud failure", not the specific class."""
    from standup import _append_entry
    bad = {"when": datetime.datetime(2026, 5, 8, 12, 0, 0)}
    with pytest.raises(Exception):
        _append_entry(bad)


def test_non_serializable_value_does_not_corrupt_log(isolated_log_existing):
    """If serialization fails, the existing log content must remain intact.
    A partial write (header bytes flushed before the exception) would
    corrupt the JSONL stream; the implementation must serialize fully
    before opening or writing, OR write atomically.
    """
    log_file, seed = isolated_log_existing
    before = log_file.read_bytes()

    from standup import _append_entry
    bad = {"when": datetime.datetime(2026, 5, 8, 12, 0, 0)}
    try:
        _append_entry(bad)
    except Exception:
        pass

    after = log_file.read_bytes()
    assert after == before, (
        "non-serializable input corrupted the existing log; "
        f"before={before!r} after={after!r}"
    )


def test_unsupported_object_raises(isolated_log):
    """An arbitrary class instance with no JSON encoding must raise."""
    class NotJsonable:
        pass

    from standup import _append_entry
    with pytest.raises(Exception):
        _append_entry({"x": NotJsonable()})


# --------------------------------------------------------------------------- #
# EDGE CASES — adversarial checks beyond the minimum criteria
# --------------------------------------------------------------------------- #

def test_empty_dict_writes_braces_and_newline(isolated_log):
    """An empty dict must serialize to exactly '{}\\n'."""
    from standup import _append_entry
    _append_entry({})
    assert isolated_log.read_bytes() == b"{}\n", (
        f"empty dict produced unexpected bytes: {isolated_log.read_bytes()!r}"
    )


def test_nested_structures_preserved(isolated_log):
    """Nested dicts and lists must round-trip exactly."""
    from standup import _append_entry
    entry = {
        "id": "abc",
        "tags": ["a", "b", "c"],
        "meta": {
            "depth": 3,
            "children": [{"i": 0}, {"i": 1, "kid": {"deep": True}}],
        },
        "n": 7,
    }
    _append_entry(entry)
    parsed = json.loads(isolated_log.read_text(encoding="utf-8").rstrip("\n"))
    assert parsed == entry


def test_no_extra_whitespace_around_line(isolated_log):
    """The written line must be the JSON encoding plus exactly one LF —
    no leading whitespace, no extra blank line."""
    from standup import _append_entry
    _append_entry({"k": "v"})

    raw = isolated_log.read_bytes()
    assert raw.startswith(b"{"), (
        f"line does not start with '{{'; raw={raw!r}"
    )
    # Exactly one trailing newline; no double newline.
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n"), (
        f"unexpected trailing whitespace; raw={raw!r}"
    )


def test_each_call_writes_exactly_one_newline(isolated_log):
    """Per call: the file must grow by exactly one extra LF byte."""
    from standup import _append_entry
    counts = []
    for i in range(4):
        _append_entry({"i": i})
        counts.append(isolated_log.read_bytes().count(b"\n"))
    assert counts == [1, 2, 3, 4], (
        f"newline counts after each append should be [1,2,3,4]; got {counts}"
    )


def test_long_entry_handled(isolated_log):
    """A reasonably large entry (≈ 100KB string) must be written as one
    line, no truncation, round-trip clean."""
    from standup import _append_entry
    big = {"blob": "x" * 100_000, "i": 1}
    _append_entry(big)

    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, "large entry produced more than one line"
    parsed = json.loads(text.rstrip("\n"))
    assert parsed == big


def test_special_string_values_preserved(isolated_log):
    """String values containing characters JSON must escape (newline,
    quote, backslash, tab) must round-trip — the helper must not split
    on embedded newlines."""
    from standup import _append_entry
    entry = {
        "newline": "line1\nline2",
        "quote": 'he said "hi"',
        "backslash": "a\\b",
        "tab": "col1\tcol2",
    }
    _append_entry(entry)

    text = isolated_log.read_text(encoding="utf-8")
    # Embedded \n in the value MUST be escaped in the JSON, so the file
    # must still have exactly one physical LF terminator.
    assert text.count("\n") == 1, (
        "embedded newline broke into multiple lines; "
        "json.dumps must have escaped it"
    )
    parsed = json.loads(text.rstrip("\n"))
    assert parsed == entry


def test_signature_takes_one_positional_param():
    """Adversarial: the function must take exactly one positional
    parameter (entry) and not silently accept *args/**kwargs."""
    import inspect
    from standup import _append_entry
    sig = inspect.signature(_append_entry)
    params = list(sig.parameters.values())
    assert len(params) == 1, (
        f"_append_entry must take exactly one parameter, got "
        f"{[p.name for p in params]}"
    )
    p = params[0]
    assert p.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), (
        f"_append_entry's parameter must be positional, got kind {p.kind}"
    )
