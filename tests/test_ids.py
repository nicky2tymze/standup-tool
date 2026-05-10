"""
Acceptance tests for Story 3 — Unique entry id and session id generation.

Verifies the two private helper functions in standup.py:
  - _new_entry_id() -> str
  - _new_session_id() -> str

Acceptance criteria covered:
  - Both functions are importable by name from `standup`
  - Each is callable
  - Each returns a str
  - Each returns a 32-character lowercase hex string (uuid4().hex format —
    no dashes, no prefix)
  - Format matches uuid4 hex pattern (regex + hexdigit + int(s, 16) checks)
  - Multiple consecutive calls return distinct values (rapid succession)
  - Larger sample (100 calls) yields 100 unique values
  - Both functions produce values in the SAME format — interchangeable
    surface, distinct semantic intent at call sites
  - Functions are private (underscore-prefixed); not in __all__

Stdlib only. pytest as the runner. Tests should fail meaningfully if
acceptance is violated.
"""

from __future__ import annotations

import pathlib
import re
import string
import sys
import uuid

import pytest


# --------------------------------------------------------------------------- #
# Path setup — ensure Tools/Standup/ is importable regardless of where pytest
# is invoked from. Mirrors test_skeleton.py and test_timestamps.py.
# --------------------------------------------------------------------------- #

THIS_FILE = pathlib.Path(__file__).resolve()
PACKAGE_DIR = THIS_FILE.parent.parent           # .../Tools/Standup
PACKAGE_PARENT = PACKAGE_DIR.parent              # .../Tools

for p in (str(PACKAGE_DIR), str(PACKAGE_PARENT)):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------- #
# Shared regex / character set — uuid4().hex is exactly 32 lowercase hex chars
# with no dashes and no prefix. We assert this surface explicitly.
# --------------------------------------------------------------------------- #

UUID4_HEX_PATTERN = re.compile(r"^[0-9a-f]{32}$")
HEX_LOWER = set(string.hexdigits.lower())  # '0'..'9' + 'a'..'f' (uppercase too,
                                            # but we filter to lower below)
HEX_LOWER_ONLY = set("0123456789abcdef")


# --------------------------------------------------------------------------- #
# CRITERION — Helpers are importable by name (private, but addressable)
# --------------------------------------------------------------------------- #

def test_new_entry_id_importable():
    """`from standup import _new_entry_id` must succeed."""
    from standup import _new_entry_id  # noqa: F401


def test_new_session_id_importable():
    """`from standup import _new_session_id` must succeed."""
    from standup import _new_session_id  # noqa: F401


def test_both_id_helpers_importable_together():
    """The story's exact import line must work as a single statement."""
    from standup import _new_entry_id, _new_session_id  # noqa: F401
    assert _new_entry_id is not _new_session_id, (
        "_new_entry_id and _new_session_id must be distinct function objects "
        "(named separately for call-site clarity, even if implementations match)"
    )


def test_id_helpers_are_callable():
    """Both helpers must be callable objects."""
    from standup import _new_entry_id, _new_session_id
    assert callable(_new_entry_id), "_new_entry_id must be callable"
    assert callable(_new_session_id), "_new_session_id must be callable"


# --------------------------------------------------------------------------- #
# CRITERION — Functions are private (underscore-prefixed); NOT in __all__
# --------------------------------------------------------------------------- #

def test_id_helpers_are_private_not_in_dunder_all():
    """Private helpers must not appear in __all__ (acceptance criterion).
    They remain accessible by name; just not part of the public surface."""
    import standup
    public = getattr(standup, "__all__", [])
    assert "_new_entry_id" not in public, (
        f"_new_entry_id must not be in __all__ (it is private); __all__={public}"
    )
    assert "_new_session_id" not in public, (
        f"_new_session_id must not be in __all__ (it is private); __all__={public}"
    )


def test_id_helpers_have_underscore_prefix():
    """Belt-and-suspenders: the names themselves start with underscore."""
    from standup import _new_entry_id, _new_session_id
    assert _new_entry_id.__name__.startswith("_"), (
        f"_new_entry_id name must be underscore-prefixed; got {_new_entry_id.__name__!r}"
    )
    assert _new_session_id.__name__.startswith("_"), (
        f"_new_session_id name must be underscore-prefixed; got {_new_session_id.__name__!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Each returns a string
# --------------------------------------------------------------------------- #

def test_new_entry_id_returns_string():
    """_new_entry_id() must return a str instance."""
    from standup import _new_entry_id
    result = _new_entry_id()
    assert isinstance(result, str), (
        f"_new_entry_id() must return str, got {type(result).__name__}"
    )


def test_new_session_id_returns_string():
    """_new_session_id() must return a str instance."""
    from standup import _new_session_id
    result = _new_session_id()
    assert isinstance(result, str), (
        f"_new_session_id() must return str, got {type(result).__name__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Each returns a 32-character lowercase hex string (no dashes)
# --------------------------------------------------------------------------- #

def test_new_entry_id_is_32_chars():
    """_new_entry_id() must return a string of exactly 32 characters."""
    from standup import _new_entry_id
    s = _new_entry_id()
    assert len(s) == 32, (
        f"_new_entry_id() must return a 32-char string; got len={len(s)} "
        f"for value {s!r}"
    )


def test_new_session_id_is_32_chars():
    """_new_session_id() must return a string of exactly 32 characters."""
    from standup import _new_session_id
    s = _new_session_id()
    assert len(s) == 32, (
        f"_new_session_id() must return a 32-char string; got len={len(s)} "
        f"for value {s!r}"
    )


def test_new_entry_id_is_lowercase_hex():
    """_new_entry_id() output must contain only lowercase hex characters
    (0-9, a-f). No uppercase, no dashes, no whitespace, no prefix."""
    from standup import _new_entry_id
    s = _new_entry_id()
    extra = set(s) - HEX_LOWER_ONLY
    assert not extra, (
        f"_new_entry_id() must contain only lowercase hex chars [0-9a-f]; "
        f"found unexpected characters {extra!r} in {s!r}"
    )


def test_new_session_id_is_lowercase_hex():
    """_new_session_id() output must contain only lowercase hex characters
    (0-9, a-f). No uppercase, no dashes, no whitespace, no prefix."""
    from standup import _new_session_id
    s = _new_session_id()
    extra = set(s) - HEX_LOWER_ONLY
    assert not extra, (
        f"_new_session_id() must contain only lowercase hex chars [0-9a-f]; "
        f"found unexpected characters {extra!r} in {s!r}"
    )


def test_new_entry_id_has_no_dashes():
    """Adversarial check: uuid4().hex strips dashes; raw str(uuid4()) keeps
    them. This catches the bug of returning str(uuid4()) instead of .hex."""
    from standup import _new_entry_id
    s = _new_entry_id()
    assert "-" not in s, (
        f"_new_entry_id() must not contain dashes (uuid4().hex format); "
        f"got {s!r}. Did the implementation use str(uuid4()) instead of .hex?"
    )


def test_new_session_id_has_no_dashes():
    """Adversarial check: uuid4().hex strips dashes; raw str(uuid4()) keeps
    them. This catches the bug of returning str(uuid4()) instead of .hex."""
    from standup import _new_session_id
    s = _new_session_id()
    assert "-" not in s, (
        f"_new_session_id() must not contain dashes (uuid4().hex format); "
        f"got {s!r}. Did the implementation use str(uuid4()) instead of .hex?"
    )


def test_new_entry_id_has_no_prefix_or_whitespace():
    """No leading/trailing whitespace, no 'urn:' or 'uuid:' prefix."""
    from standup import _new_entry_id
    s = _new_entry_id()
    assert s == s.strip(), (
        f"_new_entry_id() must not contain leading/trailing whitespace; got {s!r}"
    )
    assert ":" not in s, (
        f"_new_entry_id() must not include any prefix like 'urn:' or 'uuid:'; got {s!r}"
    )


def test_new_session_id_has_no_prefix_or_whitespace():
    """No leading/trailing whitespace, no 'urn:' or 'uuid:' prefix."""
    from standup import _new_session_id
    s = _new_session_id()
    assert s == s.strip(), (
        f"_new_session_id() must not contain leading/trailing whitespace; got {s!r}"
    )
    assert ":" not in s, (
        f"_new_session_id() must not include any prefix like 'urn:' or 'uuid:'; got {s!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Format matches uuid4 hex pattern (regex)
# --------------------------------------------------------------------------- #

def test_new_entry_id_matches_uuid4_hex_pattern():
    """_new_entry_id() must match ^[0-9a-f]{32}$ exactly."""
    from standup import _new_entry_id
    s = _new_entry_id()
    assert UUID4_HEX_PATTERN.match(s), (
        f"_new_entry_id() {s!r} does not match uuid4 hex pattern "
        f"^[0-9a-f]{{32}}$"
    )


def test_new_session_id_matches_uuid4_hex_pattern():
    """_new_session_id() must match ^[0-9a-f]{32}$ exactly."""
    from standup import _new_session_id
    s = _new_session_id()
    assert UUID4_HEX_PATTERN.match(s), (
        f"_new_session_id() {s!r} does not match uuid4 hex pattern "
        f"^[0-9a-f]{{32}}$"
    )


def test_new_entry_id_is_valid_hex_int():
    """The returned string must be parseable as a base-16 integer (i.e.,
    every character is a valid hex digit)."""
    from standup import _new_entry_id
    s = _new_entry_id()
    # int(s, 16) raises ValueError on any non-hex char; this is the
    # canonical hex-validity check.
    int(s, 16)


def test_new_session_id_is_valid_hex_int():
    """The returned string must be parseable as a base-16 integer."""
    from standup import _new_session_id
    s = _new_session_id()
    int(s, 16)


def test_new_entry_id_roundtrips_through_uuid_constructor():
    """The 32-char hex must be acceptable as input to uuid.UUID(hex=...).
    This is the strongest possible check: it confirms the value is a valid
    UUID hex representation per the stdlib uuid module's own contract."""
    from standup import _new_entry_id
    s = _new_entry_id()
    u = uuid.UUID(hex=s)
    assert u.hex == s, (
        f"_new_entry_id() output {s!r} did not round-trip through "
        f"uuid.UUID(hex=...).hex (got {u.hex!r})"
    )


def test_new_session_id_roundtrips_through_uuid_constructor():
    """The 32-char hex must be acceptable as input to uuid.UUID(hex=...).
    Confirms valid UUID hex representation per stdlib's own contract."""
    from standup import _new_session_id
    s = _new_session_id()
    u = uuid.UUID(hex=s)
    assert u.hex == s, (
        f"_new_session_id() output {s!r} did not round-trip through "
        f"uuid.UUID(hex=...).hex (got {u.hex!r})"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Both functions produce values in the SAME format
# (interchangeable surface; distinct names for call-site clarity)
# --------------------------------------------------------------------------- #

def test_both_id_helpers_produce_same_format():
    """Output from each helper must match the same regex pattern.
    Per story: 'Both functions can be used interchangeably (same format)'."""
    from standup import _new_entry_id, _new_session_id
    entry = _new_entry_id()
    session = _new_session_id()
    assert UUID4_HEX_PATTERN.match(entry), (
        f"_new_entry_id() {entry!r} fails uuid4 hex pattern"
    )
    assert UUID4_HEX_PATTERN.match(session), (
        f"_new_session_id() {session!r} fails uuid4 hex pattern"
    )
    assert len(entry) == len(session) == 32, (
        f"Both helpers must return 32-char strings; got "
        f"entry-len={len(entry)}, session-len={len(session)}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Multiple consecutive calls return distinct values
# --------------------------------------------------------------------------- #

def test_new_entry_id_two_consecutive_calls_distinct():
    """Two _new_entry_id() calls in rapid succession must yield different
    strings (uuid4 randomness guarantees this with overwhelming probability)."""
    from standup import _new_entry_id
    a = _new_entry_id()
    b = _new_entry_id()
    assert a != b, (
        f"Consecutive _new_entry_id() calls returned identical values: {a!r}. "
        f"This suggests a fixed-seed or cached implementation, not uuid4."
    )


def test_new_session_id_two_consecutive_calls_distinct():
    """Two _new_session_id() calls in rapid succession must yield different
    strings (uuid4 randomness guarantees this with overwhelming probability)."""
    from standup import _new_session_id
    a = _new_session_id()
    b = _new_session_id()
    assert a != b, (
        f"Consecutive _new_session_id() calls returned identical values: {a!r}. "
        f"This suggests a fixed-seed or cached implementation, not uuid4."
    )


def test_entry_and_session_ids_do_not_collide():
    """Even across functions, an entry id and a session id generated back-to-back
    must not collide. Catches the (silly but possible) bug of both returning
    the same cached value."""
    from standup import _new_entry_id, _new_session_id
    entry = _new_entry_id()
    session = _new_session_id()
    assert entry != session, (
        f"_new_entry_id() and _new_session_id() returned the same value "
        f"{entry!r}; expected distinct uuid4 hex strings."
    )


# --------------------------------------------------------------------------- #
# EDGE CASES — larger samples, stress, distribution sanity
# --------------------------------------------------------------------------- #

def test_new_entry_id_100_calls_all_unique():
    """100 calls to _new_entry_id() must yield 100 distinct values.
    uuid4's collision probability is astronomically below 1 in 100^2."""
    from standup import _new_entry_id
    values = [_new_entry_id() for _ in range(100)]
    unique = set(values)
    assert len(unique) == 100, (
        f"_new_entry_id() produced duplicates in a sample of 100: "
        f"{len(unique)} unique values. Likely a non-uuid4 implementation."
    )


def test_new_session_id_100_calls_all_unique():
    """100 calls to _new_session_id() must yield 100 distinct values."""
    from standup import _new_session_id
    values = [_new_session_id() for _ in range(100)]
    unique = set(values)
    assert len(unique) == 100, (
        f"_new_session_id() produced duplicates in a sample of 100: "
        f"{len(unique)} unique values. Likely a non-uuid4 implementation."
    )


def test_mixed_pool_of_ids_all_unique():
    """A mixed pool of 100 entry ids + 100 session ids must contain
    200 distinct values. Catches shared-state bugs across the two helpers."""
    from standup import _new_entry_id, _new_session_id
    pool = [_new_entry_id() for _ in range(100)] + [_new_session_id() for _ in range(100)]
    assert len(set(pool)) == 200, (
        f"Mixed entry/session id pool of 200 produced only "
        f"{len(set(pool))} unique values; the helpers may share cached state."
    )


def test_new_entry_id_format_stable_across_many_calls():
    """Across 100 calls, every value must satisfy the format invariants
    (32 chars, lowercase hex, regex match). Catches an intermittent bug
    where the format is not deterministic."""
    from standup import _new_entry_id
    for i in range(100):
        s = _new_entry_id()
        assert len(s) == 32, (
            f"call #{i}: _new_entry_id() returned len={len(s)}: {s!r}"
        )
        assert UUID4_HEX_PATTERN.match(s), (
            f"call #{i}: _new_entry_id() returned non-matching value {s!r}"
        )


def test_new_session_id_format_stable_across_many_calls():
    """Across 100 calls, every value must satisfy the format invariants."""
    from standup import _new_session_id
    for i in range(100):
        s = _new_session_id()
        assert len(s) == 32, (
            f"call #{i}: _new_session_id() returned len={len(s)}: {s!r}"
        )
        assert UUID4_HEX_PATTERN.match(s), (
            f"call #{i}: _new_session_id() returned non-matching value {s!r}"
        )


def test_id_helpers_take_no_arguments():
    """Per the story signature `_new_entry_id() -> str` and
    `_new_session_id() -> str`, the helpers must be callable with zero
    positional arguments. Calling with no args must succeed."""
    from standup import _new_entry_id, _new_session_id
    # If either of these raises TypeError, the signature is wrong.
    _new_entry_id()
    _new_session_id()
