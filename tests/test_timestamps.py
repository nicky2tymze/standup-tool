"""
Acceptance tests for Story 2 — ISO 8601 local-offset timestamp helpers.

Verifies the two private helper functions in standup.py:
  - _now_iso() -> str
  - _parse_iso(s: str) -> datetime.datetime

Acceptance criteria covered:
  - Both functions are importable by name from `standup`
  - _now_iso() returns a non-empty string
  - _now_iso() returns a string parseable by datetime.fromisoformat()
  - _now_iso() output is timezone-aware (parsed datetime has tzinfo set)
  - _now_iso() includes a recognizable offset (verified via parsing,
    not just regex)
  - _parse_iso() returns a datetime.datetime instance
  - _parse_iso() returns a timezone-aware datetime
  - Round-trip integrity: _parse_iso(_now_iso()) yields the same UTC
    instant when re-formatted and re-parsed
  - _parse_iso() raises ValueError on garbage input (not silent None)
  - Functions are private (underscore-prefixed); not in __all__

Stdlib only. pytest as the runner. Tests should fail meaningfully if
acceptance is violated.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import re
import sys

import pytest


# --------------------------------------------------------------------------- #
# Path setup — ensure Tools/Standup/ is importable regardless of where pytest
# is invoked from. Mirrors test_skeleton.py.
# --------------------------------------------------------------------------- #

THIS_FILE = pathlib.Path(__file__).resolve()
PACKAGE_DIR = THIS_FILE.parent.parent           # .../Tools/Standup
PACKAGE_PARENT = PACKAGE_DIR.parent              # .../Tools

for p in (str(PACKAGE_DIR), str(PACKAGE_PARENT)):
    if p not in sys.path:
        sys.path.insert(0, p)


# --------------------------------------------------------------------------- #
# CRITERION — Helpers are importable by name (private, but addressable)
# --------------------------------------------------------------------------- #

def test_now_iso_importable():
    """`from standup import _now_iso` must succeed."""
    from standup import _now_iso  # noqa: F401


def test_parse_iso_importable():
    """`from standup import _parse_iso` must succeed."""
    from standup import _parse_iso  # noqa: F401


def test_helpers_are_callable():
    """Both helpers must be callable objects."""
    from standup import _now_iso, _parse_iso
    assert callable(_now_iso), "_now_iso must be callable"
    assert callable(_parse_iso), "_parse_iso must be callable"


def test_helpers_are_private_not_in_dunder_all():
    """Private helpers must not appear in __all__ (acceptance criterion).
    They remain accessible by name; just not part of the public surface."""
    import standup
    public = getattr(standup, "__all__", [])
    assert "_now_iso" not in public, (
        f"_now_iso must not be in __all__ (it is private); __all__={public}"
    )
    assert "_parse_iso" not in public, (
        f"_parse_iso must not be in __all__ (it is private); __all__={public}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — _now_iso() returns a string
# --------------------------------------------------------------------------- #

def test_now_iso_returns_string():
    """_now_iso() must return a str instance."""
    from standup import _now_iso
    result = _now_iso()
    assert isinstance(result, str), (
        f"_now_iso() must return str, got {type(result).__name__}"
    )


def test_now_iso_returns_non_empty_string():
    """_now_iso() must return a non-empty string."""
    from standup import _now_iso
    result = _now_iso()
    assert result, "_now_iso() must not return an empty string"
    assert result.strip() == result, (
        "_now_iso() must not return whitespace-padded output"
    )


# --------------------------------------------------------------------------- #
# CRITERION — _now_iso() output is parseable by datetime.fromisoformat()
# --------------------------------------------------------------------------- #

def test_now_iso_parseable_by_fromisoformat():
    """The string returned by _now_iso() must be parseable by
    datetime.fromisoformat() (the stdlib convention; no custom format)."""
    from standup import _now_iso
    s = _now_iso()
    # If this raises, the format is non-standard — fail meaningfully.
    parsed = _dt.datetime.fromisoformat(s)
    assert isinstance(parsed, _dt.datetime), (
        f"fromisoformat({s!r}) must yield a datetime, got {type(parsed).__name__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — _now_iso() carries a timezone offset (timezone-aware)
# --------------------------------------------------------------------------- #

def test_now_iso_string_includes_timezone_offset():
    """_now_iso() must include a timezone offset — verified by parsing
    and inspecting tzinfo, not by regex alone (per story instructions).

    Acceptable forms include trailing 'Z', '+HH:MM', '-HH:MM', or any
    offset that fromisoformat understands and that yields tzinfo != None.
    """
    from standup import _now_iso
    s = _now_iso()
    parsed = _dt.datetime.fromisoformat(s)
    assert parsed.tzinfo is not None, (
        f"_now_iso() must produce a timezone-aware string; tzinfo was None "
        f"after parsing {s!r}"
    )
    # utcoffset() must not be None for a tz-aware datetime
    assert parsed.utcoffset() is not None, (
        f"_now_iso() output must have a concrete UTC offset; got None for {s!r}"
    )


def test_now_iso_string_has_offset_pattern_at_end():
    """Adversarial regex check: the string should end with either 'Z' or
    a [+-]HH:MM offset. This catches accidental 'naive ISO' output that
    fromisoformat in newer Pythons would still accept as offset-less.

    NOTE: The authoritative check is the tzinfo test above; this regex
    is a belt-and-suspenders sanity check on the surface form.
    """
    from standup import _now_iso
    s = _now_iso()
    # Match either trailing Z, or [+-]HH:MM (with optional trailing colon-less
    # form for tolerance — fromisoformat on 3.11+ accepts both).
    pattern = re.compile(r"(Z|[+-]\d{2}:?\d{2})$")
    assert pattern.search(s), (
        f"_now_iso() string {s!r} does not end with a recognizable timezone "
        f"offset (expected trailing 'Z' or '[+-]HH:MM')"
    )


# --------------------------------------------------------------------------- #
# CRITERION — _parse_iso() returns a timezone-aware datetime
# --------------------------------------------------------------------------- #

def test_parse_iso_returns_datetime():
    """_parse_iso() must return a datetime.datetime instance."""
    from standup import _now_iso, _parse_iso
    parsed = _parse_iso(_now_iso())
    assert isinstance(parsed, _dt.datetime), (
        f"_parse_iso() must return datetime, got {type(parsed).__name__}"
    )


def test_parse_iso_result_is_timezone_aware():
    """_parse_iso() must return a timezone-aware datetime (tzinfo set)."""
    from standup import _now_iso, _parse_iso
    parsed = _parse_iso(_now_iso())
    assert parsed.tzinfo is not None, (
        "_parse_iso() must return a timezone-aware datetime; tzinfo was None"
    )
    assert parsed.utcoffset() is not None, (
        "_parse_iso() result must have a concrete UTC offset (utcoffset() != None)"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Round-trip integrity
# --------------------------------------------------------------------------- #

def test_round_trip_same_utc_instant():
    """parse(now()) yields a datetime; converting that datetime back to
    UTC must equal parse(now())'s UTC representation. Round trip preserves
    the instant, even if surface representation (offset notation) varies."""
    from standup import _now_iso, _parse_iso
    s1 = _now_iso()
    dt1 = _parse_iso(s1)
    # Re-format via isoformat (the stdlib inverse of fromisoformat),
    # then re-parse. The re-parsed datetime must represent the same UTC
    # instant as the original.
    s2 = dt1.isoformat()
    dt2 = _parse_iso(s2)
    assert dt1.astimezone(_dt.timezone.utc) == dt2.astimezone(_dt.timezone.utc), (
        f"Round-trip failed: {s1!r} -> {dt1!r} -> {s2!r} -> {dt2!r} "
        f"(UTC instants differ)"
    )


def test_round_trip_microseconds_preserved_if_present():
    """If _now_iso() includes microseconds, _parse_iso must preserve them
    through the round-trip (no silent truncation)."""
    from standup import _now_iso, _parse_iso
    s = _now_iso()
    parsed = _parse_iso(s)
    # If the surface string has a fractional-second component, the parsed
    # datetime must have a non-trivial microsecond field that survives
    # re-serialization.
    if "." in s:
        s2 = parsed.isoformat()
        parsed2 = _parse_iso(s2)
        assert parsed.microsecond == parsed2.microsecond, (
            f"Microseconds lost in round-trip: {parsed.microsecond} -> "
            f"{parsed2.microsecond} (original {s!r})"
        )


def test_round_trip_via_now_iso_and_parse_iso_only():
    """Strict round-trip using only the two helpers (not stdlib isoformat)."""
    from standup import _now_iso, _parse_iso
    s = _now_iso()
    parsed = _parse_iso(s)
    # Verify the parsed instant equals the literal interpretation of s.
    reference = _dt.datetime.fromisoformat(s)
    assert parsed.astimezone(_dt.timezone.utc) == reference.astimezone(_dt.timezone.utc), (
        f"_parse_iso disagrees with datetime.fromisoformat on input {s!r}: "
        f"{parsed!r} vs {reference!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — _parse_iso() accepts multiple valid ISO 8601 forms
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("iso_input", [
    "2026-05-08T14:32:11-05:00",                # offset, no microseconds
    "2026-05-08T14:32:11.123456-05:00",         # offset + microseconds
    "2026-05-08T14:32:11+00:00",                # explicit UTC offset
    "2026-05-08T14:32:11.000001+09:30",         # fractional + half-hour offset
    "2026-12-31T23:59:59.999999-08:00",         # year-end edge
])
def test_parse_iso_accepts_valid_iso_strings(iso_input):
    """_parse_iso() must accept a range of valid ISO 8601 inputs and
    return a timezone-aware datetime for each."""
    from standup import _parse_iso
    result = _parse_iso(iso_input)
    assert isinstance(result, _dt.datetime), (
        f"_parse_iso({iso_input!r}) must return datetime, "
        f"got {type(result).__name__}"
    )
    assert result.tzinfo is not None, (
        f"_parse_iso({iso_input!r}) must return tz-aware datetime; tzinfo was None"
    )


def test_parse_iso_accepts_z_suffix_if_supported():
    """ISO 8601 'Z' suffix denotes UTC. If the implementation supports it
    (most stdlib-based parsers do on Python 3.11+), it must yield a
    timezone-aware datetime equivalent to UTC. If unsupported on the target
    Python, this raises ValueError — also acceptable, but tested separately
    so we surface the behavior either way."""
    from standup import _parse_iso
    iso_z = "2026-05-08T14:32:11Z"
    try:
        result = _parse_iso(iso_z)
    except ValueError:
        pytest.skip("_parse_iso does not accept 'Z' suffix on this Python")
    assert result.tzinfo is not None, (
        "_parse_iso accepted 'Z' suffix but returned a naive datetime"
    )
    assert result.utcoffset() == _dt.timedelta(0), (
        f"'Z' suffix must mean UTC offset zero, got {result.utcoffset()}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — _parse_iso() raises ValueError on garbage input
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("garbage", [
    "",                                # empty
    "not a date at all",               # plain garbage
    "2026/05/08 14:32:11",             # wrong separator
    "May 8, 2026 2:32 PM",             # human-readable, not ISO
    "2026-13-40T99:99:99-05:00",       # syntactically ISO-shaped but invalid
    "2026-05-08",                      # date-only — no time component
])
def test_parse_iso_raises_on_garbage(garbage):
    """_parse_iso() must raise ValueError on invalid input — not return
    None, not return a naive datetime, not silently swallow the error."""
    from standup import _parse_iso
    with pytest.raises(ValueError):
        _parse_iso(garbage)


def test_parse_iso_raises_on_non_string_input():
    """_parse_iso() must reject non-string input loudly. Passing None or
    a number must raise (TypeError or ValueError — either is acceptable;
    silent acceptance is not).
    """
    from standup import _parse_iso
    with pytest.raises((TypeError, ValueError, AttributeError)):
        _parse_iso(None)  # type: ignore[arg-type]
    with pytest.raises((TypeError, ValueError, AttributeError)):
        _parse_iso(12345)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# EDGE CASES — adversarial checks beyond minimum criteria
# --------------------------------------------------------------------------- #

def test_now_iso_two_calls_are_monotonic_or_equal():
    """Two consecutive _now_iso() calls must produce strings whose parsed
    UTC instants are non-decreasing. Catches accidental wall-clock reverses
    (e.g., from caching a fixed value, or returning naive datetimes with
    inconsistent tz handling)."""
    from standup import _now_iso, _parse_iso
    a = _parse_iso(_now_iso())
    b = _parse_iso(_now_iso())
    assert a.astimezone(_dt.timezone.utc) <= b.astimezone(_dt.timezone.utc), (
        f"_now_iso() went backwards: {a!r} -> {b!r}"
    )


def test_now_iso_close_to_system_clock():
    """The instant produced by _now_iso() must be close to system time —
    within a generous window (5 seconds). Catches an accidental hardcoded
    timestamp or a frozen clock."""
    from standup import _now_iso, _parse_iso
    before = _dt.datetime.now(_dt.timezone.utc)
    parsed = _parse_iso(_now_iso())
    after = _dt.datetime.now(_dt.timezone.utc)
    parsed_utc = parsed.astimezone(_dt.timezone.utc)
    # Allow a generous window for slow CI runners.
    assert (before - _dt.timedelta(seconds=5)) <= parsed_utc <= (after + _dt.timedelta(seconds=5)), (
        f"_now_iso() time {parsed_utc!r} not within 5s of system clock "
        f"window [{before!r}, {after!r}]"
    )


def test_now_iso_uses_local_offset_not_utc_unless_machine_is_utc():
    """_now_iso() must use the LOCAL timezone offset (per acceptance).
    On a machine in UTC this would be +00:00 / Z, which is fine — so we
    can only assert that the offset matches the local system offset.

    This catches the bug where a developer hardcodes timezone.utc instead
    of using astimezone() to derive local offset.
    """
    from standup import _now_iso, _parse_iso
    parsed = _parse_iso(_now_iso())
    # System's current local offset (matches astimezone() with no arg).
    local_now = _dt.datetime.now().astimezone()
    expected_offset = local_now.utcoffset()
    actual_offset = parsed.utcoffset()
    assert actual_offset == expected_offset, (
        f"_now_iso() offset {actual_offset!r} does not match local system "
        f"offset {expected_offset!r}"
    )
