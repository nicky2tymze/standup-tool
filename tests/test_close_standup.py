"""
Acceptance tests for Story 10 — close_standup() public function.

Rolls up to PO v2 Requirements 3 (public API), 4 (entry schema),
9 (session identity), and 10 (no orphan recovery).

Verifies the public function

    close_standup(
        session_id: str,
        shifted: str,
        tomorrows_first_move: str,
        blocking: str,
    ) -> dict

in ``standup``. close_standup is the public glue that:
  - constructs a "close" entry via _build_entry(type='close', session_id, fields)
  - persists it via _append_entry
  - returns the entry that was written so callers can verify / echo

Story 10 changes Story 1's stub in two ways simultaneously:
  - signature widens from (session_id) -> dict to
    (session_id, shifted, tomorrows_first_move, blocking) -> dict
  - body changes from raising NotImplementedError to a working impl

Per PO v2 Req 10 ("no orphan recovery"), close_standup does NOT enforce
the existence of a matching open entry — it writes the close entry
regardless of session_id pairing, and does NOT enforce one-close-per-
session uniqueness.

Coverage:
  - close_standup is importable: ``from standup import close_standup``
  - close_standup is in standup.__all__ (public)
  - close_standup no longer raises NotImplementedError
  - signature: 4 required positional parameters
    (session_id, shifted, tomorrows_first_move, blocking); no varargs
  - valid call appends one entry to the log
  - returned dict equals the entry that was written (round-trip via
    _read_entries, matched by id)
  - returned entry has the close shape: id, session_id, type='close',
    timestamp, shifted, tomorrows_first_move, blocking (NO amends_id)
  - returned entry's session_id equals the one passed
  - multiple calls each append one entry, in order
  - multiline string field values preserved verbatim (newlines kept
    via JSON escapes)
  - empty string field values allowed (e.g., blocking="")
  - empty session_id raises ValueError
  - non-string session_id raises ValueError or TypeError
  - non-string field values raise TypeError naming the offending field
    (delegated through _build_entry)
  - NO orphan check: close_standup with a session_id that has no
    matching open entry writes the close entry anyway
  - NO one-close-per-session check: a second close_standup call with
    the same session_id as a prior close still writes
  - close_standup uses _build_entry + _append_entry as the canonical
    glue (call tracing)
  - validation failure does not write
  - returned dict equals on-disk entry

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
# CRITERION — close_standup is importable from `standup`
# --------------------------------------------------------------------------- #

def test_close_standup_importable():
    """`from standup import close_standup` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import close_standup  # noqa: F401
    assert callable(close_standup)


def test_close_standup_is_attribute_on_module():
    """The function must live on the standup module."""
    import standup
    assert hasattr(standup, "close_standup"), (
        "standup module must define close_standup"
    )
    assert callable(standup.close_standup)


# --------------------------------------------------------------------------- #
# CRITERION — close_standup is in __all__ (public)
# --------------------------------------------------------------------------- #

def test_close_standup_in_dunder_all():
    """Public functions must be exported via __all__."""
    import standup
    assert "close_standup" in standup.__all__, (
        f"close_standup must be public (listed in __all__); "
        f"current __all__ = {standup.__all__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — close_standup no longer raises NotImplementedError
# (Story 10 replaces the Story-1 stub with a working implementation)
# --------------------------------------------------------------------------- #

def test_close_standup_no_longer_raises_not_implemented(isolated_log):
    """A valid call must not raise NotImplementedError. Story 10 retires
    the Story-1 stub state; this test pins the transition."""
    from standup import close_standup
    try:
        close_standup("sid-no-stub", "s", "tfm", "bl")
    except NotImplementedError as exc:
        pytest.fail(
            "close_standup must no longer raise NotImplementedError "
            f"after Story 10; got: {exc!r}"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: 4 required positional parameters
# --------------------------------------------------------------------------- #

EXPECTED_PARAM_NAMES = [
    "session_id",
    "shifted",
    "tomorrows_first_move",
    "blocking",
]


def test_close_standup_signature_param_names():
    """Parameter names must match the spec exactly and in order."""
    from standup import close_standup
    sig = inspect.signature(close_standup)
    assert list(sig.parameters.keys()) == EXPECTED_PARAM_NAMES, (
        f"close_standup must accept parameters {EXPECTED_PARAM_NAMES}; "
        f"got {list(sig.parameters.keys())}"
    )


def test_close_standup_signature_param_count():
    """Exactly 4 parameters — no more, no less."""
    from standup import close_standup
    sig = inspect.signature(close_standup)
    assert len(sig.parameters) == 4, (
        f"close_standup must take 4 parameters; got {len(sig.parameters)}"
    )


def test_close_standup_all_params_required():
    """All 4 parameters must be required (no defaults)."""
    from standup import close_standup
    sig = inspect.signature(close_standup)
    for name, param in sig.parameters.items():
        assert param.default is inspect.Parameter.empty, (
            f"close_standup parameter {name!r} must be required "
            f"(no default); got default={param.default!r}"
        )


def test_close_standup_no_varargs_or_kwargs():
    """Adversarial: guard against ``def close_standup(*a, **kw)`` style stubs."""
    from standup import close_standup
    sig = inspect.signature(close_standup)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"close_standup must not accept *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_close_standup_params_are_positional():
    """Each parameter must be callable positionally (POSITIONAL_OR_KEYWORD
    or POSITIONAL_ONLY)."""
    from standup import close_standup
    sig = inspect.signature(close_standup)
    for name, param in sig.parameters.items():
        assert param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), (
            f"close_standup parameter {name!r} must be positional; "
            f"got kind {param.kind}"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Valid call appends one entry to the log
# --------------------------------------------------------------------------- #

def test_valid_call_appends_one_entry(isolated_log):
    """One close_standup call -> one entry in the log."""
    from standup import close_standup
    close_standup(
        session_id="sess-A" * 5 + "ab",  # arbitrary non-empty string
        shifted="s",
        tomorrows_first_move="tfm",
        blocking="bl",
    )
    entries = _read_log_entries()
    assert len(entries) == 1, (
        f"close_standup must append exactly one entry; got {len(entries)}"
    )


def test_valid_call_creates_log_when_absent(isolated_log):
    """If LOG_PATH does not exist, close_standup must create it (via
    _append_entry's append-mode open)."""
    assert not isolated_log.exists()
    from standup import close_standup
    close_standup("sid-12345", "s", "tfm", "bl")
    assert isolated_log.is_file(), (
        "close_standup must create LOG_PATH on first write"
    )


def test_valid_call_returns_dict(isolated_log):
    """Return value must be a dict."""
    from standup import close_standup
    result = close_standup("sid-12345", "s", "tfm", "bl")
    assert isinstance(result, dict), (
        f"close_standup must return a dict; got {type(result).__name__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Returned dict has the expected close shape
# (id, session_id, type='close', timestamp, shifted, tomorrows_first_move,
#  blocking — NO amends_id)
# --------------------------------------------------------------------------- #

EXPECTED_CLOSE_KEYS = {
    "id",
    "session_id",
    "type",
    "timestamp",
    "shifted",
    "tomorrows_first_move",
    "blocking",
}


def test_returned_entry_has_exact_close_shape(isolated_log):
    """Returned entry must have exactly the close-type keys; no extras,
    no omissions."""
    from standup import close_standup
    result = close_standup("sid-shape", "s", "tfm", "bl")
    assert set(result.keys()) == EXPECTED_CLOSE_KEYS, (
        f"close_standup return must have exactly {EXPECTED_CLOSE_KEYS}; "
        f"got {set(result.keys())}"
    )


def test_returned_entry_has_no_amends_id(isolated_log):
    """Close entries must NOT carry an amends_id key — that key belongs
    to amend entries only."""
    from standup import close_standup
    result = close_standup("sid-no-amends", "s", "tfm", "bl")
    assert "amends_id" not in result, (
        "close entries must not include amends_id; got "
        f"amends_id={result.get('amends_id')!r}"
    )


def test_returned_entry_type_is_close(isolated_log):
    """Returned entry's ``type`` field must be the string 'close'."""
    from standup import close_standup
    result = close_standup("sid-type", "s", "tfm", "bl")
    assert result["type"] == "close", (
        f"close_standup must build entries with type='close'; "
        f"got type={result['type']!r}"
    )


def test_returned_entry_session_id_matches_input(isolated_log):
    """Returned entry's session_id must equal the value passed in."""
    from standup import close_standup
    sid = "session-id-xyz-987"
    result = close_standup(sid, "s", "tfm", "bl")
    assert result["session_id"] == sid, (
        f"close_standup must preserve session_id; "
        f"passed {sid!r}, got {result['session_id']!r}"
    )


def test_returned_entry_shifted_matches_input(isolated_log):
    """Returned entry's shifted field must equal the value passed in."""
    from standup import close_standup
    s = "shifted content"
    result = close_standup("sid", s, "tfm", "bl")
    assert result["shifted"] == s


def test_returned_entry_tomorrows_first_move_matches_input(isolated_log):
    """Returned entry's tomorrows_first_move field must equal the value
    passed in."""
    from standup import close_standup
    tfm = "tomorrow's first move content"
    result = close_standup("sid", "s", tfm, "bl")
    assert result["tomorrows_first_move"] == tfm


def test_returned_entry_blocking_matches_input(isolated_log):
    """Returned entry's blocking field must equal the value passed in."""
    from standup import close_standup
    bl = "blocking content"
    result = close_standup("sid", "s", "tfm", bl)
    assert result["blocking"] == bl


def test_returned_entry_id_is_uuid4_hex(isolated_log):
    """Returned entry's id field must be 32-char lowercase hex (uuid4)."""
    from standup import close_standup
    result = close_standup("sid", "s", "tfm", "bl")
    assert isinstance(result["id"], str)
    assert UUID4_HEX_RE.match(result["id"]), (
        f"id must be 32-char lowercase hex; got {result['id']!r}"
    )


def test_returned_entry_timestamp_is_iso_with_offset(isolated_log):
    """Returned entry's timestamp must be an ISO 8601 string with a
    timezone offset (matches ``_now_iso`` output)."""
    from standup import close_standup
    result = close_standup("sid", "s", "tfm", "bl")
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
    """The dict close_standup returns must equal the dict that lands on
    disk — confirmed by reading the log back via the production reader
    and matching by id."""
    from standup import close_standup
    returned = close_standup(
        session_id="rt-session",
        shifted="rt-s",
        tomorrows_first_move="rt-tfm",
        blocking="rt-bl",
    )
    entries = _read_log_entries()
    assert len(entries) == 1
    on_disk = entries[0]
    assert on_disk["id"] == returned["id"], (
        f"id mismatch between returned and written entry; "
        f"returned={returned['id']!r}, on_disk={on_disk['id']!r}"
    )
    assert on_disk == returned, (
        f"close_standup's return value must equal the entry written to "
        f"disk; returned={returned!r}, on_disk={on_disk!r}"
    )


def test_returned_entry_round_trips_through_json(isolated_log):
    """Defensive: the on-disk JSON line, parsed independently, equals
    close_standup's returned dict."""
    from standup import close_standup
    returned = close_standup("sid-jrt", "s", "tfm", "bl")
    raw = isolated_log.read_text(encoding="utf-8").rstrip("\n")
    parsed = json.loads(raw)
    assert parsed == returned


# --------------------------------------------------------------------------- #
# CRITERION — Multiple calls append in order, one entry each
# --------------------------------------------------------------------------- #

def test_multiple_calls_append_in_order(isolated_log):
    """Three calls -> three entries, file order matches call order."""
    from standup import close_standup
    r1 = close_standup("sid-1", "s1", "tfm1", "bl1")
    r2 = close_standup("sid-2", "s2", "tfm2", "bl2")
    r3 = close_standup("sid-3", "s3", "tfm3", "bl3")

    entries = _read_log_entries()
    assert len(entries) == 3, (
        f"expected 3 entries after 3 calls; got {len(entries)}"
    )
    assert entries[0] == r1
    assert entries[1] == r2
    assert entries[2] == r3


def test_multiple_calls_each_have_unique_id(isolated_log):
    """Each entry must get its own fresh id."""
    from standup import close_standup
    ids = [
        close_standup(f"sid-{i}", "s", "tfm", "bl")["id"]
        for i in range(5)
    ]
    assert len(set(ids)) == 5, (
        f"close_standup must mint a fresh id per call; "
        f"got {len(set(ids))} unique ids across 5 calls: {ids}"
    )


def test_multiple_calls_preserve_distinct_session_ids(isolated_log):
    """Different session_ids passed in must surface as different
    session_ids on disk (no caching)."""
    from standup import close_standup
    close_standup("session-A", "s", "tfm", "bl")
    close_standup("session-B", "s", "tfm", "bl")
    entries = _read_log_entries()
    assert [e["session_id"] for e in entries] == ["session-A", "session-B"]


# --------------------------------------------------------------------------- #
# CRITERION — Multiline string values preserved verbatim
# (newlines kept via JSON escapes; entry remains one physical line)
# --------------------------------------------------------------------------- #

def test_multiline_shifted_preserved(isolated_log):
    """shifted field with embedded newlines must round-trip exactly,
    and the log entry must remain one physical line."""
    from standup import close_standup
    multi = "line one\nline two\n  indented line three"
    returned = close_standup("sid-multi-s", multi, "tfm", "bl")

    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, (
        f"multiline field must produce exactly one physical line on disk; "
        f"got {text.count(chr(10))} newlines"
    )

    entries = _read_log_entries()
    assert entries[0]["shifted"] == multi
    assert returned["shifted"] == multi


def test_multiline_tomorrows_first_move_preserved(isolated_log):
    """tomorrows_first_move field with embedded newlines must round-trip
    exactly."""
    from standup import close_standup
    multi = "first task\nsecond task\nthird task"
    returned = close_standup("sid-multi-tfm", "s", multi, "bl")
    entries = _read_log_entries()
    assert entries[0]["tomorrows_first_move"] == multi
    assert returned["tomorrows_first_move"] == multi


def test_multiline_blocking_preserved(isolated_log):
    """blocking field with embedded newlines must round-trip exactly."""
    from standup import close_standup
    multi = "blocker one\n  - sub a\n  - sub b\nblocker two"
    returned = close_standup("sid-multi-bl", "s", "tfm", multi)
    entries = _read_log_entries()
    assert entries[0]["blocking"] == multi
    assert returned["blocking"] == multi


def test_all_three_multiline_fields_simultaneously(isolated_log):
    """All three field values multiline at once — no bleed, all round-trip,
    one physical line on disk."""
    from standup import close_standup
    s = "s1\ns2\ns3"
    tfm = "tfm1\ntfm2"
    bl = "bl1\nbl2\nbl3\nbl4"
    returned = close_standup("sid-all-multi", s, tfm, bl)

    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, (
        "embedded newlines must be JSON-escaped, not split into lines; "
        f"got {text.count(chr(10))} physical newlines"
    )

    entries = _read_log_entries()
    e = entries[0]
    assert e["shifted"] == s
    assert e["tomorrows_first_move"] == tfm
    assert e["blocking"] == bl
    assert returned == e


def test_special_chars_in_field_values_preserved(isolated_log):
    """JSON-significant characters (quote, backslash, tab, CR) must
    round-trip without breaking the line."""
    from standup import close_standup
    s = 'has "quotes" and \\ backslashes'
    tfm = "has\ttabs\tand\rcarriage returns"
    bl = 'mix\n"quote"\n\\backslash\n\ttab'
    returned = close_standup("sid-special", s, tfm, bl)

    entries = _read_log_entries()
    assert entries[0]["shifted"] == s
    assert entries[0]["tomorrows_first_move"] == tfm
    assert entries[0]["blocking"] == bl
    assert returned == entries[0]


# --------------------------------------------------------------------------- #
# CRITERION — Empty string field values are allowed
# --------------------------------------------------------------------------- #

def test_empty_blocking_allowed(isolated_log):
    """blocking='' is allowed (the common 'nothing blocking tomorrow' case)."""
    from standup import close_standup
    returned = close_standup("sid-empty-bl", "s", "tfm", "")
    assert returned["blocking"] == ""
    entries = _read_log_entries()
    assert entries[0]["blocking"] == ""


def test_empty_shifted_allowed(isolated_log):
    """shifted='' is allowed (no plan shift today)."""
    from standup import close_standup
    returned = close_standup("sid-empty-s", "", "tfm", "bl")
    assert returned["shifted"] == ""
    entries = _read_log_entries()
    assert entries[0]["shifted"] == ""


def test_empty_tomorrows_first_move_allowed(isolated_log):
    """tomorrows_first_move='' is allowed (intentionally undecided)."""
    from standup import close_standup
    returned = close_standup("sid-empty-tfm", "s", "", "bl")
    assert returned["tomorrows_first_move"] == ""
    entries = _read_log_entries()
    assert entries[0]["tomorrows_first_move"] == ""


def test_all_empty_field_values_allowed(isolated_log):
    """All three field values empty simultaneously — still a valid call."""
    from standup import close_standup
    returned = close_standup("sid-all-empty", "", "", "")
    assert returned["shifted"] == ""
    assert returned["tomorrows_first_move"] == ""
    assert returned["blocking"] == ""
    entries = _read_log_entries()
    assert entries[0] == returned


# --------------------------------------------------------------------------- #
# CRITERION — Empty session_id raises ValueError
# (architect's session pairing invariant — a close needs SOME session_id
# even though no orphan check enforces a matching open)
# --------------------------------------------------------------------------- #

def test_empty_session_id_raises_value_error(isolated_log):
    """session_id='' must raise ValueError (a close with no session_id
    has nothing to pair against, ever)."""
    from standup import close_standup
    with pytest.raises(ValueError):
        close_standup("", "s", "tfm", "bl")


def test_empty_session_id_does_not_write(isolated_log):
    """A failed-validation call must not have written anything."""
    from standup import close_standup
    try:
        close_standup("", "s", "tfm", "bl")
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
    from standup import close_standup
    with pytest.raises((ValueError, TypeError)):
        close_standup(bad, "s", "tfm", "bl")


def test_non_string_session_id_does_not_write(isolated_log):
    """A failed-validation call must not have written anything."""
    from standup import close_standup
    try:
        close_standup(42, "s", "tfm", "bl")  # type: ignore[arg-type]
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

def test_non_string_shifted_raises_type_error(isolated_log):
    """Non-string shifted must raise TypeError. The error message must
    name 'shifted' so the operator can fix the offending field."""
    from standup import close_standup
    with pytest.raises(TypeError) as exc_info:
        close_standup("sid", 42, "tfm", "bl")  # type: ignore[arg-type]
    assert "shifted" in str(exc_info.value), (
        f"TypeError must name the offending field 'shifted'; "
        f"got message: {exc_info.value!s}"
    )


def test_non_string_tomorrows_first_move_raises_type_error(isolated_log):
    """Non-string tomorrows_first_move must raise TypeError naming
    'tomorrows_first_move'."""
    from standup import close_standup
    with pytest.raises(TypeError) as exc_info:
        close_standup("sid", "s", 99, "bl")  # type: ignore[arg-type]
    assert "tomorrows_first_move" in str(exc_info.value), (
        f"TypeError must name the offending field 'tomorrows_first_move'; "
        f"got message: {exc_info.value!s}"
    )


def test_non_string_blocking_raises_type_error(isolated_log):
    """Non-string blocking must raise TypeError naming 'blocking'."""
    from standup import close_standup
    with pytest.raises(TypeError) as exc_info:
        close_standup("sid", "s", "tfm", ["bl"])  # type: ignore[arg-type]
    assert "blocking" in str(exc_info.value), (
        f"TypeError must name the offending field 'blocking'; "
        f"got message: {exc_info.value!s}"
    )


@pytest.mark.parametrize(
    "field_name,values",
    [
        ("shifted", (None, "tfm", "bl")),
        ("shifted", (123, "tfm", "bl")),
        ("shifted", ([], "tfm", "bl")),
        ("tomorrows_first_move", ("s", None, "bl")),
        ("tomorrows_first_move", ("s", 3.14, "bl")),
        ("tomorrows_first_move", ("s", {}, "bl")),
        ("blocking", ("s", "tfm", None)),
        ("blocking", ("s", "tfm", 0)),
        ("blocking", ("s", "tfm", b"bytes")),
    ],
    ids=[
        "shifted-None", "shifted-int", "shifted-list",
        "tomorrows_first_move-None", "tomorrows_first_move-float",
        "tomorrows_first_move-dict",
        "blocking-None", "blocking-int", "blocking-bytes",
    ],
)
def test_non_string_field_value_raises_type_error_naming_field(
    isolated_log, field_name, values
):
    """Adversarial parametrized: every non-string field value raises
    TypeError, and the message names the offending field."""
    from standup import close_standup
    with pytest.raises(TypeError) as exc_info:
        close_standup("sid", *values)  # type: ignore[arg-type]
    assert field_name in str(exc_info.value), (
        f"TypeError for non-string {field_name} value must name the "
        f"field in its message; got: {exc_info.value!s}"
    )


def test_non_string_field_does_not_write(isolated_log):
    """A failed-validation call (non-string field value) must not have
    written anything."""
    from standup import close_standup
    try:
        close_standup("sid", "s", 42, "bl")  # type: ignore[arg-type]
    except TypeError:
        pass
    if isolated_log.exists():
        assert isolated_log.read_bytes() == b"", (
            "rejected non-string field still produced output; "
            "validation must run before any write"
        )


# --------------------------------------------------------------------------- #
# CRITERION — NO orphan check (PO v2 Req 10)
# close_standup does NOT verify a matching open exists — it writes
# the close entry regardless.
# --------------------------------------------------------------------------- #

def test_close_with_no_matching_open_does_not_raise(isolated_log):
    """A pristine log (no opens at all) plus a close call must succeed —
    the tool deliberately does not enforce open/close pairing per Req 10."""
    from standup import close_standup
    # Log file does not exist; no opens have ever been written.
    assert not isolated_log.exists()
    # Should write without complaint.
    returned = close_standup(
        "orphan-session-id-xyz",
        "s",
        "tfm",
        "bl",
    )
    assert returned["session_id"] == "orphan-session-id-xyz"
    assert returned["type"] == "close"

    entries = _read_log_entries()
    assert len(entries) == 1, (
        "close_standup must write the close entry even when no matching "
        "open exists; got 0 entries"
    )
    assert entries[0]["session_id"] == "orphan-session-id-xyz"
    assert entries[0]["type"] == "close"


def test_close_with_unrelated_open_session_does_not_raise(isolated_log):
    """An open with session_id A plus a close with session_id B must
    succeed — close_standup does not consult prior opens to validate
    the session_id pairing (Req 10)."""
    from standup import submit_open, close_standup
    submit_open("session-AAA", "y", "t", "b")
    # Close a totally different session id; must not raise.
    returned = close_standup("session-ZZZ-different", "s", "tfm", "bl")
    assert returned["session_id"] == "session-ZZZ-different"

    entries = _read_log_entries()
    assert len(entries) == 2
    assert entries[0]["type"] == "open"
    assert entries[0]["session_id"] == "session-AAA"
    assert entries[1]["type"] == "close"
    assert entries[1]["session_id"] == "session-ZZZ-different"


# --------------------------------------------------------------------------- #
# CRITERION — NO one-close-per-session enforcement
# A second close with the same session_id as a prior close still writes.
# --------------------------------------------------------------------------- #

def test_second_close_same_session_id_still_writes(isolated_log):
    """The tool does not enforce one-close-per-session uniqueness. A
    duplicate close (same session_id as a prior close) writes another
    close entry."""
    from standup import close_standup
    r1 = close_standup("dup-session", "s1", "tfm1", "bl1")
    r2 = close_standup("dup-session", "s2", "tfm2", "bl2")

    assert r1["id"] != r2["id"], (
        "duplicate close calls must mint distinct entry ids"
    )

    entries = _read_log_entries()
    assert len(entries) == 2, (
        f"two close_standup calls must yield two entries; got {len(entries)}"
    )
    assert entries[0]["session_id"] == "dup-session"
    assert entries[1]["session_id"] == "dup-session"
    assert entries[0]["type"] == "close"
    assert entries[1]["type"] == "close"
    # Distinct content survives.
    assert entries[0]["shifted"] == "s1"
    assert entries[1]["shifted"] == "s2"


def test_close_after_open_then_close_same_session_writes_third_entry(
    isolated_log,
):
    """open(A) -> close(A) -> close(A) must produce three entries; the
    second close is not deduped or rejected."""
    from standup import submit_open, close_standup
    submit_open("session-ABC", "y", "t", "b")
    close_standup("session-ABC", "s", "tfm", "bl")
    close_standup("session-ABC", "s2", "tfm2", "bl2")

    entries = _read_log_entries()
    assert len(entries) == 3
    assert entries[0]["type"] == "open"
    assert entries[1]["type"] == "close"
    assert entries[2]["type"] == "close"


# --------------------------------------------------------------------------- #
# EDGE CASE — close_standup returns a fresh dict per call (no shared state)
# --------------------------------------------------------------------------- #

def test_returned_dict_is_distinct_per_call(isolated_log):
    """Two calls must return distinct dict objects."""
    from standup import close_standup
    a = close_standup("sid-a", "s", "tfm", "bl")
    b = close_standup("sid-b", "s", "tfm", "bl")
    assert a is not b, (
        "close_standup must return a fresh dict per call; "
        "returning a shared/cached reference is unsafe"
    )


def test_mutating_returned_dict_does_not_affect_log(isolated_log):
    """Mutating the returned dict after the call must not change what
    is on disk (defensive against shared references)."""
    from standup import close_standup
    returned = close_standup("sid-mut", "s", "tfm", "bl")
    bytes_before = isolated_log.read_bytes()
    returned["shifted"] = "MUTATED"
    returned["new_key"] = "should not appear"
    bytes_after = isolated_log.read_bytes()
    assert bytes_before == bytes_after, (
        "mutating close_standup's return value must not change the log"
    )

    # And the on-disk record still has the original values.
    entries = _read_log_entries()
    assert entries[0]["shifted"] == "s"
    assert "new_key" not in entries[0]


# --------------------------------------------------------------------------- #
# EDGE CASE — close_standup uses _build_entry + _append_entry as glue
# (the two helpers are the canonical path; this test traces calls)
# --------------------------------------------------------------------------- #

def test_close_standup_routes_through_build_and_append(
    isolated_log, monkeypatch
):
    """close_standup must delegate construction to _build_entry and
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

    standup.close_standup("sid-glue", "s", "tfm", "bl")

    assert len(build_calls) == 1, (
        f"close_standup must call _build_entry exactly once per submission; "
        f"got {len(build_calls)} calls"
    )
    assert len(append_calls) == 1, (
        f"close_standup must call _append_entry exactly once per submission; "
        f"got {len(append_calls)} calls"
    )
    # And _build_entry was called with the right shape.
    bc = build_calls[0]
    assert bc["type"] == "close", (
        f"_build_entry must be called with type='close'; got {bc['type']!r}"
    )
    assert bc["session_id"] == "sid-glue"
    assert bc["fields"] == {
        "shifted": "s",
        "tomorrows_first_move": "tfm",
        "blocking": "bl",
    }
    assert bc["amends_id"] is None, (
        "close_standup must not pass amends_id; that is the amend flow's job"
    )


def test_validation_failure_does_not_call_append(isolated_log, monkeypatch):
    """When validation fails (non-string field), _append_entry must NOT
    be called — the failed call leaves the log untouched."""
    import standup

    append_calls: list[dict] = []
    real_append = standup._append_entry

    def tracking_append(entry):
        append_calls.append(dict(entry))
        return real_append(entry)

    monkeypatch.setattr(standup, "_append_entry", tracking_append)

    try:
        standup.close_standup("sid", 42, "tfm", "bl")  # type: ignore[arg-type]
    except TypeError:
        pass

    assert append_calls == [], (
        "validation failure must not call _append_entry; got "
        f"{len(append_calls)} append call(s)"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Long content tolerated
# --------------------------------------------------------------------------- #

def test_long_field_values_round_trip(isolated_log):
    """A reasonably large freeform field (~50KB) round-trips on one
    physical line."""
    from standup import close_standup
    big = "x" * 50_000
    returned = close_standup("sid-big", big, "tfm", "bl")

    text = isolated_log.read_text(encoding="utf-8")
    assert text.count("\n") == 1, "large field produced more than one line"
    entries = _read_log_entries()
    assert entries[0]["shifted"] == big
    assert returned["shifted"] == big


# --------------------------------------------------------------------------- #
# EDGE CASE — Unicode in field values preserved
# --------------------------------------------------------------------------- #

def test_unicode_field_values_preserved(isolated_log):
    """Non-ASCII content (Chinese, Cyrillic, emoji) round-trips exactly."""
    from standup import close_standup
    s = "中文测试 — shifted"
    tfm = "Привет — tomorrow's first move"
    bl = "🔥 blocking ✨"
    returned = close_standup("sid-unicode", s, tfm, bl)

    entries = _read_log_entries()
    assert entries[0]["shifted"] == s
    assert entries[0]["tomorrows_first_move"] == tfm
    assert entries[0]["blocking"] == bl
    assert returned == entries[0]


# --------------------------------------------------------------------------- #
# EDGE CASE — Open and close interleave cleanly in one log
# --------------------------------------------------------------------------- #

def test_open_then_close_produces_two_entries_in_order(isolated_log):
    """submit_open followed by close_standup writes two distinct entries,
    in call order, with the right types."""
    from standup import submit_open, close_standup
    o = submit_open("sess-pair", "y", "t", "b")
    c = close_standup("sess-pair", "s", "tfm", "bl")

    entries = _read_log_entries()
    assert len(entries) == 2
    assert entries[0] == o
    assert entries[1] == c
    assert entries[0]["type"] == "open"
    assert entries[1]["type"] == "close"
    assert entries[0]["session_id"] == entries[1]["session_id"] == "sess-pair"
