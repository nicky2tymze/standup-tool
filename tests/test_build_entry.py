"""
Acceptance tests for Story 4 — Entry schema construction and validation.

Rolls up to PO v2 Requirements 4 (entry schema), 8 (append-only with
amendment entries), 9 (session identity).

Verifies the private helper

    _build_entry(
        type: str,
        session_id: str,
        fields: dict,
        amends_id: str | None = None,
    ) -> dict

in standup.py:

  - Importable as ``from standup import _build_entry``
  - NOT exported in ``standup.__all__`` (private)
  - Always returns a dict with: id, session_id, type, timestamp
  - id is fresh uuid4 hex (32 lowercase hex chars), distinct across calls
  - timestamp is fresh ISO 8601 with offset (parseable by _parse_iso)
  - Type-specific schemas:
      open  -> {yesterday, today, blockers}
      close -> {shifted, tomorrows_first_move, blocking}
      amend -> mirrors open OR close; carries amends_id
  - Field VALUES must all be strings (multiline preserved)
  - Loud rejection of malformed input (ValueError / TypeError)

This helper does NOT touch disk; no monkeypatch needed.

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import inspect
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


# --------------------------------------------------------------------------- #
# Constants — schema field-key sets used across many tests
# --------------------------------------------------------------------------- #

OPEN_FIELDS = {"yesterday": "y", "today": "t", "blockers": "b"}
CLOSE_FIELDS = {
    "shifted": "s",
    "tomorrows_first_move": "tfm",
    "blocking": "bl",
}

OPEN_KEYS = set(OPEN_FIELDS.keys())
CLOSE_KEYS = set(CLOSE_FIELDS.keys())

UUID4_HEX_PATTERN = re.compile(r"^[0-9a-f]{32}$")
SESSION_ID = "session-abc-123"
AMENDS_ID = "ffeeddccbbaa99887766554433221100"


# --------------------------------------------------------------------------- #
# CRITERION — _build_entry is importable from `standup`
# --------------------------------------------------------------------------- #

def test_build_entry_importable():
    """`from standup import _build_entry` must succeed."""
    from standup import _build_entry  # noqa: F401
    assert callable(_build_entry)


def test_build_entry_is_attribute_on_module():
    """The helper must live on the standup module itself."""
    import standup
    assert hasattr(standup, "_build_entry"), (
        "standup module must define _build_entry"
    )
    assert callable(standup._build_entry)


# --------------------------------------------------------------------------- #
# CRITERION — _build_entry is NOT in __all__ (private)
# --------------------------------------------------------------------------- #

def test_build_entry_not_in_dunder_all():
    """Private helpers must not be re-exported via __all__."""
    import standup
    assert "_build_entry" not in standup.__all__, (
        "_build_entry must be private (excluded from __all__); "
        f"current __all__ = {standup.__all__}"
    )


def test_build_entry_name_underscore_prefixed():
    """Belt-and-suspenders: the canonical name must start with underscore."""
    from standup import _build_entry
    assert _build_entry.__name__.startswith("_"), (
        f"_build_entry.__name__ must be underscore-prefixed; "
        f"got {_build_entry.__name__!r}"
    )


def test_no_public_alias_exposes_build_entry():
    """No symbol in __all__ may be the same callable as _build_entry."""
    import standup
    target = getattr(standup, "_build_entry", object())
    for name in standup.__all__:
        obj = getattr(standup, name, None)
        if obj is target:
            pytest.fail(
                f"Public alias {name!r} exposes _build_entry; "
                "private helpers must not be re-exported"
            )


# --------------------------------------------------------------------------- #
# CRITERION — Function signature matches the story
# --------------------------------------------------------------------------- #

def test_signature_has_expected_parameters():
    """_build_entry(type, session_id, fields, amends_id=None)."""
    from standup import _build_entry
    sig = inspect.signature(_build_entry)
    params = list(sig.parameters.values())
    names = [p.name for p in params]
    assert names == ["type", "session_id", "fields", "amends_id"], (
        f"_build_entry signature must be "
        f"(type, session_id, fields, amends_id=None); got params {names}"
    )
    # amends_id has a default of None
    assert sig.parameters["amends_id"].default is None, (
        "amends_id parameter must default to None; "
        f"got {sig.parameters['amends_id'].default!r}"
    )
    # The first three params must NOT have defaults
    for required in ("type", "session_id", "fields"):
        assert sig.parameters[required].default is inspect.Parameter.empty, (
            f"{required!r} must be a required parameter (no default)"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Valid open entry — full shape
# --------------------------------------------------------------------------- #

def test_valid_open_entry_has_required_keys():
    """type='open' produces a dict with id, session_id, type, timestamp,
    plus the three open-schema fields."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))

    assert isinstance(entry, dict), (
        f"_build_entry must return a dict; got {type(entry).__name__}"
    )

    expected_keys = {"id", "session_id", "type", "timestamp"} | OPEN_KEYS
    assert set(entry.keys()) == expected_keys, (
        f"open entry keys mismatch; expected {expected_keys}, "
        f"got {set(entry.keys())}"
    )


def test_valid_open_entry_field_values_preserved():
    """The open entry must carry through the input field values verbatim."""
    from standup import _build_entry
    fields = {"yesterday": "did A", "today": "do B", "blockers": "none"}
    entry = _build_entry("open", SESSION_ID, fields)
    assert entry["yesterday"] == "did A"
    assert entry["today"] == "do B"
    assert entry["blockers"] == "none"


def test_valid_open_entry_type_and_session_id():
    """type and session_id must be passed through to the entry."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert entry["type"] == "open"
    assert entry["session_id"] == SESSION_ID


def test_valid_open_entry_no_amends_id_key():
    """type='open' (no amends_id passed) MUST NOT include an amends_id
    key in the returned dict — that key is reserved for amend entries."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert "amends_id" not in entry, (
        f"open entry must not carry an 'amends_id' key; got entry={entry!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Valid close entry — full shape
# --------------------------------------------------------------------------- #

def test_valid_close_entry_has_required_keys():
    """type='close' produces a dict with id, session_id, type, timestamp,
    plus the three close-schema fields."""
    from standup import _build_entry
    entry = _build_entry("close", SESSION_ID, dict(CLOSE_FIELDS))

    expected_keys = {"id", "session_id", "type", "timestamp"} | CLOSE_KEYS
    assert set(entry.keys()) == expected_keys, (
        f"close entry keys mismatch; expected {expected_keys}, "
        f"got {set(entry.keys())}"
    )


def test_valid_close_entry_field_values_preserved():
    """Close field values must round-trip verbatim."""
    from standup import _build_entry
    fields = {
        "shifted": "scope grew",
        "tomorrows_first_move": "ship the patch",
        "blocking": "waiting on review",
    }
    entry = _build_entry("close", SESSION_ID, fields)
    assert entry["shifted"] == "scope grew"
    assert entry["tomorrows_first_move"] == "ship the patch"
    assert entry["blocking"] == "waiting on review"


def test_valid_close_entry_type_and_session_id():
    """type='close' must be reflected in the entry; session_id passed through."""
    from standup import _build_entry
    entry = _build_entry("close", SESSION_ID, dict(CLOSE_FIELDS))
    assert entry["type"] == "close"
    assert entry["session_id"] == SESSION_ID


def test_valid_close_entry_no_amends_id_key():
    """A non-amend entry must not carry an amends_id key."""
    from standup import _build_entry
    entry = _build_entry("close", SESSION_ID, dict(CLOSE_FIELDS))
    assert "amends_id" not in entry, (
        f"close entry must not carry an 'amends_id' key; got entry={entry!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Valid amend entry mirroring open
# --------------------------------------------------------------------------- #

def test_valid_amend_entry_mirrors_open_shape():
    """An amend with open-schema fields produces id, session_id,
    type='amend', timestamp, amends_id, plus the open fields."""
    from standup import _build_entry
    entry = _build_entry(
        "amend", SESSION_ID, dict(OPEN_FIELDS), amends_id=AMENDS_ID
    )

    expected_keys = (
        {"id", "session_id", "type", "timestamp", "amends_id"} | OPEN_KEYS
    )
    assert set(entry.keys()) == expected_keys, (
        f"amend(open) entry keys mismatch; expected {expected_keys}, "
        f"got {set(entry.keys())}"
    )
    assert entry["type"] == "amend"
    assert entry["session_id"] == SESSION_ID
    assert entry["amends_id"] == AMENDS_ID


def test_valid_amend_entry_mirrors_open_field_values():
    """Open-schema field values must round-trip in the amend."""
    from standup import _build_entry
    fields = {
        "yesterday": "yest-corrected",
        "today": "today-corrected",
        "blockers": "blockers-corrected",
    }
    entry = _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)
    for k, v in fields.items():
        assert entry[k] == v


# --------------------------------------------------------------------------- #
# CRITERION — Valid amend entry mirroring close
# --------------------------------------------------------------------------- #

def test_valid_amend_entry_mirrors_close_shape():
    """An amend with close-schema fields produces the close-shaped dict
    plus amends_id and type='amend'."""
    from standup import _build_entry
    entry = _build_entry(
        "amend", SESSION_ID, dict(CLOSE_FIELDS), amends_id=AMENDS_ID
    )

    expected_keys = (
        {"id", "session_id", "type", "timestamp", "amends_id"} | CLOSE_KEYS
    )
    assert set(entry.keys()) == expected_keys, (
        f"amend(close) entry keys mismatch; expected {expected_keys}, "
        f"got {set(entry.keys())}"
    )
    assert entry["type"] == "amend"
    assert entry["amends_id"] == AMENDS_ID


def test_valid_amend_entry_mirrors_close_field_values():
    """Close-schema field values must round-trip in the amend."""
    from standup import _build_entry
    fields = {
        "shifted": "actually scope held",
        "tomorrows_first_move": "different plan",
        "blocking": "now unblocked",
    }
    entry = _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)
    for k, v in fields.items():
        assert entry[k] == v


# --------------------------------------------------------------------------- #
# CRITERION — id is a fresh uuid4 hex (32 lowercase hex chars)
# --------------------------------------------------------------------------- #

def test_id_is_uuid4_hex_format_open():
    """For an open entry, id must match ^[0-9a-f]{32}$."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert isinstance(entry["id"], str), (
        f"id must be str; got {type(entry['id']).__name__}"
    )
    assert UUID4_HEX_PATTERN.match(entry["id"]), (
        f"id {entry['id']!r} does not match uuid4 hex pattern ^[0-9a-f]{{32}}$"
    )


def test_id_is_uuid4_hex_format_close():
    """For a close entry, id must match ^[0-9a-f]{32}$."""
    from standup import _build_entry
    entry = _build_entry("close", SESSION_ID, dict(CLOSE_FIELDS))
    assert UUID4_HEX_PATTERN.match(entry["id"]), (
        f"id {entry['id']!r} does not match uuid4 hex pattern"
    )


def test_id_is_uuid4_hex_format_amend():
    """For an amend entry, id must match ^[0-9a-f]{32}$."""
    from standup import _build_entry
    entry = _build_entry(
        "amend", SESSION_ID, dict(OPEN_FIELDS), amends_id=AMENDS_ID
    )
    assert UUID4_HEX_PATTERN.match(entry["id"]), (
        f"id {entry['id']!r} does not match uuid4 hex pattern"
    )


def test_two_consecutive_calls_produce_different_ids():
    """Each call must mint a fresh id; consecutive calls must not collide."""
    from standup import _build_entry
    a = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    b = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert a["id"] != b["id"], (
        f"Two consecutive _build_entry calls produced the same id: "
        f"{a['id']!r}. Each entry must have a fresh uuid4."
    )


def test_id_distinct_from_session_id():
    """The minted entry id must not be the session_id (sanity check that
    the helper isn't reusing the session id slot for the entry id)."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert entry["id"] != SESSION_ID, (
        f"entry id collides with session_id {SESSION_ID!r}; "
        "implementation likely confused id slots"
    )


def test_many_calls_produce_unique_ids():
    """Across 50 builds, all ids must be unique (uuid4 collision odds are
    astronomically low)."""
    from standup import _build_entry
    ids = [
        _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))["id"]
        for _ in range(50)
    ]
    assert len(set(ids)) == 50, (
        f"Expected 50 unique ids across 50 calls; got {len(set(ids))}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — timestamp is fresh ISO 8601 with offset, parseable by _parse_iso
# --------------------------------------------------------------------------- #

def test_timestamp_is_string():
    """timestamp must be a string."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert isinstance(entry["timestamp"], str), (
        f"timestamp must be a string; got {type(entry['timestamp']).__name__}"
    )


def test_timestamp_parseable_by_parse_iso():
    """The timestamp must be a valid tz-aware ISO 8601 per _parse_iso's
    contract — Story 2's parser is the source of truth."""
    from standup import _build_entry, _parse_iso
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    parsed = _parse_iso(entry["timestamp"])
    assert parsed.tzinfo is not None, (
        "timestamp must be tz-aware; _parse_iso returned a naive datetime"
    )


def test_timestamp_monotonic_or_distinct_across_calls():
    """Two consecutive calls must produce timestamps that are either equal
    (same wall-clock tick) or strictly later — never out of order. Most
    runs will see strictly increasing timestamps; clock-tick collisions
    are tolerated."""
    from standup import _build_entry, _parse_iso
    a = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    b = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    ta = _parse_iso(a["timestamp"])
    tb = _parse_iso(b["timestamp"])
    assert tb >= ta, (
        f"Second call's timestamp {b['timestamp']!r} is earlier than "
        f"first call's {a['timestamp']!r}; clock went backwards"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Invalid type raises ValueError
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad_type",
    ["foo", "OPEN", "Open", "openn", " open", "open ", "", "amendment"],
    ids=[
        "foo", "OPEN-uppercase", "Open-titlecase", "openn-typo",
        "leading-space", "trailing-space", "empty-string", "amendment",
    ],
)
def test_invalid_type_string_raises_valueerror(bad_type):
    """Any string that isn't exactly 'open', 'close', or 'amend' must
    raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry(bad_type, SESSION_ID, dict(OPEN_FIELDS))


@pytest.mark.parametrize(
    "bad_type",
    [None, 0, 1, 3.14, True, [], {}, ("open",)],
    ids=["None", "int-zero", "int-one", "float", "bool", "list", "dict", "tuple"],
)
def test_non_string_type_raises(bad_type):
    """Non-string ``type`` must raise loudly. ValueError is documented in
    the spec; TypeError is also acceptable since the type check naturally
    raises one. Either is loud and unambiguous."""
    from standup import _build_entry
    with pytest.raises((ValueError, TypeError)):
        _build_entry(bad_type, SESSION_ID, dict(OPEN_FIELDS))


# --------------------------------------------------------------------------- #
# CRITERION — Empty / non-string session_id raises
# --------------------------------------------------------------------------- #

def test_empty_session_id_raises_valueerror():
    """session_id='' must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("open", "", dict(OPEN_FIELDS))


@pytest.mark.parametrize(
    "bad_sid",
    [None, 0, 42, 3.14, True, [], {}, ("sid",), b"bytes-sid"],
    ids=[
        "None", "int-zero", "int-nonzero", "float", "bool",
        "list", "dict", "tuple", "bytes",
    ],
)
def test_non_string_session_id_raises(bad_sid):
    """session_id must be a string. Non-string values raise ValueError or
    TypeError — both are acceptable per the spec."""
    from standup import _build_entry
    with pytest.raises((ValueError, TypeError)):
        _build_entry("open", bad_sid, dict(OPEN_FIELDS))


# --------------------------------------------------------------------------- #
# CRITERION — Non-dict fields raises TypeError
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad_fields",
    [
        None,
        "a string",
        42,
        3.14,
        True,
        [("yesterday", "y"), ("today", "t"), ("blockers", "b")],
        ("yesterday", "today", "blockers"),
        {"yesterday", "today", "blockers"},
        b"bytes",
    ],
    ids=[
        "None", "str", "int", "float", "bool",
        "list-of-tuples", "tuple", "set", "bytes",
    ],
)
def test_non_dict_fields_raises_typeerror(bad_fields):
    """fields must be a dict; non-dict input must raise TypeError."""
    from standup import _build_entry
    with pytest.raises(TypeError):
        _build_entry("open", SESSION_ID, bad_fields)


# --------------------------------------------------------------------------- #
# CRITERION — type='open' missing or extra keys raises ValueError
# --------------------------------------------------------------------------- #

def test_open_missing_one_key_raises_valueerror_naming_it():
    """If a required open key is absent, ValueError must mention it."""
    from standup import _build_entry
    fields = {"yesterday": "y", "today": "t"}  # missing "blockers"
    with pytest.raises(ValueError) as exc_info:
        _build_entry("open", SESSION_ID, fields)
    assert "blockers" in str(exc_info.value), (
        f"ValueError must name the missing key 'blockers'; "
        f"got message: {exc_info.value!s}"
    )


def test_open_missing_all_keys_raises_valueerror():
    """An empty fields dict for type='open' must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("open", SESSION_ID, {})


def test_open_extra_key_raises_valueerror_naming_it():
    """If an unknown key is present, ValueError must mention it."""
    from standup import _build_entry
    fields = {**OPEN_FIELDS, "shifted": "wrong-schema-key"}
    with pytest.raises(ValueError) as exc_info:
        _build_entry("open", SESSION_ID, fields)
    assert "shifted" in str(exc_info.value), (
        f"ValueError must name the extra key 'shifted'; "
        f"got message: {exc_info.value!s}"
    )


def test_open_with_close_keys_raises_valueerror():
    """Substituting the close schema for an open call is an obvious bug
    — must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("open", SESSION_ID, dict(CLOSE_FIELDS))


# --------------------------------------------------------------------------- #
# CRITERION — type='close' missing or extra keys raises ValueError
# --------------------------------------------------------------------------- #

def test_close_missing_one_key_raises_valueerror_naming_it():
    """If a required close key is absent, ValueError must mention it."""
    from standup import _build_entry
    fields = {"shifted": "s", "tomorrows_first_move": "t"}  # missing "blocking"
    with pytest.raises(ValueError) as exc_info:
        _build_entry("close", SESSION_ID, fields)
    assert "blocking" in str(exc_info.value), (
        f"ValueError must name the missing key 'blocking'; "
        f"got message: {exc_info.value!s}"
    )


def test_close_missing_all_keys_raises_valueerror():
    """An empty fields dict for type='close' must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("close", SESSION_ID, {})


def test_close_extra_key_raises_valueerror_naming_it():
    """A close call with an unknown key must raise ValueError naming the key."""
    from standup import _build_entry
    fields = {**CLOSE_FIELDS, "today": "wrong-schema-key"}
    with pytest.raises(ValueError) as exc_info:
        _build_entry("close", SESSION_ID, fields)
    assert "today" in str(exc_info.value), (
        f"ValueError must name the extra key 'today'; "
        f"got message: {exc_info.value!s}"
    )


def test_close_with_open_keys_raises_valueerror():
    """Substituting the open schema for a close call must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("close", SESSION_ID, dict(OPEN_FIELDS))


# --------------------------------------------------------------------------- #
# CRITERION — type='amend' fields must mirror open OR close
# --------------------------------------------------------------------------- #

def test_amend_with_neither_open_nor_close_shape_raises_valueerror():
    """fields keys that match neither schema must raise ValueError."""
    from standup import _build_entry
    fields = {"foo": "x", "bar": "y", "baz": "z"}
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)


def test_amend_partial_open_shape_raises_valueerror():
    """An amend with only some of the open keys is not the open schema;
    must raise ValueError."""
    from standup import _build_entry
    fields = {"yesterday": "y", "today": "t"}  # missing "blockers"
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)


def test_amend_open_with_extra_key_raises_valueerror():
    """An amend that mostly matches open but has an extra key must raise."""
    from standup import _build_entry
    fields = {**OPEN_FIELDS, "shifted": "smuggled"}
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)


def test_amend_mixing_open_and_close_keys_raises_valueerror():
    """A union of open and close keys matches NEITHER schema; must raise."""
    from standup import _build_entry
    fields = {**OPEN_FIELDS, **CLOSE_FIELDS}
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)


def test_amend_empty_fields_raises_valueerror():
    """type='amend' with empty fields must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, {}, amends_id=AMENDS_ID)


# --------------------------------------------------------------------------- #
# CRITERION — type='amend' without amends_id raises ValueError
# --------------------------------------------------------------------------- #

def test_amend_without_amends_id_raises_valueerror():
    """type='amend' with amends_id=None (the default) must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, dict(OPEN_FIELDS))


def test_amend_with_explicit_none_amends_id_raises_valueerror():
    """Passing amends_id=None explicitly is also rejected."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry(
            "amend", SESSION_ID, dict(OPEN_FIELDS), amends_id=None
        )


def test_amend_with_empty_amends_id_raises_valueerror():
    """amends_id='' is rejected — empty string is not a usable id."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("amend", SESSION_ID, dict(OPEN_FIELDS), amends_id="")


@pytest.mark.parametrize(
    "bad_amends_id",
    [0, 42, 3.14, True, [], {}, b"bytes-id"],
    ids=["int-zero", "int-nonzero", "float", "bool", "list", "dict", "bytes"],
)
def test_amend_with_non_string_amends_id_raises(bad_amends_id):
    """A non-string amends_id must raise — ValueError or TypeError both
    acceptable per spec ('must be a non-empty string; else ValueError'
    plus standard type-check semantics)."""
    from standup import _build_entry
    with pytest.raises((ValueError, TypeError)):
        _build_entry(
            "amend", SESSION_ID, dict(OPEN_FIELDS), amends_id=bad_amends_id
        )


# --------------------------------------------------------------------------- #
# CRITERION — amends_id passed with non-amend type raises ValueError
# --------------------------------------------------------------------------- #

def test_open_with_amends_id_raises_valueerror():
    """type='open' with a non-None amends_id must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry(
            "open", SESSION_ID, dict(OPEN_FIELDS), amends_id=AMENDS_ID
        )


def test_close_with_amends_id_raises_valueerror():
    """type='close' with a non-None amends_id must raise ValueError."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry(
            "close", SESSION_ID, dict(CLOSE_FIELDS), amends_id=AMENDS_ID
        )


def test_open_with_empty_amends_id_still_rejected():
    """Even an empty-string amends_id paired with type='open' is wrong:
    the spec says 'amends_id MUST be passed only with type=amend; if
    amends_id is non-None and type != amend, ValueError'. An empty string
    is non-None, therefore this must raise.

    Note: an implementation that treats falsy amends_id as 'not passed'
    would silently accept this case. The spec says non-None, so empty
    string still trips the rule."""
    from standup import _build_entry
    with pytest.raises(ValueError):
        _build_entry("open", SESSION_ID, dict(OPEN_FIELDS), amends_id="")


# --------------------------------------------------------------------------- #
# CRITERION — Non-string field VALUES raise TypeError naming the key
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad_value",
    [None, 0, 1, 3.14, True, ["a"], {"k": "v"}, ("t",), b"bytes"],
    ids=[
        "None", "int-zero", "int-nonzero", "float", "bool",
        "list", "dict", "tuple", "bytes",
    ],
)
def test_open_non_string_field_value_raises_typeerror(bad_value):
    """A non-string value in an open field must raise TypeError."""
    from standup import _build_entry
    fields = {**OPEN_FIELDS, "today": bad_value}
    with pytest.raises(TypeError) as exc_info:
        _build_entry("open", SESSION_ID, fields)
    assert "today" in str(exc_info.value), (
        f"TypeError must name the offending key 'today'; "
        f"got message: {exc_info.value!s}"
    )


def test_close_non_string_field_value_raises_typeerror_naming_key():
    """Non-string value in a close field must raise TypeError naming it."""
    from standup import _build_entry
    fields = {**CLOSE_FIELDS, "blocking": 42}
    with pytest.raises(TypeError) as exc_info:
        _build_entry("close", SESSION_ID, fields)
    assert "blocking" in str(exc_info.value), (
        f"TypeError must name the offending key 'blocking'; "
        f"got message: {exc_info.value!s}"
    )


def test_amend_non_string_field_value_raises_typeerror_naming_key():
    """Non-string value in an amend field must raise TypeError naming it."""
    from standup import _build_entry
    fields = {**OPEN_FIELDS, "yesterday": [1, 2, 3]}
    with pytest.raises(TypeError) as exc_info:
        _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)
    assert "yesterday" in str(exc_info.value), (
        f"TypeError must name the offending key 'yesterday'; "
        f"got message: {exc_info.value!s}"
    )


def test_open_none_field_value_raises_typeerror():
    """A None value in any field must be rejected as non-string."""
    from standup import _build_entry
    fields = {**OPEN_FIELDS, "blockers": None}
    with pytest.raises(TypeError) as exc_info:
        _build_entry("open", SESSION_ID, fields)
    assert "blockers" in str(exc_info.value), (
        f"TypeError must name the offending key 'blockers'; "
        f"got message: {exc_info.value!s}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Multiline string values preserved verbatim
# --------------------------------------------------------------------------- #

def test_multiline_field_value_preserved_open():
    """Newlines inside a string field VALUE must be preserved exactly.
    JSON-encoding is downstream; in the dict, newlines stay as \\n chars."""
    from standup import _build_entry
    body = "line one\nline two\nline three"
    fields = {**OPEN_FIELDS, "today": body}
    entry = _build_entry("open", SESSION_ID, fields)
    assert entry["today"] == body
    # Sanity: the newline character literally lives in the value
    assert "\n" in entry["today"]


def test_multiline_field_value_preserved_close():
    """Multiline preserved on close type as well."""
    from standup import _build_entry
    body = "shifted because:\n - reason A\n - reason B"
    fields = {**CLOSE_FIELDS, "shifted": body}
    entry = _build_entry("close", SESSION_ID, fields)
    assert entry["shifted"] == body


def test_multiline_field_value_preserved_amend():
    """Multiline preserved on amend type."""
    from standup import _build_entry
    body = "corrected:\n\n  multiple paragraphs\n\n  with blank lines\n"
    fields = {**OPEN_FIELDS, "yesterday": body}
    entry = _build_entry("amend", SESSION_ID, fields, amends_id=AMENDS_ID)
    assert entry["yesterday"] == body


def test_special_characters_in_field_values_preserved():
    """Tabs, quotes, backslashes — all preserved verbatim in the dict
    (escaping happens at JSON serialization, not here)."""
    from standup import _build_entry
    fields = {
        "yesterday": 'said "hi"',
        "today": "tab\there",
        "blockers": "back\\slash",
    }
    entry = _build_entry("open", SESSION_ID, fields)
    for k, v in fields.items():
        assert entry[k] == v, (
            f"value for {k!r} mutated: expected {v!r}, got {entry[k]!r}"
        )


def test_empty_string_field_values_allowed():
    """Empty strings ARE strings — they must be accepted as field values
    (they're 'no content', not 'wrong type'). The validator rejects the
    session_id when empty, but field values may be intentionally blank
    (e.g. blockers='')."""
    from standup import _build_entry
    fields = {"yesterday": "", "today": "", "blockers": ""}
    entry = _build_entry("open", SESSION_ID, fields)
    assert entry["yesterday"] == ""
    assert entry["today"] == ""
    assert entry["blockers"] == ""


# --------------------------------------------------------------------------- #
# EDGE CASES — adversarial guards
# --------------------------------------------------------------------------- #

def test_input_fields_dict_not_mutated():
    """The caller's fields dict must not be mutated by _build_entry.
    Side-effect-free helpers are easier to reason about and reuse."""
    from standup import _build_entry
    fields = dict(OPEN_FIELDS)
    snapshot = dict(fields)
    _build_entry("open", SESSION_ID, fields)
    assert fields == snapshot, (
        f"_build_entry mutated caller's fields dict; "
        f"before={snapshot!r} after={fields!r}"
    )


def test_returned_dict_independent_of_input():
    """Mutating the returned dict must not affect any other call's output."""
    from standup import _build_entry
    a = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    a["yesterday"] = "MUTATED"
    b = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert b["yesterday"] != "MUTATED", (
        "mutation of one entry leaked into another — shared mutable state"
    )


def test_session_id_passed_through_verbatim():
    """The session_id string must appear in the entry exactly as given,
    no transformation, no normalization."""
    from standup import _build_entry
    sid = "WeIrD-SeSsIoN_iD.123"
    entry = _build_entry("open", sid, dict(OPEN_FIELDS))
    assert entry["session_id"] == sid


def test_returned_value_is_plain_dict():
    """The returned object must be a plain dict (not e.g. a dataclass or
    custom subclass), since downstream JSON serialization expects that."""
    from standup import _build_entry
    entry = _build_entry("open", SESSION_ID, dict(OPEN_FIELDS))
    assert type(entry) is dict, (
        f"_build_entry must return a plain dict; got {type(entry).__name__}"
    )


def test_validation_failure_does_not_leak_partial_dict():
    """When validation fails, _build_entry must raise — not return a
    partially-populated dict. (Adversarial: catches an implementation that
    builds the dict first and then validates with a bare 'return None' on
    error.)"""
    from standup import _build_entry
    # Use a clearly invalid type. If the implementation returned anything
    # at all, this would silently pass.
    with pytest.raises(ValueError):
        result = _build_entry("not_a_valid_type", SESSION_ID, dict(OPEN_FIELDS))
        # If we get here without raising, the test must fail:
        pytest.fail(f"expected ValueError, got returned value: {result!r}")
