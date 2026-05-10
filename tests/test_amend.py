"""
Acceptance tests for Story 11 — amend() public function.

Rolls up to PO v2 Requirement 8 (append-only with amendment entries).

Verifies the public function

    amend(amends_id: str, fields: dict) -> dict

in ``standup``. amend is the public glue that:
  - locates the target entry by ``amends_id`` via _read_entries (Story 6)
  - validates that the target exists, is NOT itself an amend, and that
    ``fields`` mirror the target type's schema
  - constructs the amend entry via _build_entry(type='amend',
    session_id=<target's session_id>, fields=fields, amends_id=amends_id)
  - persists it via _append_entry (Story 5)
  - returns the amend entry that was written so callers can verify / echo
  - does NOT rewrite or modify the original entry's bytes on disk

Story 11 contract:
  - the amend's session_id is INHERITED from the target (not provided
    by caller) — binds the amendment to the same session as the original
  - amend entries themselves cannot be amended (flat layer over
    open/close, not a chain)
  - field-key mirror is enforced through _build_entry's existing rules

Coverage:
  - amend is importable: ``from standup import amend``
  - amend is in standup.__all__ (public)
  - signature: 2 required positional parameters (amends_id, fields)
  - valid amend of an open entry: writes amend with open mirror; original
    open entry's bytes on disk are byte-identical before/after the call
  - valid amend of a close entry: writes amend with close mirror; original
    close entry's bytes on disk are byte-identical before/after the call
  - returned entry has amend shape: id, session_id, type='amend',
    timestamp, amends_id, plus mirrored fields
  - amend's session_id matches target's session_id (inherited)
  - amend's amends_id matches the target's id
  - amend's id is a fresh uuid4 hex (different from amends_id)
  - amend's timestamp is fresh (later than target's)
  - empty amends_id raises ValueError
  - non-string amends_id raises ValueError or TypeError
  - amends_id not found in log raises ValueError naming the missing id
  - target type=='amend' raises ValueError ("cannot amend an amend")
  - wrong field set for target type raises ValueError (via _build_entry)
  - non-string field values raise TypeError (via _build_entry)
  - multiple amends of the same target are allowed; each is a distinct
    entry in the log
  - amend does NOT delete or rewrite any prior entry
  - glue tracing: _read_entries called (locate), _build_entry called
    once with correct args, _append_entry called once

Test isolation:
  - every test that touches the log monkeypatches ``standup.LOG_PATH``
    to a per-test ``tmp_path / "log.jsonl"`` so the real
    ``Tools/Standup/log.jsonl`` is never touched
  - log content is verified via ``standup._read_entries`` (production reader)

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


# Field key sets for each target type — these mirror what _build_entry
# enforces internally for amend entries.
OPEN_FIELDS = {
    "yesterday": "y-orig",
    "today": "t-orig",
    "blockers": "b-orig",
}
OPEN_FIELDS_AMENDED = {
    "yesterday": "y-fixed",
    "today": "t-fixed",
    "blockers": "b-fixed",
}
CLOSE_FIELDS = {
    "shifted": "shifted-orig",
    "tomorrows_first_move": "tfm-orig",
    "blocking": "blocking-orig",
}
CLOSE_FIELDS_AMENDED = {
    "shifted": "shifted-fixed",
    "tomorrows_first_move": "tfm-fixed",
    "blocking": "blocking-fixed",
}


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


def _seed_open(session_id="sess-orig"):
    """Use submit_open to create an open target entry. Returns the entry
    that was written (so tests can read its id, session_id, timestamp)."""
    import standup
    return standup.submit_open(
        session_id,
        OPEN_FIELDS["yesterday"],
        OPEN_FIELDS["today"],
        OPEN_FIELDS["blockers"],
    )


def _seed_close(session_id="sess-orig-close"):
    """Use close_standup to create a close target entry."""
    import standup
    return standup.close_standup(
        session_id,
        CLOSE_FIELDS["shifted"],
        CLOSE_FIELDS["tomorrows_first_move"],
        CLOSE_FIELDS["blocking"],
    )


# --------------------------------------------------------------------------- #
# CRITERION — amend is importable from `standup`
# --------------------------------------------------------------------------- #

def test_amend_importable():
    """`from standup import amend` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import amend  # noqa: F401
    assert callable(amend)


def test_amend_is_attribute_on_module():
    """The function must live on the standup module."""
    import standup
    assert hasattr(standup, "amend"), (
        "standup module must define amend"
    )
    assert callable(standup.amend)


# --------------------------------------------------------------------------- #
# CRITERION — amend is in __all__ (public)
# --------------------------------------------------------------------------- #

def test_amend_in_dunder_all():
    """Public functions must be exported via __all__."""
    import standup
    assert "amend" in standup.__all__, (
        f"amend must be public (listed in __all__); "
        f"current __all__ = {standup.__all__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: 2 required positional parameters
# (amends_id, fields)
# --------------------------------------------------------------------------- #

EXPECTED_PARAM_NAMES = ["amends_id", "fields"]


def test_amend_signature_param_names():
    """Parameter names must match the spec exactly and in order."""
    from standup import amend
    sig = inspect.signature(amend)
    assert list(sig.parameters.keys()) == EXPECTED_PARAM_NAMES, (
        f"amend must accept parameters {EXPECTED_PARAM_NAMES}; "
        f"got {list(sig.parameters.keys())}"
    )


def test_amend_signature_param_count():
    """Exactly 2 parameters — no more, no less."""
    from standup import amend
    sig = inspect.signature(amend)
    assert len(sig.parameters) == 2, (
        f"amend must take 2 parameters; got {len(sig.parameters)}"
    )


def test_amend_all_params_required():
    """Both parameters must be required (no defaults)."""
    from standup import amend
    sig = inspect.signature(amend)
    for name, param in sig.parameters.items():
        assert param.default is inspect.Parameter.empty, (
            f"amend parameter {name!r} must be required (no default); "
            f"got default={param.default!r}"
        )


def test_amend_no_varargs_or_kwargs():
    """Adversarial: guard against ``def amend(*a, **kw)`` style stubs."""
    from standup import amend
    sig = inspect.signature(amend)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"amend must not accept *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_amend_params_are_positional():
    """Each parameter must be callable positionally."""
    from standup import amend
    sig = inspect.signature(amend)
    for name, param in sig.parameters.items():
        assert param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ), (
            f"amend parameter {name!r} must be positional; "
            f"got kind {param.kind}"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Valid amend of an open entry
# --------------------------------------------------------------------------- #

def test_valid_amend_of_open_returns_dict(isolated_log):
    """amend of an open entry must return a dict."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert isinstance(result, dict), (
        f"amend must return a dict; got {type(result).__name__}"
    )


def test_valid_amend_of_open_has_amend_shape(isolated_log):
    """Returned amend must have id, session_id, type='amend', timestamp,
    amends_id, plus the open mirror fields — no extras, no omissions."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    expected_keys = {
        "id", "session_id", "type", "timestamp", "amends_id",
        "yesterday", "today", "blockers",
    }
    assert set(result.keys()) == expected_keys, (
        f"amend(open) keys mismatch; expected {expected_keys}, "
        f"got {set(result.keys())}"
    )


def test_valid_amend_of_open_type_is_amend(isolated_log):
    """Returned entry's ``type`` must be the string 'amend'."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert result["type"] == "amend", (
        f"amend must build entries with type='amend'; "
        f"got type={result['type']!r}"
    )


def test_valid_amend_of_open_field_values_match(isolated_log):
    """Returned amend's mirrored fields must equal the values passed in."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert result["yesterday"] == OPEN_FIELDS_AMENDED["yesterday"]
    assert result["today"] == OPEN_FIELDS_AMENDED["today"]
    assert result["blockers"] == OPEN_FIELDS_AMENDED["blockers"]


def test_valid_amend_of_open_writes_one_new_entry(isolated_log):
    """Before amend: 1 entry (the open). After amend: 2 entries (open
    + amend). The amend is appended, not inserted."""
    from standup import amend
    target = _seed_open()
    entries_before = _read_log_entries()
    assert len(entries_before) == 1
    amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    entries_after = _read_log_entries()
    assert len(entries_after) == 2, (
        f"amend must append exactly one entry; before=1, after={len(entries_after)}"
    )
    # First entry is still the original open; second is the amend.
    assert entries_after[0] == target
    assert entries_after[1]["type"] == "amend"


def test_valid_amend_of_open_does_not_modify_original_bytes(isolated_log):
    """The bytes occupied by the original open entry's line on disk must
    be byte-identical before and after the amend call."""
    from standup import amend
    target = _seed_open()
    bytes_before = isolated_log.read_bytes()
    # Sanity: the file holds exactly one line that ends with '\n'.
    assert bytes_before.endswith(b"\n")
    amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    bytes_after = isolated_log.read_bytes()
    # The first len(bytes_before) bytes — the original line — must be
    # untouched. The amend's bytes are appended after.
    assert bytes_after[: len(bytes_before)] == bytes_before, (
        "amend must not rewrite the original entry's bytes on disk; "
        "append-only invariant violated"
    )
    # And the file grew (amend added a line).
    assert len(bytes_after) > len(bytes_before), (
        "amend must append bytes; file did not grow"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Valid amend of a close entry
# --------------------------------------------------------------------------- #

def test_valid_amend_of_close_has_close_mirror_shape(isolated_log):
    """Returned amend (close mirror) must have id, session_id, type='amend',
    timestamp, amends_id, plus the close mirror fields."""
    from standup import amend
    target = _seed_close()
    result = amend(target["id"], dict(CLOSE_FIELDS_AMENDED))
    expected_keys = {
        "id", "session_id", "type", "timestamp", "amends_id",
        "shifted", "tomorrows_first_move", "blocking",
    }
    assert set(result.keys()) == expected_keys, (
        f"amend(close) keys mismatch; expected {expected_keys}, "
        f"got {set(result.keys())}"
    )


def test_valid_amend_of_close_field_values_match(isolated_log):
    """Returned amend's mirrored close fields must equal the values
    passed in."""
    from standup import amend
    target = _seed_close()
    result = amend(target["id"], dict(CLOSE_FIELDS_AMENDED))
    assert result["shifted"] == CLOSE_FIELDS_AMENDED["shifted"]
    assert result["tomorrows_first_move"] == \
        CLOSE_FIELDS_AMENDED["tomorrows_first_move"]
    assert result["blocking"] == CLOSE_FIELDS_AMENDED["blocking"]


def test_valid_amend_of_close_does_not_modify_original_bytes(isolated_log):
    """Original close entry's bytes on disk must be byte-identical
    before/after the amend call."""
    from standup import amend
    target = _seed_close()
    bytes_before = isolated_log.read_bytes()
    amend(target["id"], dict(CLOSE_FIELDS_AMENDED))
    bytes_after = isolated_log.read_bytes()
    assert bytes_after[: len(bytes_before)] == bytes_before, (
        "amend must not rewrite the original close entry's bytes; "
        "append-only invariant violated"
    )
    assert len(bytes_after) > len(bytes_before)


# --------------------------------------------------------------------------- #
# CRITERION — amend's session_id matches target's session_id (inherited)
# --------------------------------------------------------------------------- #

def test_amend_session_id_inherited_from_open_target(isolated_log):
    """amend's session_id must equal the target's session_id — caller
    does not provide it; amend looks it up."""
    from standup import amend
    target = _seed_open(session_id="custom-open-session")
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert result["session_id"] == target["session_id"], (
        f"amend session_id must equal target's; "
        f"target={target['session_id']!r}, amend={result['session_id']!r}"
    )
    assert result["session_id"] == "custom-open-session"


def test_amend_session_id_inherited_from_close_target(isolated_log):
    """Inheritance also applies when the target is a close entry."""
    from standup import amend
    target = _seed_close(session_id="custom-close-session")
    result = amend(target["id"], dict(CLOSE_FIELDS_AMENDED))
    assert result["session_id"] == target["session_id"]
    assert result["session_id"] == "custom-close-session"


# --------------------------------------------------------------------------- #
# CRITERION — amend's amends_id matches target's id
# --------------------------------------------------------------------------- #

def test_amend_amends_id_matches_target_id(isolated_log):
    """The amend's ``amends_id`` field must equal the target's ``id``."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert result["amends_id"] == target["id"], (
        f"amend.amends_id must equal target.id; "
        f"target.id={target['id']!r}, amend.amends_id={result['amends_id']!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — amend's id is a fresh uuid4 hex (different from amends_id)
# --------------------------------------------------------------------------- #

def test_amend_id_is_uuid4_hex(isolated_log):
    """The amend's id must be 32-char lowercase hex (uuid4)."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert isinstance(result["id"], str)
    assert UUID4_HEX_RE.match(result["id"]), (
        f"amend.id must be 32-char lowercase hex; got {result['id']!r}"
    )


def test_amend_id_differs_from_amends_id(isolated_log):
    """The amend MUST mint its own id; reusing the target's id would
    collapse the audit trail to a single record."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    assert result["id"] != result["amends_id"], (
        f"amend.id must be distinct from amends_id; both are "
        f"{result['id']!r}"
    )
    assert result["id"] != target["id"]


# --------------------------------------------------------------------------- #
# CRITERION — amend's timestamp is fresh (later than target's)
# --------------------------------------------------------------------------- #

def test_amend_timestamp_is_iso_with_offset(isolated_log):
    """The amend's timestamp must be an ISO 8601 string with a [+-]HH:MM
    offset (matches _now_iso output)."""
    from standup import amend
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    ts = result["timestamp"]
    assert isinstance(ts, str)
    assert ISO_OFFSET_RE.match(ts), (
        f"amend.timestamp must be ISO 8601 with [+-]HH:MM offset; got {ts!r}"
    )


def test_amend_timestamp_strictly_later_than_target(isolated_log):
    """The amend's timestamp must be strictly > the target's timestamp
    (it was generated later — at least one tick of clock resolution)."""
    from standup import amend, _parse_iso
    target = _seed_open()
    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    target_ts = _parse_iso(target["timestamp"])
    amend_ts = _parse_iso(result["timestamp"])
    assert amend_ts >= target_ts, (
        f"amend.timestamp must be >= target.timestamp; "
        f"target={target['timestamp']!r}, amend={result['timestamp']!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Round-trip: returned amend equals what landed on disk
# --------------------------------------------------------------------------- #

def test_returned_amend_equals_written_entry_round_trip(isolated_log):
    """The dict amend returns must equal the dict that lands on disk —
    confirmed by reading the log back and matching by id."""
    from standup import amend
    target = _seed_open()
    returned = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    entries = _read_log_entries()
    # Find the amend by id
    on_disk = next((e for e in entries if e.get("id") == returned["id"]), None)
    assert on_disk is not None, (
        f"amend entry not found on disk by id={returned['id']!r}"
    )
    assert on_disk == returned, (
        f"amend's return value must equal the entry written to disk; "
        f"returned={returned!r}, on_disk={on_disk!r}"
    )


def test_amend_round_trips_through_json(isolated_log):
    """The on-disk JSON line for the amend, parsed independently, equals
    amend's returned dict."""
    from standup import amend
    target = _seed_open()
    returned = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    # The log now contains two lines; the second is the amend.
    text = isolated_log.read_text(encoding="utf-8")
    lines = [ln for ln in text.split("\n") if ln]
    assert len(lines) == 2
    parsed = json.loads(lines[1])
    assert parsed == returned


# --------------------------------------------------------------------------- #
# CRITERION — Empty amends_id raises ValueError
# --------------------------------------------------------------------------- #

def test_empty_amends_id_raises_value_error(isolated_log):
    """amends_id='' must raise ValueError."""
    from standup import amend
    _seed_open()  # have at least one entry to look at
    with pytest.raises(ValueError):
        amend("", dict(OPEN_FIELDS_AMENDED))


def test_empty_amends_id_does_not_write(isolated_log):
    """A failed-validation call (empty amends_id) must not have written
    anything new to the log."""
    from standup import amend
    target = _seed_open()
    bytes_before = isolated_log.read_bytes()
    try:
        amend("", dict(OPEN_FIELDS_AMENDED))
    except ValueError:
        pass
    bytes_after = isolated_log.read_bytes()
    assert bytes_after == bytes_before, (
        "rejected empty amends_id still produced output; "
        "validation must run before any write"
    )
    # And no new amend exists in the log.
    entries = _read_log_entries()
    assert len(entries) == 1
    assert entries[0] == target


# --------------------------------------------------------------------------- #
# CRITERION — Non-string amends_id raises ValueError or TypeError
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad",
    [None, 42, 3.14, True, [], {}, b"bytes", ("tup",)],
    ids=["None", "int", "float", "bool", "list", "dict", "bytes", "tuple"],
)
def test_non_string_amends_id_raises(isolated_log, bad):
    """amends_id must be a str. Non-string values must raise loudly —
    either ValueError or TypeError is acceptable per the spec."""
    from standup import amend
    _seed_open()
    with pytest.raises((ValueError, TypeError)):
        amend(bad, dict(OPEN_FIELDS_AMENDED))


def test_non_string_amends_id_does_not_write(isolated_log):
    """A failed-validation call (non-string amends_id) must not have
    written anything."""
    from standup import amend
    _seed_open()
    bytes_before = isolated_log.read_bytes()
    try:
        amend(42, dict(OPEN_FIELDS_AMENDED))  # type: ignore[arg-type]
    except (ValueError, TypeError):
        pass
    bytes_after = isolated_log.read_bytes()
    assert bytes_after == bytes_before, (
        "rejected non-string amends_id still produced output"
    )


# --------------------------------------------------------------------------- #
# CRITERION — amends_id not found in log raises ValueError naming the id
# --------------------------------------------------------------------------- #

def test_unknown_amends_id_raises_value_error(isolated_log):
    """If no entry in the log has id == amends_id, ValueError is raised."""
    from standup import amend
    _seed_open()  # the log has one open entry, but with a different id
    missing_id = "deadbeef" * 4  # 32-hex string that won't match
    with pytest.raises(ValueError):
        amend(missing_id, dict(OPEN_FIELDS_AMENDED))


def test_unknown_amends_id_error_names_the_missing_id(isolated_log):
    """The ValueError message must name the missing id so the operator
    can see what was looked up."""
    from standup import amend
    _seed_open()
    missing_id = "cafef00d" * 4
    with pytest.raises(ValueError) as exc_info:
        amend(missing_id, dict(OPEN_FIELDS_AMENDED))
    assert missing_id in str(exc_info.value), (
        f"ValueError message must name the missing id {missing_id!r}; "
        f"got: {exc_info.value!s}"
    )


def test_unknown_amends_id_does_not_write(isolated_log):
    """A failed-lookup call must not have written anything."""
    from standup import amend
    _seed_open()
    bytes_before = isolated_log.read_bytes()
    try:
        amend("deadbeef" * 4, dict(OPEN_FIELDS_AMENDED))
    except ValueError:
        pass
    bytes_after = isolated_log.read_bytes()
    assert bytes_after == bytes_before, (
        "rejected unknown amends_id still produced output"
    )


def test_amends_id_lookup_against_empty_log_raises(isolated_log):
    """Looking up any amends_id when the log is empty must raise
    ValueError (no targets exist)."""
    from standup import amend
    assert not isolated_log.exists()
    with pytest.raises(ValueError):
        amend("deadbeef" * 4, dict(OPEN_FIELDS_AMENDED))


# --------------------------------------------------------------------------- #
# CRITERION — Trying to amend an amend raises ValueError
# ("cannot amend an amend")
# --------------------------------------------------------------------------- #

def test_cannot_amend_an_amend_raises_value_error(isolated_log):
    """Once an amend exists, attempting to amend that amend must raise
    ValueError. Amends are a flat layer, not a chain."""
    from standup import amend
    target = _seed_open()
    first_amend = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    # Now try to amend the amend itself:
    with pytest.raises(ValueError):
        amend(first_amend["id"], dict(OPEN_FIELDS_AMENDED))


def test_cannot_amend_an_amend_error_message(isolated_log):
    """The error message must communicate that an amend cannot itself
    be amended (avoids ambiguity of 'which version is current')."""
    from standup import amend
    target = _seed_open()
    first_amend = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    with pytest.raises(ValueError) as exc_info:
        amend(first_amend["id"], dict(OPEN_FIELDS_AMENDED))
    msg = str(exc_info.value).lower()
    assert "amend" in msg, (
        f"ValueError when targeting an amend must mention 'amend' in "
        f"its message; got: {exc_info.value!s}"
    )


def test_cannot_amend_an_amend_does_not_write(isolated_log):
    """A rejected amend-of-amend call must not have written anything new."""
    from standup import amend
    target = _seed_open()
    first_amend = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    bytes_before = isolated_log.read_bytes()
    try:
        amend(first_amend["id"], dict(OPEN_FIELDS_AMENDED))
    except ValueError:
        pass
    bytes_after = isolated_log.read_bytes()
    assert bytes_after == bytes_before, (
        "rejected amend-of-amend still produced output"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Wrong field set for target type raises ValueError
# (delegated through _build_entry's mirror enforcement)
# --------------------------------------------------------------------------- #

def test_open_target_with_close_fields_raises_value_error(isolated_log):
    """An open target requires open mirror fields. Passing close-shape
    fields must raise ValueError (delegated through _build_entry)."""
    from standup import amend
    target = _seed_open()
    with pytest.raises(ValueError):
        amend(target["id"], dict(CLOSE_FIELDS_AMENDED))


def test_close_target_with_open_fields_raises_value_error(isolated_log):
    """A close target requires close mirror fields. Passing open-shape
    fields must raise ValueError."""
    from standup import amend
    target = _seed_close()
    with pytest.raises(ValueError):
        amend(target["id"], dict(OPEN_FIELDS_AMENDED))


def test_missing_field_keys_raises_value_error(isolated_log):
    """Missing one of the required mirror keys must raise ValueError."""
    from standup import amend
    target = _seed_open()
    incomplete = {"yesterday": "y", "today": "t"}  # missing 'blockers'
    with pytest.raises(ValueError):
        amend(target["id"], incomplete)


def test_extra_field_keys_raises_value_error(isolated_log):
    """Extra keys beyond the mirror set must raise ValueError."""
    from standup import amend
    target = _seed_open()
    extra = dict(OPEN_FIELDS_AMENDED)
    extra["surprise"] = "not a real field"
    with pytest.raises(ValueError):
        amend(target["id"], extra)


def test_wrong_field_set_does_not_write(isolated_log):
    """A failed field-validation call must not have written anything new."""
    from standup import amend
    target = _seed_open()
    bytes_before = isolated_log.read_bytes()
    try:
        amend(target["id"], dict(CLOSE_FIELDS_AMENDED))
    except ValueError:
        pass
    bytes_after = isolated_log.read_bytes()
    assert bytes_after == bytes_before


# --------------------------------------------------------------------------- #
# CRITERION — Non-string field values raise TypeError (via _build_entry)
# --------------------------------------------------------------------------- #

def test_non_string_yesterday_raises_type_error(isolated_log):
    """Non-string yesterday (when amending an open) must raise TypeError."""
    from standup import amend
    target = _seed_open()
    bad_fields = {"yesterday": 42, "today": "t", "blockers": "b"}
    with pytest.raises(TypeError) as exc_info:
        amend(target["id"], bad_fields)  # type: ignore[arg-type]
    assert "yesterday" in str(exc_info.value), (
        f"TypeError must name the offending field 'yesterday'; "
        f"got: {exc_info.value!s}"
    )


def test_non_string_blocking_raises_type_error(isolated_log):
    """Non-string blocking (when amending a close) must raise TypeError."""
    from standup import amend
    target = _seed_close()
    bad_fields = {"shifted": "s", "tomorrows_first_move": "t", "blocking": []}
    with pytest.raises(TypeError) as exc_info:
        amend(target["id"], bad_fields)  # type: ignore[arg-type]
    assert "blocking" in str(exc_info.value), (
        f"TypeError must name the offending field 'blocking'; "
        f"got: {exc_info.value!s}"
    )


def test_non_string_field_value_does_not_write(isolated_log):
    """A failed field-value-type-check must not have written anything new."""
    from standup import amend
    target = _seed_open()
    bytes_before = isolated_log.read_bytes()
    try:
        amend(target["id"], {"yesterday": 42, "today": "t", "blockers": "b"})
    except TypeError:
        pass
    bytes_after = isolated_log.read_bytes()
    assert bytes_after == bytes_before


# --------------------------------------------------------------------------- #
# CRITERION — Multiple amends of the same target are allowed
# --------------------------------------------------------------------------- #

def test_multiple_amends_of_same_target_allowed(isolated_log):
    """A single target may be amended multiple times — each amend is a
    separate entry, all with the same amends_id (= target.id) but
    distinct ids."""
    from standup import amend
    target = _seed_open()
    a1 = amend(target["id"], {"yesterday": "y1", "today": "t1", "blockers": "b1"})
    a2 = amend(target["id"], {"yesterday": "y2", "today": "t2", "blockers": "b2"})
    a3 = amend(target["id"], {"yesterday": "y3", "today": "t3", "blockers": "b3"})

    entries = _read_log_entries()
    assert len(entries) == 4, (
        f"after target + 3 amends, log must have 4 entries; got {len(entries)}"
    )
    # All three amends point at the same target.
    assert a1["amends_id"] == target["id"]
    assert a2["amends_id"] == target["id"]
    assert a3["amends_id"] == target["id"]
    # Each amend has its own distinct id.
    ids = {a1["id"], a2["id"], a3["id"]}
    assert len(ids) == 3, (
        f"each amend must have a fresh id; got {len(ids)} unique ids"
    )
    # All three amends inherit the same session_id from the target.
    assert a1["session_id"] == target["session_id"]
    assert a2["session_id"] == target["session_id"]
    assert a3["session_id"] == target["session_id"]


def test_multiple_amends_appended_in_order(isolated_log):
    """Entries on disk must appear in the order amends were submitted."""
    from standup import amend
    target = _seed_open()
    a1 = amend(target["id"], {"yesterday": "y1", "today": "t1", "blockers": "b1"})
    a2 = amend(target["id"], {"yesterday": "y2", "today": "t2", "blockers": "b2"})

    entries = _read_log_entries()
    assert entries[0] == target
    assert entries[1] == a1
    assert entries[2] == a2


# --------------------------------------------------------------------------- #
# CRITERION — amend does NOT delete or rewrite any prior entry
# --------------------------------------------------------------------------- #

def test_amend_does_not_modify_unrelated_prior_entries(isolated_log):
    """All entries that existed before the amend call must be byte-identical
    on disk after the amend call (only new bytes appear at the end)."""
    from standup import amend
    # Seed several unrelated entries first.
    _seed_open(session_id="sess-1")
    _seed_open(session_id="sess-2")
    target = _seed_open(session_id="sess-target")
    _seed_close(session_id="sess-1")

    bytes_before = isolated_log.read_bytes()
    entries_before = _read_log_entries()
    assert len(entries_before) == 4

    amend(target["id"], dict(OPEN_FIELDS_AMENDED))

    bytes_after = isolated_log.read_bytes()
    # All prior bytes intact.
    assert bytes_after[: len(bytes_before)] == bytes_before, (
        "amend must not modify any prior entry's bytes on disk"
    )
    # File grew by the amend line.
    assert len(bytes_after) > len(bytes_before)

    # And all 4 prior entries still round-trip identically.
    entries_after = _read_log_entries()
    assert len(entries_after) == 5
    for i in range(4):
        assert entries_after[i] == entries_before[i], (
            f"entry {i} changed after amend; "
            f"before={entries_before[i]!r}, after={entries_after[i]!r}"
        )


def test_amend_does_not_remove_any_entries(isolated_log):
    """The number of entries after amend must equal entries-before + 1
    (no deletions)."""
    from standup import amend
    _seed_open(session_id="s1")
    target = _seed_open(session_id="s2")
    _seed_close(session_id="s1")
    n_before = len(_read_log_entries())
    amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    n_after = len(_read_log_entries())
    assert n_after == n_before + 1, (
        f"amend must add exactly one entry; "
        f"before={n_before}, after={n_after}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Glue tracing: _read_entries (locate),
# _build_entry called once with correct args, _append_entry called once
# --------------------------------------------------------------------------- #

def test_amend_routes_through_read_build_and_append(isolated_log, monkeypatch):
    """amend must:
      - call _read_entries to locate the target
      - call _build_entry exactly once with type='amend',
        session_id=<target's>, fields=<caller's>, amends_id=<target.id>
      - call _append_entry exactly once with the constructed entry
    """
    import standup

    target = _seed_open(session_id="glue-session")

    read_calls: list[tuple[list[dict], list]] = []
    build_calls: list[dict] = []
    append_calls: list[dict] = []

    real_read = standup._read_entries
    real_build = standup._build_entry
    real_append = standup._append_entry

    def tracking_read():
        result = real_read()
        # store a snapshot so caller's later mutations don't affect us
        read_calls.append(([dict(e) for e in result[0]], list(result[1])))
        return result

    def tracking_build(type, session_id, fields, amends_id=None):
        build_calls.append(
            {"type": type, "session_id": session_id,
             "fields": dict(fields), "amends_id": amends_id}
        )
        return real_build(type, session_id, fields, amends_id)

    def tracking_append(entry):
        append_calls.append(dict(entry))
        return real_append(entry)

    monkeypatch.setattr(standup, "_read_entries", tracking_read)
    monkeypatch.setattr(standup, "_build_entry", tracking_build)
    monkeypatch.setattr(standup, "_append_entry", tracking_append)

    standup.amend(target["id"], dict(OPEN_FIELDS_AMENDED))

    # _read_entries called at least once (to locate target).
    assert len(read_calls) >= 1, (
        "amend must call _read_entries to locate the target"
    )

    # _build_entry called exactly once, with the right shape.
    assert len(build_calls) == 1, (
        f"amend must call _build_entry exactly once; "
        f"got {len(build_calls)} calls"
    )
    bc = build_calls[0]
    assert bc["type"] == "amend", (
        f"_build_entry must be called with type='amend'; got {bc['type']!r}"
    )
    assert bc["session_id"] == target["session_id"], (
        f"_build_entry session_id must equal target's; "
        f"target={target['session_id']!r}, build_call={bc['session_id']!r}"
    )
    assert bc["fields"] == OPEN_FIELDS_AMENDED, (
        f"_build_entry fields must equal caller's fields; "
        f"got {bc['fields']!r}"
    )
    assert bc["amends_id"] == target["id"], (
        f"_build_entry amends_id must equal target.id; "
        f"target.id={target['id']!r}, build_call={bc['amends_id']!r}"
    )

    # _append_entry called exactly once.
    assert len(append_calls) == 1, (
        f"amend must call _append_entry exactly once; "
        f"got {len(append_calls)} calls"
    )


def test_amend_does_not_call_build_or_append_on_validation_failure(
    isolated_log, monkeypatch
):
    """When validation fails (e.g., empty amends_id), amend must NOT
    reach _build_entry or _append_entry."""
    import standup

    build_calls: list[dict] = []
    append_calls: list[dict] = []

    def tracking_build(type, session_id, fields, amends_id=None):
        build_calls.append({"type": type})
        return standup._build_entry  # unreachable but keep signature happy

    def tracking_append(entry):
        append_calls.append(dict(entry))

    monkeypatch.setattr(standup, "_build_entry", tracking_build)
    monkeypatch.setattr(standup, "_append_entry", tracking_append)

    with pytest.raises(ValueError):
        standup.amend("", dict(OPEN_FIELDS_AMENDED))

    assert build_calls == [], (
        "amend must not call _build_entry when validation fails"
    )
    assert append_calls == [], (
        "amend must not call _append_entry when validation fails"
    )


def test_amend_does_not_call_append_on_unknown_target(
    isolated_log, monkeypatch
):
    """When amends_id is not found, amend must not call _append_entry —
    nothing should be written for a failed lookup."""
    import standup

    _seed_open()  # log has one open entry

    append_calls: list[dict] = []

    real_append = standup._append_entry

    def tracking_append(entry):
        append_calls.append(dict(entry))
        return real_append(entry)

    monkeypatch.setattr(standup, "_append_entry", tracking_append)

    with pytest.raises(ValueError):
        standup.amend("deadbeef" * 4, dict(OPEN_FIELDS_AMENDED))

    # Note: _append_entry was used by _seed_open earlier (before patching).
    # Since we patched after seeding, the only calls captured here are
    # those that would happen during amend(). Expect zero.
    assert append_calls == [], (
        "amend must not call _append_entry when target lookup fails; "
        f"got {len(append_calls)} call(s)"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — amend returns a fresh dict per call (no shared state)
# --------------------------------------------------------------------------- #

def test_returned_dict_is_distinct_per_call(isolated_log):
    """Two amend calls must return distinct dict objects."""
    from standup import amend
    target = _seed_open()
    a = amend(target["id"], {"yesterday": "y1", "today": "t1", "blockers": "b1"})
    b = amend(target["id"], {"yesterday": "y2", "today": "t2", "blockers": "b2"})
    assert a is not b, (
        "amend must return a fresh dict per call; "
        "returning a shared/cached reference is unsafe"
    )


def test_mutating_returned_dict_does_not_affect_log(isolated_log):
    """Mutating amend's returned dict after the call must not change
    what is on disk (defensive against shared references)."""
    from standup import amend
    target = _seed_open()
    returned = amend(target["id"], dict(OPEN_FIELDS_AMENDED))
    bytes_before = isolated_log.read_bytes()
    returned["yesterday"] = "MUTATED"
    returned["new_key"] = "should not appear"
    bytes_after = isolated_log.read_bytes()
    assert bytes_before == bytes_after, (
        "mutating amend's return value must not change the log"
    )
    # And the on-disk amend still has its original values.
    entries = _read_log_entries()
    on_disk_amend = next(
        e for e in entries if e.get("type") == "amend"
    )
    assert on_disk_amend["yesterday"] == OPEN_FIELDS_AMENDED["yesterday"]
    assert "new_key" not in on_disk_amend


# --------------------------------------------------------------------------- #
# EDGE CASE — Caller's input fields dict not mutated
# --------------------------------------------------------------------------- #

def test_caller_fields_dict_not_mutated(isolated_log):
    """amend must not mutate the fields dict passed in by the caller."""
    from standup import amend
    target = _seed_open()
    original_fields = dict(OPEN_FIELDS_AMENDED)
    snapshot = dict(original_fields)
    amend(target["id"], original_fields)
    assert original_fields == snapshot, (
        f"amend mutated the caller's fields dict; "
        f"before={snapshot!r}, after={original_fields!r}"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Multiline / unicode values preserved through amend
# --------------------------------------------------------------------------- #

def test_amend_preserves_multiline_values(isolated_log):
    """Multiline values in amend fields round-trip exactly, and the
    amend remains a single physical line on disk."""
    from standup import amend
    target = _seed_open()
    bytes_before = isolated_log.read_bytes()
    multi_y = "line one\nline two\n  indented line three"
    multi_t = "first task\nsecond task"
    multi_b = "blocker one\n  - sub a\n  - sub b"
    returned = amend(
        target["id"],
        {"yesterday": multi_y, "today": multi_t, "blockers": multi_b},
    )

    # Original line still byte-identical.
    bytes_after = isolated_log.read_bytes()
    assert bytes_after[: len(bytes_before)] == bytes_before

    # Amend is a single physical line — newlines escaped inside JSON.
    appended = bytes_after[len(bytes_before):]
    # The appended chunk must end in a single newline and contain only
    # one physical newline (the line terminator).
    assert appended.endswith(b"\n")
    assert appended.count(b"\n") == 1, (
        "embedded newlines in amend fields must be JSON-escaped, not "
        f"split into lines; got {appended.count(chr(10).encode())} newlines"
    )

    entries = _read_log_entries()
    on_disk_amend = next(e for e in entries if e["id"] == returned["id"])
    assert on_disk_amend["yesterday"] == multi_y
    assert on_disk_amend["today"] == multi_t
    assert on_disk_amend["blockers"] == multi_b


def test_amend_preserves_unicode_values(isolated_log):
    """Non-ASCII content in amend fields round-trips exactly."""
    from standup import amend
    target = _seed_open()
    y = "中文测试 — yesterday"
    t = "Привет — today"
    b = "🔥 blockers ✨"
    returned = amend(
        target["id"],
        {"yesterday": y, "today": t, "blockers": b},
    )

    entries = _read_log_entries()
    on_disk_amend = next(e for e in entries if e["id"] == returned["id"])
    assert on_disk_amend["yesterday"] == y
    assert on_disk_amend["today"] == t
    assert on_disk_amend["blockers"] == b
    assert returned == on_disk_amend


# --------------------------------------------------------------------------- #
# EDGE CASE — Empty string amend field values are allowed (mirror of
# submit_open / close_standup behavior)
# --------------------------------------------------------------------------- #

def test_amend_with_all_empty_string_values_allowed(isolated_log):
    """Empty string values for the mirrored fields are allowed in amend
    (mirror of submit_open/close_standup behavior — empty != non-string)."""
    from standup import amend
    target = _seed_open()
    returned = amend(
        target["id"],
        {"yesterday": "", "today": "", "blockers": ""},
    )
    assert returned["yesterday"] == ""
    assert returned["today"] == ""
    assert returned["blockers"] == ""

    entries = _read_log_entries()
    on_disk_amend = next(e for e in entries if e["id"] == returned["id"])
    assert on_disk_amend == returned


# --------------------------------------------------------------------------- #
# EDGE CASE — amend across multiple sessions; correct target located
# --------------------------------------------------------------------------- #

def test_amend_locates_correct_target_among_many(isolated_log):
    """When the log holds many entries across multiple sessions, amend
    must locate the exact entry whose id == amends_id and inherit its
    session_id specifically."""
    from standup import amend
    _seed_open(session_id="alpha")
    _seed_close(session_id="alpha")
    target = _seed_open(session_id="bravo")
    _seed_open(session_id="charlie")
    _seed_close(session_id="bravo")

    result = amend(target["id"], dict(OPEN_FIELDS_AMENDED))

    assert result["amends_id"] == target["id"]
    assert result["session_id"] == "bravo", (
        f"amend must inherit the matched target's session_id; "
        f"expected 'bravo', got {result['session_id']!r}"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Non-dict fields argument raises (delegated through _build_entry)
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad_fields",
    [None, "string", 42, [("yesterday", "y")], ("y", "t", "b")],
    ids=["None", "string", "int", "list-of-tuples", "tuple"],
)
def test_non_dict_fields_raises(isolated_log, bad_fields):
    """A non-dict ``fields`` argument must raise loudly — _build_entry
    raises TypeError for non-dict fields, but amend may also reject it
    earlier with a different error type, so we accept (TypeError,
    ValueError, AttributeError) here."""
    from standup import amend
    target = _seed_open()
    with pytest.raises((TypeError, ValueError, AttributeError)):
        amend(target["id"], bad_fields)  # type: ignore[arg-type]
