"""
Acceptance tests for Story 9 — submit_open() public function.

Rolls up to PO v2 Requirements 3 (public API) and 4 (entry schema).

Verifies the public function

    submit_open(
        session_id: str,
        yesterday: str,
        today: str,
        blockers: str,
    ) -> dict

in ``standup``. submit_open is the public glue that:
  - constructs an "open" entry via _build_entry(type='open', session_id, fields)
  - persists it via _append_entry
  - returns the entry that was written so callers can verify / echo

Coverage:
  - submit_open is importable: ``from standup import submit_open``
  - submit_open is in standup.__all__ (public)
  - signature: 4 required positional parameters
    (session_id, yesterday, today, blockers); no varargs
  - valid call appends one entry to the log
  - returned dict equals the entry that was written (round-trip via
    _read_entries, matched by id)
  - returned entry has the open shape: id, session_id, type='open',
    timestamp, yesterday, today, blockers
  - returned entry's session_id equals the one passed
  - multiple calls each append one entry, in order
  - multiline string field values preserved verbatim (newlines kept
    via JSON escapes)
  - empty string field values allowed (e.g., blockers="")
  - empty session_id raises ValueError
  - non-string session_id raises ValueError or TypeError
  - non-string field values raise TypeError naming the offending field
    (delegated through _build_entry)
  - submit_open does not touch close_standup or history
    (their stubs still raise NotImplementedError)

Test isolation:
  - every test that touches the log monkeypatches ``standup.LOG_PATH``
    to a per-test ``tmp_path / "log.jsonl"`` so the real
    ``Tools/Standup/log.jsonl`` is never touched
  - log content is verified via ``standup._read_entries`` (the
    production reader) so writer/reader contracts stay aligned

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pathlib
import re
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


UUID4_HEX_RE = re.compile(r"^[0-9a-f]{32}$")
ISO_OFFSET_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$"
)


# --------------------------------------------------------------------------- #
# Fixture — redirect LOG_PATH to a per-test tmp file so the real log is
# never touched. Reload defensively so a previous test's monkeypatch
# doesn't leak.
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Monkeypatch ``standup.LOG_PATH`` to a tmp file for one test.

    Returns the path object so the test can read it back. The file does
    NOT exist on entry — exercising "first append creates the file" is
    a normal use of the helper.
    """
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file


def _read_log_entries():
    """Read the isolated log via the production ``_read_entries`` helper.

    Returns just the list of parsed dicts (drops the skipped list — these
    tests never expect skipped lines and a non-empty skipped list is a
    test failure).
    """
    import standup
    entries, skipped = standup._read_entries()
    assert skipped == [], (
        f"unexpected malformed lines in test log: {skipped!r}"
    )
    return entries


# --------------------------------------------------------------------------- #
# CRITERION — submit_open is importable from `standup`
# --------------------------------------------------------------------------- #

def test_submit_open_importable():
    """`from standup import submit_open` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import submit_open  # noqa: F401
    assert callable(submit_open)


def test_submit_open_is_attribute_on_module():
    """The function must live on the standup module."""
    import standup
    assert hasattr(standup, "submit_open"), (
        "standup module must define submit_open"
    )
    assert callable(standup.submit_open)


# --------------------------------------------------------------------------- #
# CRITERION — submit_open is in __all__ (public)
# --------------------------------------------------------------------------- #

def test_submit_open_in_dunder_all():
    """Public functions must be exported via __all__."""
    import standup
    assert "submit_open" in standup.__all__, (
        f"submit_open must be public (listed in __all__); "
        f"current __all__ = {standup.__all__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: 4 required positional parameters
# --------------------------------------------------------------------------- #

EXPECTED_PARAM_NAMES = ["session_id", "yesterday", "today", "blockers"]


def test_submit_open_signature_param_names():
    """Parameter names must match the spec exactly and in order."""
    from standup import submit_open
    sig = inspect.signature(submit_open)
    assert list(sig.parameters.keys()) == EXPECTED_PARAM_NAMES, (
        f"submit_open must accept parameters {EXPECTED_PARAM_NAMES}; "
        f"got {list(sig.parameters.keys())}"
    )


def test_submit_open_signature_param_count():
    """Exactly 4 parameters — no more, no less."""
    from standup import submit_open
    sig = inspect.signature(submit_open)
    assert len(sig.parameters) == 4, (
        f"submit_open must take 4 parameters; got {len(sig.parameters)}"
    )


def test_submit_open_all_params_required():
    """All 4 parameters must be required (no defaults)."""
    from standup import submit_open
    sig = inspect.signature(submit_open)
    for name, param in sig.parameters.items():
        assert param.default is inspect.Parameter.empty, (
            f"submit_open parameter {name!r} must be required "
            f"(no default); got default={param.default!r}"
        )


def test_submit_open_no_varargs_or_kwargs():
    """Adversarial: guard against ``def submit_open(*a, **kw)`` style stubs."""
    from standup import submit_open
    sig = inspect.signature(submit_open)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"submit_open must not accept *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_submit_open_params_are_positional():
    """Each parameter must be callable positionally (POSITIONAL_OR_KEYWORD
    or POSITIONAL_ONLY)."""
    from standup import submit_open
    sig = inspect.signature(submit_open)
    for name, param in sig.parameters.items():
        assert param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), (
            f"submit_open parameter {name!r} must be positional; "
            f"got kind {param.kind}"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Valid call appends one entry to the log
# --------------------------------------------------------------------------- #

def test_valid_call_appends_one_entry(isolated_log):
    """One submit_open call -> one entry in the log."""
    from standup import submit_open
    submit_open(
        session_id="sess-A" * 5 + "ab",  # arbitrary non-empty string
        yesterday="y",
        today="t",
        blockers="b",
    )
    entries = _read_log_entries()
    assert len(entries) == 1, (
        f"submit_open must append exactly one entry; got {len(entries)}"
    )


def test_valid_call_creates_log_when_absent(isolated_log):
    """If LOG_PATH does not exist, submit_open must create it (via
    _append_entry's append-mode open)."""
    assert not isolated_log.exists()
    from standup import submit_open
    submit_open("sid-12345", "y", "t", "b")
    assert isolated_log.is_file(), (
        "submit_open must create LOG_PATH on first write"
    )


def test_valid_call_returns_dict(isolated_log):
    """Return value must be a dict."""
    from standup import submit_open
    result = submit_open("sid-12345", "y", "t", "b")
    assert isinstance(result, dict), (
        f"submit_open must return a dict; got {type(result).__name__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Returned dict has the expected shape
# (id, session_id, type='open', timestamp, yesterday, today, blockers)
# --------------------------------------------------------------------------- #

EXPECTED_OPEN_KEYS = {
    "id",
    "session_id",
    "type",
    "timestamp",
    "yesterday",
    "today",
    "blockers",
}


def test_returned_entry_has_exact_open_shape(isolated_log):
    """Returned entry must have exactly the open-type keys; no extras,
    no omissions."""
    from standup import submit_open
    result = submit_open("sid-shape", "y", "t", "b")
    assert set(result.keys()) == EXPECTED_OPEN_KEYS, (
        f"submit_open return must have exactly {EXPECTED_OPEN_KEYS}; "
        f"got {set(result.keys())}"
    )


def test_returned_entry_type_is_open(isolated_log):
    """Returned entry's ``type`` field must be the string 'open'."""
    from standup import submit_open
    result = submit_open("sid-type", "y", "t", "b")
    assert result["type"] == "open", (
        f"submit_open must build entries with type='open'; "
        f"got type={result['type']!r}"
    )


def test_returned_entry_session_id_matches_input(isolated_log):
    """Returned entry's session_id must equal the value passed in."""
    from standup import submit_open
    sid = "session-id-xyz-987"
    result = submit_open(sid, "y", "t", "b")
    assert result["session_id"] == sid, (
        f"submit_open must preserve session_id; "
        f"passed {sid!r}, got {result['session_id']!r}"
    )


def test_returned_entry_yesterday_matches_input(isolated_log):
    """Returned entry's yesterday field must equal the value passed in."""
    from standup import submit_open
    y = "yesterday content"
    result = submit_open("sid", y, "t", "b")
    assert result["yesterday"] == y


def test_returned_entry_today_matches_input(isolated_log):
    """Returned entry's today field must equal the value passed in."""
    from standup import submit_open
    t = "today content"
    result = submit_open("sid", "y", t, "b")
    assert result["today"] == t


def test_returned_entry_blockers_matches_input(isolated_log):
    """Returned entry's blockers field must equal the value passed in."""
    from standup import submit_open
    b = "blocker content"
    result = submit_open("sid", "y", "t", b)
    assert result["blockers"] == b


def test_returned_entry_id_is_uuid4_hex(isolated_log):
    """Returned entry's id field must be 32-char lowercase hex (uuid4)."""
    from standup import submit_open
    result = submit_open("sid", "y", "t", "b")
    assert isinstance(result["id"], str)
    assert UUID4_HEX_RE.match(result["id"]), (
        f"id must be 32-char lowercase hex; got {result['id']!r}"
    )


def test_returned_entry_timestamp_is_iso_with_offset(isolated_log):
    """Returned entry's timestamp must be an ISO 8601 string with a
    timezone offset (matches ``_now_iso`` output)."""
    from standup import submit_open
    result = submit_open("sid", "y", "t", "b")
    ts = result["timestamp"]
    assert isinstance(ts, str)
    assert ISO_OFFSET_RE.match(ts), (
        f"timestamp must be ISO 8601 with [+-]HH:MM offset; got {ts!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Round-trip: returned dict equals the entry that was written
# (read back via _read_entries, matched by id)
# --------------------------------------------------------------------------- #

def test_returned_entry_equals_written_entry_round_trip(isolated_log):
    """The dict submit_open returns must equal the dict that lands on
    disk — confirmed by reading the log back via the production reader
    and matching by id."""
    from standup import submit_open
    returned = submit_open(
        session_id="rt-session",
        yesterday="rt-y",
        today="rt-t",
        blockers="rt-b",
    )
    entries = _read_log_entries()
    assert len(entries) == 1
    on_disk = entries[0]
    # Match by id — even if extra entries existed, the round-trip would
    # still locate the correct one.
    assert on_disk["id"] == returned["id"], (
        f"id mismatch between returned and written entry; "
        f"returned={returned['id']!r}, on_disk={on_disk['id']!r}"
    )
    assert on_disk == returned, (
        f"submit_open's return value must equal the entry written to "
        f"disk; returned={returned!r}, on_disk={on_disk!r}"
    )


def test_returned_entry_round_trips_through_json(isolated_log):
    """Defensive: the on-disk JSON line, parsed independently, equals
    submit_open's returned dict."""
    from standup import submit_open
    returned = submit_open("sid-jrt", "y", "t", "b")
    raw = isolated_log.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(raw)
    assert parsed == returned


# --------------------------------------------------------------------------- #
# CRITERION — Multiple calls append in order, one entry each
# --------------------------------------------------------------------------- #

def test_multiple_calls_append_in_order(isolated_log):
    """Three calls -> three entries, file order matches call order."""
    from standup import submit_open
    r1 = submit_open("sid-1", "y1", "t1", "b1")
    r2 = submit_open("sid-2", "y2", "t2", "b2")
    r3 = submit_open("sid-3", "y3", "t3", "b3")

    entries = _read_log_entries()
    assert len(entries) == 3, (
        f"expected 3 entries after 3 calls; got {len(entries)}"
    )
    assert entries[0] == r1
    assert entries[1] == r2
    assert entries[2] == r3


def test_multiple_calls_each_have_unique_id(isolated_log):
    """Each entry must get its own fresh id."""
    from standup import submit_open
    ids = [
        submit_open(f"sid-{i}", "y", "t", "b")["id"]
        for i in range(5)
    ]
    assert len(set(ids)) == 5, (
        f"submit_open must mint a fresh id per call; "
        f"got {len(set(ids))} unique ids across 5 calls: {ids}"
    )


def test_multiple_calls_preserve_distinct_session_ids(isolated_log):
    """Different session_ids passed in must surface as different
    session_ids on disk (no caching)."""
    from standup import submit_open
    submit_open("session-A", "y", "t", "b")
    submit_open("session-B", "y", "t", "b")
    entries = _read_log_entries()
    assert [e["session_id"] for e in entries] == ["session-A", "session-B"]


# --------------------------------------------------------------------------- #
# CRITERION — Multiline string values preserved verbatim
# (newlines kept via JSON escapes; entry remains one physical line)
# --------------------------------------------------------------------------- #

def test_multiline_yesterday_preserved(isolated_log):
    """yesterday field with embedded newlines must round-trip exactly,
    and the log entry must remain one physical line."""
    from standup import submit_open
    multi = "line one\nline two\n  indented line three"
    returned = submit_open("sid-multi-y", multi, "t", "b")

    # Disk: exactly one physical line (newlines escaped as \n inside JSON).
    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, (
        f"multiline field must produce exactly one physical line on disk; "
        f"got {text.count(chr(10))} newlines"
    )

    entries = _read_log_entries()
    assert entries[0]["yesterday"] == multi
    assert returned["yesterday"] == multi


def test_multiline_today_preserved(isolated_log):
    """today field with embedded newlines must round-trip exactly."""
    from standup import submit_open
    multi = "first task\nsecond task\nthird task"
    returned = submit_open("sid-multi-t", "y", multi, "b")
    entries = _read_log_entries()
    assert entries[0]["today"] == multi
    assert returned["today"] == multi


def test_multiline_blockers_preserved(isolated_log):
    """blockers field with embedded newlines must round-trip exactly."""
    from standup import submit_open
    multi = "blocker one\n  - sub a\n  - sub b\nblocker two"
    returned = submit_open("sid-multi-b", "y", "t", multi)
    entries = _read_log_entries()
    assert entries[0]["blockers"] == multi
    assert returned["blockers"] == multi


def test_all_three_multiline_fields_simultaneously(isolated_log):
    """All three field values multiline at once — no bleed, all round-trip,
    one physical line on disk."""
    from standup import submit_open
    y = "y1\ny2\ny3"
    t = "t1\nt2"
    b = "b1\nb2\nb3\nb4"
    returned = submit_open("sid-all-multi", y, t, b)

    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, (
        "embedded newlines must be JSON-escaped, not split into lines; "
        f"got {text.count(chr(10))} physical newlines"
    )

    entries = _read_log_entries()
    e = entries[0]
    assert e["yesterday"] == y
    assert e["today"] == t
    assert e["blockers"] == b
    assert returned == e


def test_special_chars_in_field_values_preserved(isolated_log):
    """JSON-significant characters (quote, backslash, tab, CR) must
    round-trip without breaking the line."""
    from standup import submit_open
    y = 'has "quotes" and \\ backslashes'
    t = "has\ttabs\tand\rcarriage returns"
    b = 'mix\n"quote"\n\\backslash\n\ttab'
    returned = submit_open("sid-special", y, t, b)

    entries = _read_log_entries()
    assert entries[0]["yesterday"] == y
    assert entries[0]["today"] == t
    assert entries[0]["blockers"] == b
    assert returned == entries[0]


# --------------------------------------------------------------------------- #
# CRITERION — Empty string field values are allowed
# --------------------------------------------------------------------------- #

def test_empty_blockers_allowed(isolated_log):
    """blockers='' is allowed (the common 'no blockers today' case)."""
    from standup import submit_open
    returned = submit_open("sid-empty-b", "y", "t", "")
    assert returned["blockers"] == ""
    entries = _read_log_entries()
    assert entries[0]["blockers"] == ""


def test_empty_yesterday_allowed(isolated_log):
    """yesterday='' is allowed (e.g., first day on a project)."""
    from standup import submit_open
    returned = submit_open("sid-empty-y", "", "t", "b")
    assert returned["yesterday"] == ""
    entries = _read_log_entries()
    assert entries[0]["yesterday"] == ""


def test_empty_today_allowed(isolated_log):
    """today='' is allowed."""
    from standup import submit_open
    returned = submit_open("sid-empty-t", "y", "", "b")
    assert returned["today"] == ""
    entries = _read_log_entries()
    assert entries[0]["today"] == ""


def test_all_empty_field_values_allowed(isolated_log):
    """All three field values empty simultaneously — still a valid call."""
    from standup import submit_open
    returned = submit_open("sid-all-empty", "", "", "")
    assert returned["yesterday"] == ""
    assert returned["today"] == ""
    assert returned["blockers"] == ""
    entries = _read_log_entries()
    assert entries[0] == returned


# --------------------------------------------------------------------------- #
# CRITERION — Empty session_id raises ValueError
# (architect's session pairing invariant)
# --------------------------------------------------------------------------- #

def test_empty_session_id_raises_value_error(isolated_log):
    """session_id='' must raise ValueError (empty session breaks the
    open/close pairing invariant)."""
    from standup import submit_open
    with pytest.raises(ValueError):
        submit_open("", "y", "t", "b")


def test_empty_session_id_does_not_write(isolated_log):
    """A failed-validation call must not have written anything."""
    from standup import submit_open
    try:
        submit_open("", "y", "t", "b")
    except ValueError:
        pass
    # Either the file does not exist or it is empty.
    if isolated_log.exists():
        assert isolated_log.read_bytes() == b"", (
            "rejected empty session_id still produced output; "
            "validation must run before any write"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Non-string session_id raises ValueError or TypeError
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad",
    [None, 42, 3.14, True, [], {}, b"bytes", ("tup",)],
    ids=["None", "int", "float", "bool", "list", "dict", "bytes", "tuple"],
)
def test_non_string_session_id_raises(isolated_log, bad):
    """session_id must be a str. Non-string values must raise loudly —
    either ValueError or TypeError is acceptable per the spec."""
    from standup import submit_open
    with pytest.raises((ValueError, TypeError)):
        submit_open(bad, "y", "t", "b")


def test_non_string_session_id_does_not_write(isolated_log):
    """A failed-validation call must not have written anything."""
    from standup import submit_open
    try:
        submit_open(42, "y", "t", "b")  # type: ignore[arg-type]
    except (ValueError, TypeError):
        pass
    if isolated_log.exists():
        assert isolated_log.read_bytes() == b"", (
            "rejected non-string session_id still produced output"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Non-string field values raise TypeError naming the field
# (delegated through _build_entry per Story 4 contract)
# --------------------------------------------------------------------------- #

def test_non_string_yesterday_raises_type_error(isolated_log):
    """Non-string yesterday must raise TypeError. The error message must
    name 'yesterday' so the operator can fix the offending field."""
    from standup import submit_open
    with pytest.raises(TypeError) as exc_info:
        submit_open("sid", 42, "t", "b")  # type: ignore[arg-type]
    assert "yesterday" in str(exc_info.value), (
        f"TypeError must name the offending field 'yesterday'; "
        f"got message: {exc_info.value!s}"
    )


def test_non_string_today_raises_type_error(isolated_log):
    """Non-string today must raise TypeError naming 'today'."""
    from standup import submit_open
    with pytest.raises(TypeError) as exc_info:
        submit_open("sid", "y", 99, "b")  # type: ignore[arg-type]
    assert "today" in str(exc_info.value), (
        f"TypeError must name the offending field 'today'; "
        f"got message: {exc_info.value!s}"
    )


def test_non_string_blockers_raises_type_error(isolated_log):
    """Non-string blockers must raise TypeError naming 'blockers'."""
    from standup import submit_open
    with pytest.raises(TypeError) as exc_info:
        submit_open("sid", "y", "t", ["b"])  # type: ignore[arg-type]
    assert "blockers" in str(exc_info.value), (
        f"TypeError must name the offending field 'blockers'; "
        f"got message: {exc_info.value!s}"
    )


@pytest.mark.parametrize(
    "field_name,values",
    [
        ("yesterday", (None, "t", "b")),
        ("yesterday", (123, "t", "b")),
        ("yesterday", ([], "t", "b")),
        ("today", ("y", None, "b")),
        ("today", ("y", 3.14, "b")),
        ("today", ("y", {}, "b")),
        ("blockers", ("y", "t", None)),
        ("blockers", ("y", "t", 0)),
        ("blockers", ("y", "t", b"bytes")),
    ],
    ids=[
        "yesterday-None", "yesterday-int", "yesterday-list",
        "today-None", "today-float", "today-dict",
        "blockers-None", "blockers-int", "blockers-bytes",
    ],
)
def test_non_string_field_value_raises_type_error_naming_field(
    isolated_log, field_name, values
):
    """Adversarial parametrized: every non-string field value raises
    TypeError, and the message names the offending field."""
    from standup import submit_open
    with pytest.raises(TypeError) as exc_info:
        submit_open("sid", *values)  # type: ignore[arg-type]
    assert field_name in str(exc_info.value), (
        f"TypeError for non-string {field_name} value must name the "
        f"field in its message; got: {exc_info.value!s}"
    )


def test_non_string_field_does_not_write(isolated_log):
    """A failed-validation call (non-string field value) must not have
    written anything."""
    from standup import submit_open
    try:
        submit_open("sid", "y", 42, "b")  # type: ignore[arg-type]
    except TypeError:
        pass
    if isolated_log.exists():
        assert isolated_log.read_bytes() == b"", (
            "rejected non-string field still produced output; "
            "validation must run before any write"
        )


# --------------------------------------------------------------------------- #
# CRITERION — submit_open does not touch close_standup or history
# --------------------------------------------------------------------------- #

# NOTE: test_submit_open_does_not_implement_close_standup was removed
# in Story 10. Story 9 pinned the cross-story isolation by asserting
# close_standup remained a NotImplementedError stub after a submit_open
# call; Story 10 replaces that stub with a working implementation
# (signature also widens from 1 arg to 4), so the stub-state assertion
# no longer reflects the contract for close_standup. The Story-10
# acceptance tests in test_close_standup.py now own that surface, and
# test_open_then_close_produces_two_entries_in_order in particular
# pins the open + close interleave that this test was guarding.


# NOTE: test_submit_open_does_not_implement_history was removed in
# Story 12. Story 9 pinned the cross-story isolation by asserting
# history remained a NotImplementedError stub after a submit_open
# call; Story 12 replaces that stub with a working implementation,
# so the stub-state assertion no longer reflects the contract for
# history. The Story-12 acceptance tests in test_history.py now own
# that surface, and test_history_renders_submit_open_built_entries
# in particular pins the submit_open + history integration that
# this test was guarding.


# --------------------------------------------------------------------------- #
# EDGE CASE — submit_open returns a fresh dict per call (no shared state)
# --------------------------------------------------------------------------- #

def test_returned_dict_is_distinct_per_call(isolated_log):
    """Two calls must return distinct dict objects."""
    from standup import submit_open
    a = submit_open("sid-a", "y", "t", "b")
    b = submit_open("sid-b", "y", "t", "b")
    assert a is not b, (
        "submit_open must return a fresh dict per call; "
        "returning a shared/cached reference is unsafe"
    )


def test_mutating_returned_dict_does_not_affect_log(isolated_log):
    """Mutating the returned dict after the call must not change what
    is on disk (defensive against shared references)."""
    from standup import submit_open
    returned = submit_open("sid-mut", "y", "t", "b")
    bytes_before = isolated_log.read_bytes()
    returned["yesterday"] = "MUTATED"
    returned["new_key"] = "should not appear"
    bytes_after = isolated_log.read_bytes()
    assert bytes_before == bytes_after, (
        "mutating submit_open's return value must not change the log"
    )

    # And the on-disk record still has the original values.
    entries = _read_log_entries()
    assert entries[0]["yesterday"] == "y"
    assert "new_key" not in entries[0]


# --------------------------------------------------------------------------- #
# EDGE CASE — submit_open uses _build_entry + _append_entry as glue
# (the two helpers are the canonical path; this test traces calls)
# --------------------------------------------------------------------------- #

def test_submit_open_routes_through_build_and_append(isolated_log, monkeypatch):
    """submit_open must delegate construction to _build_entry and
    persistence to _append_entry — not reimplement the schema or write
    bytes directly."""
    import standup

    build_calls: list[dict] = []
    append_calls: list[dict] = []

    real_build = standup._build_entry
    real_append = standup._append_entry

    def tracking_build(type, session_id, fields, amends_id=None):
        build_calls.append(
            {"type": type, "session_id": session_id, "fields": dict(fields),
             "amends_id": amends_id}
        )
        return real_build(type, session_id, fields, amends_id)

    def tracking_append(entry):
        append_calls.append(dict(entry))
        return real_append(entry)

    monkeypatch.setattr(standup, "_build_entry", tracking_build)
    monkeypatch.setattr(standup, "_append_entry", tracking_append)

    standup.submit_open("sid-glue", "y", "t", "b")

    assert len(build_calls) == 1, (
        f"submit_open must call _build_entry exactly once per submission; "
        f"got {len(build_calls)} calls"
    )
    assert len(append_calls) == 1, (
        f"submit_open must call _append_entry exactly once per submission; "
        f"got {len(append_calls)} calls"
    )
    # And _build_entry was called with the right shape.
    bc = build_calls[0]
    assert bc["type"] == "open", (
        f"_build_entry must be called with type='open'; got {bc['type']!r}"
    )
    assert bc["session_id"] == "sid-glue"
    assert bc["fields"] == {"yesterday": "y", "today": "t", "blockers": "b"}
    assert bc["amends_id"] is None, (
        "submit_open must not pass amends_id; that is the amend flow's job"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Long content tolerated
# --------------------------------------------------------------------------- #

def test_long_field_values_round_trip(isolated_log):
    """A reasonably large freeform field (~50KB) round-trips on one
    physical line."""
    from standup import submit_open
    big = "x" * 50_000
    returned = submit_open("sid-big", big, "t", "b")

    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, "large field produced more than one line"
    entries = _read_log_entries()
    assert entries[0]["yesterday"] == big
    assert returned["yesterday"] == big


# --------------------------------------------------------------------------- #
# EDGE CASE — Unicode in field values preserved
# --------------------------------------------------------------------------- #

def test_unicode_field_values_preserved(isolated_log):
    """Non-ASCII content (Chinese, Cyrillic, emoji) round-trips exactly."""
    from standup import submit_open
    y = "中文测试 — yesterday"
    t = "Привет — today"
    b = "🔥 blockers ✨"
    returned = submit_open("sid-unicode", y, t, b)

    entries = _read_log_entries()
    assert entries[0]["yesterday"] == y
    assert entries[0]["today"] == t
    assert entries[0]["blockers"] == b
    assert returned == entries[0]
