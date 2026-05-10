"""
Acceptance tests for Story 6 — Resilient line-by-line log reader.

Rolls up to PO v2 Requirements 1 (persistent log) and 14 (corrupt-log
resilience).

Verifies the private helper
``_read_entries() -> tuple[list[dict], list[tuple[int, str]]]`` in
``standup``:

  - importable as ``from standup import _read_entries``
  - NOT exported in ``standup.__all__`` (private, underscore-prefixed)
  - returns a tuple of (list, list) — entries (dicts) and skipped
    ((line_number, raw_line) tuples), in file order, line numbers
    1-indexed
  - missing log file -> ([], [])
  - empty log file  -> ([], [])
  - blank / whitespace-only lines silently skipped (NOT in entries
    OR skipped)
  - trailing newline tolerated
  - malformed JSON lines surfaced via ``warnings.warn`` AND included in
    the skipped list, never raised
  - clean log produces no warnings
  - UTF-8 decoded; unicode (chinese, emoji) preserved
  - binary garbage / undecodable bytes do not raise — they are surfaced
    as malformed lines or skipped with warning

Test isolation: every test monkeypatches ``standup.LOG_PATH`` to a
tmp_path file so the real ``Tools/Standup/log.jsonl`` is never touched.
Logs are built by writing strings/bytes directly — this story is
testable independently of Story 5's ``_append_entry``.

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import importlib
import json
import pathlib
import sys
import warnings

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
# Fixtures
#
# isolated_log:        path object pointing at a non-existent tmp file with
#                      LOG_PATH already monkeypatched to it.
# write_log:           helper that writes raw text to that path in UTF-8.
# write_log_bytes:     helper that writes raw bytes (for the binary-garbage
#                      edge case).
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Monkeypatch ``standup.LOG_PATH`` to a per-test tmp file.

    The file does NOT exist on entry — tests that need it absent get that
    behavior by default. Tests that need content present write it
    explicitly via ``write_log`` / ``write_log_bytes``.
    """
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file


@pytest.fixture
def write_log(isolated_log):
    """Return a helper that writes a UTF-8 string to ``isolated_log``."""
    def _write(text: str) -> pathlib.Path:
        isolated_log.write_text(text, encoding="utf-8")
        return isolated_log
    return _write


@pytest.fixture
def write_log_bytes(isolated_log):
    """Return a helper that writes raw bytes to ``isolated_log``.

    Used for the undecodable-bytes edge case where we need to bypass any
    encoding guard the test runner might apply.
    """
    def _write(data: bytes) -> pathlib.Path:
        isolated_log.write_bytes(data)
        return isolated_log
    return _write


# --------------------------------------------------------------------------- #
# CRITERION — _read_entries is importable from `standup`
# --------------------------------------------------------------------------- #

def test_read_entries_importable():
    """`from standup import _read_entries` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import _read_entries  # noqa: F401
    assert callable(_read_entries)


def test_read_entries_is_attribute_on_module():
    """The helper must live on the standup module (not a submodule)."""
    import standup
    assert hasattr(standup, "_read_entries"), (
        "standup module must define _read_entries"
    )
    assert callable(standup._read_entries)


# --------------------------------------------------------------------------- #
# CRITERION — _read_entries is NOT in __all__ (private)
# --------------------------------------------------------------------------- #

def test_read_entries_not_in_dunder_all():
    """Private helpers must not be re-exported via __all__."""
    import standup
    assert "_read_entries" not in standup.__all__, (
        "_read_entries must be private (excluded from __all__); "
        f"current __all__ = {standup.__all__}"
    )


def test_read_entries_name_is_underscore_prefixed():
    """Adversarial: even if a future refactor adds a public alias, no
    name in ``__all__`` may resolve to the same callable."""
    import standup
    target = getattr(standup, "_read_entries", object())
    for name in standup.__all__:
        obj = getattr(standup, name, None)
        if obj is target:
            pytest.fail(
                f"Public alias {name!r} exposes _read_entries; "
                "private helpers must not be re-exported"
            )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: zero required params, returns tuple of two lists
# --------------------------------------------------------------------------- #

def test_signature_takes_no_required_params():
    """``_read_entries`` must be callable with no arguments."""
    import inspect
    from standup import _read_entries
    sig = inspect.signature(_read_entries)
    for name, p in sig.parameters.items():
        assert p.default is not inspect.Parameter.empty or p.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"_read_entries should accept zero required args; "
            f"required param {name!r} is missing a default"
        )


def test_returns_tuple_of_two_lists(isolated_log):
    """The return must be ``tuple`` containing two ``list`` objects."""
    from standup import _read_entries
    result = _read_entries()
    assert isinstance(result, tuple), f"expected tuple, got {type(result)}"
    assert len(result) == 2, f"expected 2-tuple, got len={len(result)}"
    entries, skipped = result
    assert isinstance(entries, list), (
        f"first element must be list, got {type(entries)}"
    )
    assert isinstance(skipped, list), (
        f"second element must be list, got {type(skipped)}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — LOG_PATH does not exist  ->  ([], [])
# --------------------------------------------------------------------------- #

def test_missing_file_returns_empty_pair(isolated_log):
    """When LOG_PATH does not exist, return (empty list, empty list)."""
    assert not isolated_log.exists(), (
        "fixture invariant: log should not exist before the test acts"
    )
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == []
    assert skipped == []


def test_missing_file_emits_no_warning(isolated_log):
    """Absent file is not a degraded condition; warn() must not fire."""
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()
    assert caught == [], (
        f"expected no warnings on missing file, got {[str(w.message) for w in caught]}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Empty file  ->  ([], [])
# --------------------------------------------------------------------------- #

def test_empty_file_returns_empty_pair(write_log):
    """File exists but contains zero bytes -> ([], [])."""
    write_log("")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == []
    assert skipped == []


def test_empty_file_emits_no_warning(write_log):
    """Empty file is normal (e.g. fresh deployment); no warning."""
    write_log("")
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()
    assert caught == []


def test_only_newlines_file_returns_empty_pair(write_log):
    """A file containing only blank lines also yields empty results,
    because blank lines are silently skipped (not malformed)."""
    write_log("\n\n\n")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == []
    assert skipped == []


# --------------------------------------------------------------------------- #
# CRITERION — Single valid line
# --------------------------------------------------------------------------- #

def test_single_valid_line(write_log):
    """One JSON line -> entries=[parsed], skipped=[]."""
    entry = {"event": "open", "id": "abc", "n": 1}
    write_log(json.dumps(entry) + "\n")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [entry]
    assert skipped == []


def test_single_valid_line_no_trailing_newline(write_log):
    """Last line without trailing LF must still parse."""
    entry = {"event": "close"}
    write_log(json.dumps(entry))  # no trailing \n
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [entry]
    assert skipped == []


def test_single_valid_line_emits_no_warning(write_log):
    """Clean single-line log: no warnings."""
    write_log(json.dumps({"k": "v"}) + "\n")
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()
    assert caught == [], (
        f"clean log emitted warnings: {[str(w.message) for w in caught]}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Multiple valid lines preserve file order
# --------------------------------------------------------------------------- #

def test_multiple_valid_lines_in_order(write_log):
    """Lines must be returned in the exact order they appear on disk."""
    expected = [{"i": i, "tag": f"row-{i}"} for i in range(5)]
    payload = "".join(json.dumps(e) + "\n" for e in expected)
    write_log(payload)

    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == expected
    assert skipped == []


def test_many_valid_lines(write_log):
    """Stress: 100 valid lines preserved in order."""
    expected = [{"i": i} for i in range(100)]
    write_log("".join(json.dumps(e) + "\n" for e in expected))
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == expected
    assert skipped == []


def test_trailing_newline_does_not_create_phantom_entry(write_log):
    """A final '\\n' must NOT produce an extra empty entry or skipped line."""
    expected = [{"i": 0}, {"i": 1}]
    write_log(json.dumps(expected[0]) + "\n" + json.dumps(expected[1]) + "\n")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == expected
    assert skipped == []


# --------------------------------------------------------------------------- #
# CRITERION — Mixed valid + invalid: invalid surfaced in skipped only
# --------------------------------------------------------------------------- #

def test_one_valid_one_invalid(write_log):
    """One valid + one malformed line -> entries has the valid one,
    skipped has (line_number, raw_line) for the bad one."""
    valid = {"event": "open", "id": "abc"}
    payload = json.dumps(valid) + "\n" + "this is not json\n"
    write_log(payload)

    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # we test the warning separately
        entries, skipped = _read_entries()

    assert entries == [valid]
    assert len(skipped) == 1
    line_no, raw = skipped[0]
    assert line_no == 2, f"expected 1-indexed line 2, got {line_no}"
    # The raw line content should be preserved (trailing newline may or may
    # not be included; the spec only says "raw line" — we accept either).
    assert "this is not json" in raw


def test_invalid_then_valid_line_numbers_correct(write_log):
    """Bad line FIRST, good line second — line numbers and order preserved."""
    valid = {"ok": True}
    write_log("garbage line\n" + json.dumps(valid) + "\n")

    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entries, skipped = _read_entries()

    assert entries == [valid]
    assert len(skipped) == 1
    line_no, raw = skipped[0]
    assert line_no == 1, f"first physical line must be line 1, got {line_no}"
    assert "garbage" in raw


def test_multiple_invalid_lines_all_surfaced(write_log):
    """Every malformed line must appear in skipped, in file order."""
    write_log("not json 1\nnot json 2\nnot json 3\n")
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entries, skipped = _read_entries()

    assert entries == []
    assert len(skipped) == 3
    # Ordered, 1-indexed
    nums = [n for n, _raw in skipped]
    assert nums == [1, 2, 3], f"line numbers must be ordered 1,2,3 — got {nums}"
    for (n, raw), expected_text in zip(
        skipped, ["not json 1", "not json 2", "not json 3"]
    ):
        assert expected_text in raw, (
            f"raw line for entry {n} did not contain {expected_text!r}: {raw!r}"
        )


def test_alternating_valid_invalid_ordering(write_log):
    """Mixed: V, I, V, I, V — entries keep file order; skipped tracks bad
    line numbers separately and in order."""
    v0 = {"i": 0}
    v1 = {"i": 1}
    v2 = {"i": 2}
    payload = (
        json.dumps(v0) + "\n"      # line 1 valid
        + "BAD-A\n"                 # line 2 invalid
        + json.dumps(v1) + "\n"     # line 3 valid
        + "BAD-B\n"                 # line 4 invalid
        + json.dumps(v2) + "\n"     # line 5 valid
    )
    write_log(payload)

    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entries, skipped = _read_entries()

    assert entries == [v0, v1, v2], "valid entries must keep their file order"
    nums = [n for n, _ in skipped]
    raws = [raw for _, raw in skipped]
    assert nums == [2, 4], f"skipped line numbers wrong: {nums}"
    assert "BAD-A" in raws[0]
    assert "BAD-B" in raws[1]


# --------------------------------------------------------------------------- #
# CRITERION — Whitespace-only / blank lines silently skipped
# --------------------------------------------------------------------------- #

def test_blank_lines_silently_skipped(write_log):
    """Empty lines between valid lines must not appear anywhere."""
    a = {"i": 1}
    b = {"i": 2}
    write_log(json.dumps(a) + "\n\n" + json.dumps(b) + "\n")

    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [a, b]
    assert skipped == [], (
        f"blank line between entries must be silently skipped, not in "
        f"skipped list; got {skipped}"
    )


def test_whitespace_only_lines_silently_skipped(write_log):
    """A line that contains only spaces / tabs is blank — silent skip."""
    a = {"i": 1}
    b = {"i": 2}
    write_log(json.dumps(a) + "\n   \n\t\t\n" + json.dumps(b) + "\n")

    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [a, b]
    assert skipped == [], (
        f"whitespace-only lines must be silently skipped; got {skipped}"
    )


def test_blank_lines_emit_no_warning(write_log):
    """A log with valid lines + blanks must not warn — blanks are not
    a degraded condition."""
    write_log(json.dumps({"i": 1}) + "\n\n\n" + json.dumps({"i": 2}) + "\n")
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()
    assert caught == [], (
        f"blank lines triggered warnings: {[str(w.message) for w in caught]}"
    )


def test_leading_and_trailing_blanks(write_log):
    """Blank lines at top and bottom of file must not produce phantom
    entries or skipped tuples."""
    a = {"only": True}
    write_log("\n\n" + json.dumps(a) + "\n\n\n")

    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [a]
    assert skipped == []


# --------------------------------------------------------------------------- #
# CRITERION — Warning is emitted via warnings.warn when there are skipped
# lines; not emitted when log is clean
# --------------------------------------------------------------------------- #

def test_warning_emitted_when_lines_skipped(write_log):
    """At least one warning must be issued when malformed lines are
    encountered. Use ``pytest.warns`` to bind the contract to the public
    ``warnings`` API."""
    write_log("not json\n" + json.dumps({"ok": 1}) + "\n")
    from standup import _read_entries
    with pytest.warns(Warning):
        _read_entries()


def test_warning_message_mentions_count(write_log):
    """The warning text must name the count of skipped lines so the
    operator can size the damage at a glance."""
    write_log("bad1\nbad2\nbad3\n")
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()

    assert caught, "expected at least one warning when lines were skipped"
    combined = " ".join(str(w.message) for w in caught)
    # The count "3" must appear somewhere in the warning text.
    assert "3" in combined, (
        f"warning message must reference the count of skipped lines; "
        f"got {combined!r}"
    )


def test_warning_message_mentions_location(write_log):
    """The warning must reference an approximate location (line number)
    of skipped content — the spec wording is 'count and approximate
    location'. We require at least one 1-indexed bad line number to
    appear in the warning text."""
    # Bad lines are at lines 2 and 4.
    write_log(
        json.dumps({"i": 0}) + "\n"
        + "BAD\n"
        + json.dumps({"i": 1}) + "\n"
        + "ALSO BAD\n"
    )
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()

    combined = " ".join(str(w.message) for w in caught)
    assert ("2" in combined) or ("4" in combined), (
        f"warning text must reference an approximate line number "
        f"(2 or 4); got {combined!r}"
    )


def test_no_warning_when_log_is_clean(write_log):
    """A fully-valid log must not produce any warning."""
    write_log(
        json.dumps({"i": 0}) + "\n"
        + json.dumps({"i": 1}) + "\n"
        + json.dumps({"i": 2}) + "\n"
    )
    from standup import _read_entries
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _read_entries()
    assert caught == [], (
        f"clean log produced warnings: {[str(w.message) for w in caught]}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Never raises on malformed JSON content
# --------------------------------------------------------------------------- #

def test_never_raises_on_pure_garbage(write_log):
    """A log with NO valid lines at all must still return cleanly."""
    write_log("not json\n{broken\n[also bad\n")
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            entries, skipped = _read_entries()
        except Exception as e:  # pragma: no cover - failing assertion is the report
            pytest.fail(f"_read_entries raised on pure garbage input: {e!r}")

    assert entries == []
    assert len(skipped) == 3


def test_never_raises_on_partial_json(write_log):
    """Truncated / partial JSON must be classified as malformed, not
    raised."""
    # A truncated JSON object — clearly invalid as a complete value.
    write_log('{"event": "open", "id": "ab\n')
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entries, skipped = _read_entries()
    assert entries == []
    assert len(skipped) == 1


def test_never_raises_when_line_is_number_or_array(write_log):
    """Some implementations may want to reject non-dict JSON values too;
    others may accept them. The spec says ``entries`` is ``list[dict]``,
    so a top-level array or scalar should NOT appear in entries. Either
    classify as skipped or silently drop, but never raise."""
    write_log("[1,2,3]\n42\n\"a string\"\n")
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            entries, skipped = _read_entries()
        except Exception as e:  # pragma: no cover
            pytest.fail(
                f"_read_entries raised on non-dict JSON values: {e!r}"
            )
    # Whatever the implementation chooses, none of these belong in entries.
    for e in entries:
        assert isinstance(e, dict), (
            f"entries must contain only dicts; found {type(e).__name__}: {e!r}"
        )


# --------------------------------------------------------------------------- #
# CRITERION — UTF-8 decoding, unicode preserved
# --------------------------------------------------------------------------- #

def test_chinese_characters_preserved(write_log):
    """Non-ASCII text must round-trip exactly through the reader."""
    entry = {"note": "中文测试", "n": 1}
    write_log(json.dumps(entry, ensure_ascii=False) + "\n")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [entry]
    assert entries[0]["note"] == "中文测试"
    assert skipped == []


def test_emoji_preserved(write_log):
    """Emoji (4-byte UTF-8) must round-trip exactly."""
    entry = {"mood": "🔥💧✨", "ok": True}
    write_log(json.dumps(entry, ensure_ascii=False) + "\n")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [entry]
    assert entries[0]["mood"] == "🔥💧✨"
    assert skipped == []


def test_mixed_unicode_lines(write_log):
    """Multiple unicode lines preserve order and content."""
    expected = [
        {"latin": "café"},
        {"cyr": "Привет"},
        {"emoji": "🌊"},
    ]
    write_log("".join(
        json.dumps(e, ensure_ascii=False) + "\n" for e in expected
    ))
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == expected
    assert skipped == []


def test_ascii_escaped_unicode_also_works(write_log):
    """JSON with \\uXXXX escapes (ascii-only on disk) must decode to
    the same unicode characters as the non-escaped form."""
    entry = {"note": "中文"}
    # ensure_ascii=True produces \u escape sequences
    write_log(json.dumps(entry, ensure_ascii=True) + "\n")
    from standup import _read_entries
    entries, skipped = _read_entries()
    assert entries == [entry]
    assert entries[0]["note"] == "中文"
    assert skipped == []


# --------------------------------------------------------------------------- #
# EDGE CASE — undecodable bytes (binary garbage) handled gracefully
#
# The story says: "should also be handled gracefully (treat as malformed
# line, OR skip with warning; do NOT raise)". We assert non-raising
# behavior and let the implementation choose how to surface the damage.
# --------------------------------------------------------------------------- #

def test_binary_garbage_does_not_raise(write_log_bytes):
    """Bytes that are not valid UTF-8 must not raise out of _read_entries."""
    # 0xFF is invalid as the first byte of any UTF-8 sequence.
    write_log_bytes(b"\xff\xfe\x00\x00 not utf-8 \n")
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            _read_entries()
        except Exception as e:  # pragma: no cover
            pytest.fail(
                f"_read_entries raised on binary garbage: {e!r}; "
                "the contract is non-raising"
            )


def test_binary_garbage_then_valid_line_recovers(write_log_bytes):
    """A garbage prefix must NOT prevent a subsequent valid line from
    being parsed. The reader must continue past the damage."""
    valid = {"ok": True, "i": 99}
    payload = b"\xff\xfe garbage \n" + (json.dumps(valid) + "\n").encode("utf-8")
    write_log_bytes(payload)

    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            entries, skipped = _read_entries()
        except Exception as e:  # pragma: no cover
            pytest.fail(
                f"_read_entries raised on garbage-then-valid input: {e!r}"
            )

    # The valid entry must come through. Whether the garbage line shows up
    # in `skipped` or is silently dropped is implementation choice — the
    # story permits either behavior — but the valid entry MUST survive.
    assert valid in entries, (
        "valid line after binary garbage was lost; reader did not recover"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — line numbers stay 1-indexed even after blanks
# --------------------------------------------------------------------------- #

def test_line_numbers_count_blanks(write_log):
    """Line numbers in skipped must reflect *physical* line position in
    the file, including any blank lines that were silently skipped. A
    1-indexed line number is the number a human running ``cat -n`` would
    see for that line."""
    # line 1: blank
    # line 2: bad
    # line 3: valid
    write_log("\n" + "BAD\n" + json.dumps({"i": 1}) + "\n")
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        entries, skipped = _read_entries()

    assert entries == [{"i": 1}]
    assert len(skipped) == 1
    line_no, raw = skipped[0]
    assert line_no == 2, (
        f"line number must be physical 1-indexed (2), got {line_no}"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — repeated reads are stable / idempotent
# --------------------------------------------------------------------------- #

def test_repeated_reads_return_equal_results(write_log):
    """Calling _read_entries twice on the same file must yield equal
    results — the function must not mutate or rewrite the log."""
    expected = [{"i": 0}, {"i": 1}]
    write_log("".join(json.dumps(e) + "\n" for e in expected))

    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        a_entries, a_skipped = _read_entries()
        b_entries, b_skipped = _read_entries()

    assert a_entries == b_entries == expected
    assert a_skipped == b_skipped == []


def test_repeated_reads_do_not_mutate_file(write_log):
    """The file's bytes must be byte-equal before and after a read."""
    expected = [{"i": 0}, {"i": 1}]
    payload = "".join(json.dumps(e) + "\n" for e in expected)
    log_path = write_log(payload)
    before = log_path.read_bytes()

    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _read_entries()

    after = log_path.read_bytes()
    assert before == after, (
        "_read_entries mutated the log file; it must be read-only"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — skipped tuple shape: exactly (int, str)
# --------------------------------------------------------------------------- #

def test_skipped_entries_are_tuples_of_int_and_str(write_log):
    """Each element of the skipped list must be a 2-tuple of (int, str)."""
    write_log("BAD-A\nBAD-B\n")
    from standup import _read_entries
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _entries, skipped = _read_entries()

    assert len(skipped) == 2
    for item in skipped:
        assert isinstance(item, tuple), (
            f"skipped element must be tuple, got {type(item).__name__}: {item!r}"
        )
        assert len(item) == 2, (
            f"skipped element must be 2-tuple, got len={len(item)}: {item!r}"
        )
        line_no, raw = item
        assert isinstance(line_no, int), (
            f"line_no must be int, got {type(line_no).__name__}: {line_no!r}"
        )
        assert isinstance(raw, str), (
            f"raw must be str, got {type(raw).__name__}: {raw!r}"
        )
        assert line_no >= 1, (
            f"line numbers must be 1-indexed (>=1); got {line_no}"
        )
