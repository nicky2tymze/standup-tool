"""
Acceptance tests for Story 12 — history(window) public function.

Rolls up to PO v2 Requirement 7 (history view, this week / last month,
plain text).

Verifies the public function

    history(window: str) -> str

in ``standup``. history is the read-only public surface that:
  - Reads existing entries via ``_read_entries`` (Story 6) — never writes
  - Parses each entry's timestamp via ``_parse_iso`` (Story 2)
  - Filters to a rolling window from "now":
        "this week"  -> trailing 7 days
        "last month" -> trailing 30 days
  - Returns a plain-text rendering of the surviving entries:
        - grouped by their local-calendar date (YYYY-MM-DD header)
        - within a date group, ordered by timestamp ascending
        - date groups themselves ordered chronologically (oldest first)
        - each entry rendered as: TYPE TIMESTAMP followed by its
          field key=value pairs (multiline-friendly)
  - On an empty window, returns a documented empty-state string
    (NOT an exception, NOT the literal empty string)
  - On any window value other than "this week" or "last month", raises
    ``ValueError`` whose message names the offending value AND lists
    the valid options
  - Output is a plain ``str`` containing zero ANSI escape codes

Story 12 retires the Story-1 stub state for history (no longer raises
NotImplementedError); only the body changes — the signature stays
identical to the stub: ``history(window: str) -> str``.

Test isolation:
  - every test that touches the log monkeypatches ``standup.LOG_PATH``
    to a per-test ``tmp_path / "log.jsonl"`` so the real
    ``Tools/Standup/log.jsonl`` is never touched
  - logs are built either by writing JSONL strings directly (so
    timestamps can be pinned to specific offsets from "now") OR via
    ``submit_open`` / ``close_standup`` for live-clock content — both
    paths are exercised

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import datetime as _dt
import importlib
import inspect
import json
import pathlib
import re
import sys
import typing

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


# Any \x1b byte indicates an ANSI escape; the spec mandates pure text.
ANSI_ESC_RE = re.compile(r"\x1b")
DATE_HEADER_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# --------------------------------------------------------------------------- #
# Timestamp helpers — produce ISO 8601 strings with the local system's
# offset, exactly the way ``_now_iso`` does in production. Pinning offsets
# from "now" lets each test land entries inside / outside the rolling
# window deterministically.
# --------------------------------------------------------------------------- #

def _local_now() -> _dt.datetime:
    """Current local time, tz-aware. Mirrors what history will compare
    its rolling window against."""
    return _dt.datetime.now().astimezone()


def _iso_offset(delta: _dt.timedelta) -> str:
    """Return an ISO 8601 string for ``now + delta`` with local offset."""
    return (_local_now() + delta).isoformat()


def _make_entry(
    timestamp: str,
    type: str = "open",
    entry_id: str = "id-default",
    session_id: str = "session-default",
    extra: dict | None = None,
) -> dict:
    """Build a minimal entry dict the history renderer can ingest.

    Default shape is an "open" entry. Tests override ``type`` and
    ``extra`` to construct close / amend variants.
    """
    e: dict = {
        "id": entry_id,
        "session_id": session_id,
        "type": type,
        "timestamp": timestamp,
    }
    if type == "open":
        e.setdefault("yesterday", "y-stub")
        e.setdefault("today", "t-stub")
        e.setdefault("blockers", "b-stub")
    elif type == "close":
        e.setdefault("shifted", "s-stub")
        e.setdefault("tomorrows_first_move", "tfm-stub")
        e.setdefault("blocking", "bl-stub")
    if extra:
        e.update(extra)
    return e


# --------------------------------------------------------------------------- #
# Fixtures
#
# isolated_log: monkeypatches ``standup.LOG_PATH`` to a per-test tmp file
#               (file does NOT exist on entry — exercises the missing-log
#               codepath by default).
# write_entries: helper that writes a list of dicts as JSONL to that file
#               so each test can pin timestamps directly.
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Monkeypatch ``standup.LOG_PATH`` to a per-test tmp file.

    Reload defensively so a previous test's monkeypatch can't leak.
    """
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file


@pytest.fixture
def write_entries(isolated_log):
    """Return a helper that writes a list of entry dicts as JSONL.

    One entry per physical line, file order preserved. Tests that need
    raw control over timestamps go this route (vs submit_open /
    close_standup which use _now_iso).
    """
    def _write(entries):
        lines = "".join(
            json.dumps(e, ensure_ascii=False) + "\n" for e in entries
        )
        isolated_log.write_text(lines, encoding="utf-8")
        return isolated_log
    return _write


# --------------------------------------------------------------------------- #
# CRITERION — history is importable from `standup`
# --------------------------------------------------------------------------- #

def test_history_importable():
    """`from standup import history` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import history  # noqa: F401
    assert callable(history)


def test_history_is_attribute_on_module():
    """The function must live on the standup module."""
    import standup
    assert hasattr(standup, "history"), (
        "standup module must define history"
    )
    assert callable(standup.history)


# --------------------------------------------------------------------------- #
# CRITERION — history is in __all__ (public)
# --------------------------------------------------------------------------- #

def test_history_in_dunder_all():
    """history must be exported via __all__ (Story 1 already added it;
    Story 12 must not remove it)."""
    import standup
    assert "history" in standup.__all__, (
        f"history must be public (listed in __all__); "
        f"current __all__ = {standup.__all__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — history no longer raises NotImplementedError
# (Story 12 replaces the Story-1 stub with a working implementation)
# --------------------------------------------------------------------------- #

def test_history_no_longer_raises_not_implemented(isolated_log):
    """A valid call must not raise NotImplementedError. Story 12 retires
    the Story-1 stub state; this test pins the transition."""
    from standup import history
    try:
        history("this week")
    except NotImplementedError as exc:
        pytest.fail(
            "history must no longer raise NotImplementedError "
            f"after Story 12; got: {exc!r}"
        )


def test_history_no_longer_raises_not_implemented_last_month(isolated_log):
    """Same transition check for the other valid window."""
    from standup import history
    try:
        history("last month")
    except NotImplementedError as exc:
        pytest.fail(
            "history must no longer raise NotImplementedError for "
            f"'last month' after Story 12; got: {exc!r}"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: 1 required positional param, returns str
# (signature unchanged from the Story-1 stub)
# --------------------------------------------------------------------------- #

def test_history_signature_param_names():
    """Parameter list must be exactly ['window']."""
    from standup import history
    sig = inspect.signature(history)
    assert list(sig.parameters.keys()) == ["window"], (
        f"history must accept exactly ['window']; got "
        f"{list(sig.parameters.keys())}"
    )


def test_history_signature_param_count():
    """Exactly 1 parameter — no more, no less."""
    from standup import history
    sig = inspect.signature(history)
    assert len(sig.parameters) == 1, (
        f"history must take 1 parameter; got {len(sig.parameters)}"
    )


def test_history_signature_param_required():
    """``window`` must be a required parameter (no default)."""
    from standup import history
    sig = inspect.signature(history)
    p = sig.parameters["window"]
    assert p.default is inspect.Parameter.empty, (
        f"history parameter 'window' must be required; got default "
        f"{p.default!r}"
    )


def test_history_signature_no_varargs_or_kwargs():
    """Adversarial: guard against ``def history(*a, **kw)`` style."""
    from standup import history
    sig = inspect.signature(history)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"history must not accept *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_history_signature_window_is_positional():
    """The window parameter must be callable positionally."""
    from standup import history
    sig = inspect.signature(history)
    p = sig.parameters["window"]
    assert p.kind in (
        inspect.Parameter.POSITIONAL_ONLY,
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
    ), (
        f"history parameter 'window' must be positional; got kind {p.kind}"
    )


def test_history_return_type_annotation_is_str():
    """The return-type hint must be ``str`` (signature unchanged)."""
    from standup import history
    hints = typing.get_type_hints(history)
    assert hints.get("return") is str, (
        f"history return annotation must be str; got {hints.get('return')}"
    )


def test_history_window_type_annotation_is_str():
    """The window-parameter hint must be ``str`` (signature unchanged)."""
    from standup import history
    hints = typing.get_type_hints(history)
    assert hints.get("window") is str, (
        f"history window annotation must be str; got {hints.get('window')}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Return type is str
# --------------------------------------------------------------------------- #

def test_history_returns_str_on_empty_log_this_week(isolated_log):
    """Return value must be a ``str`` even when the log is missing."""
    from standup import history
    out = history("this week")
    assert isinstance(out, str), (
        f"history must return str; got {type(out).__name__}"
    )


def test_history_returns_str_on_empty_log_last_month(isolated_log):
    """Return value must be a ``str`` even when the log is missing."""
    from standup import history
    out = history("last month")
    assert isinstance(out, str), (
        f"history must return str; got {type(out).__name__}"
    )


def test_history_returns_str_with_content(write_entries):
    """Return value must be a ``str`` when content is present, too."""
    write_entries([
        _make_entry(_iso_offset(_dt.timedelta(hours=-2)), entry_id="e1")
    ])
    from standup import history
    out = history("this week")
    assert isinstance(out, str), (
        f"history must return str; got {type(out).__name__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Empty window returns a documented empty-state string
# (NOT an exception, NOT the literal empty string)
# --------------------------------------------------------------------------- #

def test_empty_log_returns_non_empty_empty_state_this_week(isolated_log):
    """Missing log + 'this week' must return a non-empty empty-state
    string, not raise and not return ''."""
    from standup import history
    out = history("this week")
    assert isinstance(out, str)
    assert out != "", (
        "history must return a documented empty-state string for an "
        "empty window, not the literal empty string"
    )
    assert out.strip(), (
        "empty-state string must contain at least some non-whitespace "
        f"content; got {out!r}"
    )


def test_empty_log_returns_non_empty_empty_state_last_month(isolated_log):
    """Missing log + 'last month' must return a non-empty empty-state
    string, not raise and not return ''."""
    from standup import history
    out = history("last month")
    assert isinstance(out, str)
    assert out != ""
    assert out.strip()


def test_empty_log_empty_state_does_not_raise(isolated_log):
    """An empty / missing log must NOT raise from history."""
    from standup import history
    # If this raises, pytest reports the exception and fails the test.
    history("this week")
    history("last month")


def test_existing_empty_log_returns_empty_state(isolated_log):
    """A log file that exists but has zero bytes returns the empty-state
    string for both windows."""
    isolated_log.write_text("", encoding="utf-8")
    from standup import history
    assert history("this week").strip() != ""
    assert history("last month").strip() != ""


def test_all_entries_outside_window_returns_empty_state(write_entries):
    """A log full of entries that all fall outside the requested window
    returns the empty-state string (not an empty string, not a header
    with no body)."""
    # All entries are 60 days back — outside both 7d and 30d windows.
    far_back = _iso_offset(_dt.timedelta(days=-60))
    write_entries([
        _make_entry(far_back, entry_id="old-1", session_id="sess-old"),
        _make_entry(far_back, entry_id="old-2", session_id="sess-old"),
    ])
    from standup import history
    out_week = history("this week")
    out_month = history("last month")
    assert "old-1" not in out_week and "old-2" not in out_week
    assert "old-1" not in out_month and "old-2" not in out_month
    # And the empty-state string is non-empty:
    assert out_week.strip() != ""
    assert out_month.strip() != ""


# --------------------------------------------------------------------------- #
# CRITERION — Single entry within window: rendering contains the entry's
# content
# --------------------------------------------------------------------------- #

def test_single_recent_open_entry_appears_in_this_week(write_entries):
    """An open entry from a few hours ago must appear in 'this week'
    output. Field values must be visible somewhere in the rendering."""
    ts = _iso_offset(_dt.timedelta(hours=-3))
    write_entries([
        _make_entry(
            ts,
            type="open",
            entry_id="e1",
            session_id="sess-1",
            extra={
                "yesterday": "y-content",
                "today": "t-content",
                "blockers": "b-content",
            },
        )
    ])
    from standup import history
    out = history("this week")
    assert "y-content" in out
    assert "t-content" in out
    assert "b-content" in out


def test_single_recent_close_entry_appears_in_this_week(write_entries):
    """A close entry from a few hours ago must appear in 'this week'
    output with all three close fields visible."""
    ts = _iso_offset(_dt.timedelta(hours=-2))
    write_entries([
        _make_entry(
            ts,
            type="close",
            entry_id="e1",
            session_id="sess-1",
            extra={
                "shifted": "shifted-content",
                "tomorrows_first_move": "tfm-content",
                "blocking": "blocking-content",
            },
        )
    ])
    from standup import history
    out = history("this week")
    assert "shifted-content" in out
    assert "tfm-content" in out
    assert "blocking-content" in out


def test_single_recent_amend_entry_appears(write_entries):
    """An amend entry from a few hours ago must appear in the rendering;
    the amend's mirror keys (open shape) must be visible."""
    ts = _iso_offset(_dt.timedelta(hours=-1))
    write_entries([
        {
            "id": "amend-1",
            "session_id": "sess-1",
            "type": "amend",
            "timestamp": ts,
            "amends_id": "original-id",
            "yesterday": "amend-y",
            "today": "amend-t",
            "blockers": "amend-b",
        }
    ])
    from standup import history
    out = history("this week")
    assert "amend-y" in out
    assert "amend-t" in out
    assert "amend-b" in out


# --------------------------------------------------------------------------- #
# CRITERION — Single entry outside window: empty-state string returned
# --------------------------------------------------------------------------- #

def test_single_entry_outside_this_week_returns_empty_state(write_entries):
    """A single entry from 10 days ago must NOT appear in 'this week'
    output; the empty-state string is returned instead."""
    ts = _iso_offset(_dt.timedelta(days=-10))
    write_entries([
        _make_entry(
            ts,
            entry_id="too-old",
            session_id="sess",
            extra={"yesterday": "should-not-appear"},
        )
    ])
    from standup import history
    out = history("this week")
    assert "should-not-appear" not in out
    assert "too-old" not in out
    assert out.strip() != "", (
        "empty-state string must be non-empty even when entries exist "
        "but all fall outside the window"
    )


def test_single_entry_outside_last_month_returns_empty_state(write_entries):
    """A single entry from 60 days ago must NOT appear in 'last month'
    output; the empty-state string is returned instead."""
    ts = _iso_offset(_dt.timedelta(days=-60))
    write_entries([
        _make_entry(
            ts,
            entry_id="ancient",
            extra={"yesterday": "should-not-appear"},
        )
    ])
    from standup import history
    out = history("last month")
    assert "should-not-appear" not in out
    assert "ancient" not in out
    assert out.strip() != ""


# --------------------------------------------------------------------------- #
# CRITERION — Mix of in-range + out-of-range: only in-range entries appear
# --------------------------------------------------------------------------- #

def test_mixed_range_only_in_range_appears_this_week(write_entries):
    """A log with one fresh entry and one stale entry: 'this week' shows
    only the fresh one."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-15)),
            entry_id="stale",
            extra={"yesterday": "STALE-MARKER"},
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="fresh",
            extra={"yesterday": "FRESH-MARKER"},
        ),
    ])
    from standup import history
    out = history("this week")
    assert "FRESH-MARKER" in out
    assert "STALE-MARKER" not in out
    assert "fresh" in out
    assert "stale" not in out


def test_mixed_range_only_in_range_appears_last_month(write_entries):
    """A log with one in-30-day entry and one ancient (60-day) entry:
    'last month' shows only the in-range entry."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-60)),
            entry_id="ancient",
            extra={"yesterday": "ANCIENT-MARKER"},
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(days=-15)),
            entry_id="recent",
            extra={"yesterday": "RECENT-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "RECENT-MARKER" in out
    assert "ANCIENT-MARKER" not in out
    assert "recent" in out
    assert "ancient" not in out


def test_this_week_excludes_8_day_old_but_last_month_includes(write_entries):
    """An entry 8 days old: excluded from 'this week', included in
    'last month'. Demonstrates the two windows behave differently."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-8)),
            entry_id="eight-days",
            extra={"yesterday": "EIGHT-DAYS-MARKER"},
        ),
    ])
    from standup import history
    week = history("this week")
    month = history("last month")
    assert "EIGHT-DAYS-MARKER" not in week, (
        "an 8-day-old entry must NOT appear in 'this week' (7-day window)"
    )
    assert "EIGHT-DAYS-MARKER" in month, (
        "an 8-day-old entry MUST appear in 'last month' (30-day window)"
    )


# --------------------------------------------------------------------------- #
# CRITERION — "this week" includes entries within last 7 days; excludes
# anything older
# --------------------------------------------------------------------------- #

def test_this_week_includes_one_day_old(write_entries):
    """1-day-old entry must appear in 'this week'."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-1)),
            entry_id="one-day",
            extra={"yesterday": "ONE-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("this week")
    assert "ONE-DAY-MARKER" in out


def test_this_week_excludes_8_day_old(write_entries):
    """8-day-old entry must NOT appear in 'this week'."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-8)),
            entry_id="eight-day",
            extra={"yesterday": "EIGHT-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("this week")
    assert "EIGHT-DAY-MARKER" not in out


def test_this_week_excludes_thirty_day_old(write_entries):
    """30-day-old entry must NOT appear in 'this week'."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-30)),
            entry_id="thirty",
            extra={"yesterday": "THIRTY-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("this week")
    assert "THIRTY-DAY-MARKER" not in out


# --------------------------------------------------------------------------- #
# CRITERION — "last month" includes entries within last 30 days; excludes
# older
# --------------------------------------------------------------------------- #

def test_last_month_includes_one_day_old(write_entries):
    """1-day-old entry must appear in 'last month'."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-1)),
            entry_id="one-day",
            extra={"yesterday": "ONE-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "ONE-DAY-MARKER" in out


def test_last_month_includes_eight_day_old(write_entries):
    """8-day-old entry must appear in 'last month' (within the 30-day
    rolling window)."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-8)),
            entry_id="eight-day",
            extra={"yesterday": "EIGHT-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "EIGHT-DAY-MARKER" in out


def test_last_month_includes_twenty_nine_day_old(write_entries):
    """29-day-old entry must appear in 'last month' (still within the
    30-day rolling window)."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-29)),
            entry_id="twenty-nine",
            extra={"yesterday": "TWENTY-NINE-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "TWENTY-NINE-DAY-MARKER" in out


def test_last_month_excludes_thirty_one_day_old(write_entries):
    """31-day-old entry must NOT appear in 'last month'."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-31)),
            entry_id="thirty-one",
            extra={"yesterday": "THIRTY-ONE-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "THIRTY-ONE-MARKER" not in out


def test_last_month_excludes_sixty_day_old(write_entries):
    """60-day-old entry must NOT appear in 'last month'."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(days=-60)),
            entry_id="sixty",
            extra={"yesterday": "SIXTY-DAY-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "SIXTY-DAY-MARKER" not in out


# --------------------------------------------------------------------------- #
# CRITERION — Boundary: entry ~7 days old (use 6.9 days to be safe)
# is included in "this week"
# --------------------------------------------------------------------------- #

def test_boundary_just_under_seven_days_included_in_this_week(write_entries):
    """An entry 6.9 days old (just under the 7-day boundary) must be
    included in 'this week'. Using 6.9 instead of exactly 7 absorbs any
    sub-second clock drift between test setup and history's "now"."""
    delta = _dt.timedelta(days=-6.9)
    write_entries([
        _make_entry(
            _iso_offset(delta),
            entry_id="boundary-week",
            extra={"yesterday": "BOUNDARY-WEEK-MARKER"},
        ),
    ])
    from standup import history
    out = history("this week")
    assert "BOUNDARY-WEEK-MARKER" in out, (
        "entry 6.9 days old must be included in the 7-day rolling 'this "
        "week' window"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Boundary: entry ~30 days old (use 29.9 days) is included
# in "last month"
# --------------------------------------------------------------------------- #

def test_boundary_just_under_thirty_days_included_in_last_month(write_entries):
    """An entry 29.9 days old (just under the 30-day boundary) must be
    included in 'last month'."""
    delta = _dt.timedelta(days=-29.9)
    write_entries([
        _make_entry(
            _iso_offset(delta),
            entry_id="boundary-month",
            extra={"yesterday": "BOUNDARY-MONTH-MARKER"},
        ),
    ])
    from standup import history
    out = history("last month")
    assert "BOUNDARY-MONTH-MARKER" in out, (
        "entry 29.9 days old must be included in the 30-day rolling "
        "'last month' window"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Older entries excluded
# (covered by the per-window tests above; one consolidated assertion here
# for documentation completeness)
# --------------------------------------------------------------------------- #

def test_consolidated_older_entries_excluded(write_entries):
    """A log full of entries spanning weeks/months: only those inside
    each window appear. This is a regression guard against a renderer
    that ignores filtering and dumps everything."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-1)),
            entry_id="fresh",
            extra={"yesterday": "FRESH-XYZ"},
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(days=-15)),
            entry_id="midrange",
            extra={"yesterday": "MID-XYZ"},
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(days=-100)),
            entry_id="ancient",
            extra={"yesterday": "ANCIENT-XYZ"},
        ),
    ])
    from standup import history
    week = history("this week")
    month = history("last month")
    # Week: only fresh.
    assert "FRESH-XYZ" in week
    assert "MID-XYZ" not in week
    assert "ANCIENT-XYZ" not in week
    # Month: fresh + midrange, no ancient.
    assert "FRESH-XYZ" in month
    assert "MID-XYZ" in month
    assert "ANCIENT-XYZ" not in month


# --------------------------------------------------------------------------- #
# CRITERION — Entries grouped by local-calendar date with date headers
# --------------------------------------------------------------------------- #

def test_output_contains_a_date_header(write_entries):
    """Output must contain at least one YYYY-MM-DD date header line for
    a non-empty window."""
    ts = _iso_offset(_dt.timedelta(hours=-2))
    write_entries([_make_entry(ts, entry_id="e1")])
    from standup import history
    out = history("this week")
    # Find at least one line that is exactly YYYY-MM-DD.
    has_date_header = any(
        DATE_HEADER_RE.match(line.strip()) for line in out.splitlines()
    )
    assert has_date_header, (
        "history output must include at least one YYYY-MM-DD date header "
        f"line; got:\n{out}"
    )


def test_date_header_matches_entry_local_date(write_entries):
    """The date header must equal the local-TZ calendar date of the
    entry's timestamp."""
    ts_dt = _local_now() - _dt.timedelta(hours=2)
    ts = ts_dt.isoformat()
    expected_header = ts_dt.date().isoformat()  # YYYY-MM-DD
    write_entries([_make_entry(ts, entry_id="e1")])
    from standup import history
    out = history("this week")
    assert expected_header in out, (
        f"expected date header {expected_header!r} for entry at {ts!r}; "
        f"got:\n{out}"
    )


def test_entries_on_same_day_share_one_date_header(write_entries):
    """Two entries that fall on the same local-calendar date must be
    grouped under a single date header — not two."""
    ts_dt = _local_now() - _dt.timedelta(hours=4)
    # Two entries 5 minutes apart, same day.
    a = _make_entry(
        ts_dt.isoformat(),
        entry_id="ent-a",
        extra={"yesterday": "TAG-A"},
    )
    b = _make_entry(
        (ts_dt + _dt.timedelta(minutes=5)).isoformat(),
        entry_id="ent-b",
        extra={"yesterday": "TAG-B"},
    )
    write_entries([a, b])
    from standup import history
    out = history("this week")
    expected_header = ts_dt.date().isoformat()
    # Count headers matching this exact date.
    header_count = sum(
        1 for line in out.splitlines()
        if line.strip() == expected_header
    )
    assert header_count == 1, (
        f"two entries on the same day must share one date header; "
        f"saw {header_count} occurrences of {expected_header!r} in:\n{out}"
    )
    # Both entries' content still rendered.
    assert "TAG-A" in out
    assert "TAG-B" in out


def test_entries_on_different_days_get_separate_headers(write_entries):
    """Entries on different local dates must each get their own date
    header."""
    ts_a = _local_now() - _dt.timedelta(days=1, hours=2)
    ts_b = _local_now() - _dt.timedelta(hours=2)
    write_entries([
        _make_entry(
            ts_a.isoformat(), entry_id="day-a",
            extra={"yesterday": "DAY-A-TAG"},
        ),
        _make_entry(
            ts_b.isoformat(), entry_id="day-b",
            extra={"yesterday": "DAY-B-TAG"},
        ),
    ])
    from standup import history
    out = history("this week")
    header_a = ts_a.date().isoformat()
    header_b = ts_b.date().isoformat()
    assert header_a in out, f"missing date header for day A ({header_a})"
    assert header_b in out, f"missing date header for day B ({header_b})"


# --------------------------------------------------------------------------- #
# CRITERION — Entries within a date group are ordered by timestamp
# ascending
# --------------------------------------------------------------------------- #

def test_entries_within_group_ordered_by_timestamp_ascending(write_entries):
    """Two entries on the same day, written to disk in REVERSE order:
    history must render the older one first within the date group."""
    base = _local_now() - _dt.timedelta(hours=4)
    earlier = base
    later = base + _dt.timedelta(minutes=30)
    # Write LATER one first to disk so file order != correct render order.
    write_entries([
        _make_entry(
            later.isoformat(), entry_id="later-id",
            extra={"yesterday": "LATER-MARKER"},
        ),
        _make_entry(
            earlier.isoformat(), entry_id="earlier-id",
            extra={"yesterday": "EARLIER-MARKER"},
        ),
    ])
    from standup import history
    out = history("this week")
    pos_earlier = out.find("EARLIER-MARKER")
    pos_later = out.find("LATER-MARKER")
    assert pos_earlier != -1 and pos_later != -1, (
        f"both markers must appear in output; got:\n{out}"
    )
    assert pos_earlier < pos_later, (
        "within a date group, entries must be ordered by timestamp "
        "ascending (oldest first); EARLIER-MARKER should precede "
        f"LATER-MARKER in:\n{out}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Date groups themselves ordered chronologically (oldest
# first)
# --------------------------------------------------------------------------- #

def test_date_groups_ordered_chronologically(write_entries):
    """Three days, written to disk in random order: history must render
    oldest day first, newest day last."""
    today = _local_now()
    d_minus_4 = today - _dt.timedelta(days=4, hours=2)
    d_minus_2 = today - _dt.timedelta(days=2, hours=3)
    d_minus_1 = today - _dt.timedelta(days=1, hours=1)
    # Write order: middle, oldest, newest.
    write_entries([
        _make_entry(
            d_minus_2.isoformat(), entry_id="mid",
            extra={"yesterday": "MID-DAY"},
        ),
        _make_entry(
            d_minus_4.isoformat(), entry_id="old",
            extra={"yesterday": "OLD-DAY"},
        ),
        _make_entry(
            d_minus_1.isoformat(), entry_id="new",
            extra={"yesterday": "NEW-DAY"},
        ),
    ])
    from standup import history
    out = history("this week")
    pos_old = out.find("OLD-DAY")
    pos_mid = out.find("MID-DAY")
    pos_new = out.find("NEW-DAY")
    assert pos_old != -1 and pos_mid != -1 and pos_new != -1, (
        f"all three day markers must appear in output; got:\n{out}"
    )
    assert pos_old < pos_mid < pos_new, (
        "date groups must be ordered chronologically (oldest first); "
        f"got positions OLD={pos_old}, MID={pos_mid}, NEW={pos_new} in:\n{out}"
    )


def test_date_headers_appear_in_chronological_order(write_entries):
    """The YYYY-MM-DD header lines themselves, when collected in file
    order, must be sorted chronologically (oldest first)."""
    today = _local_now()
    days = [
        today - _dt.timedelta(days=5, hours=2),
        today - _dt.timedelta(days=3, hours=2),
        today - _dt.timedelta(days=1, hours=2),
    ]
    # Write them in jumbled order (newest, oldest, middle).
    write_entries([
        _make_entry(days[2].isoformat(), entry_id="A"),
        _make_entry(days[0].isoformat(), entry_id="B"),
        _make_entry(days[1].isoformat(), entry_id="C"),
    ])
    from standup import history
    out = history("this week")
    headers_seen = [
        line.strip() for line in out.splitlines()
        if DATE_HEADER_RE.match(line.strip())
    ]
    # The YYYY-MM-DD lexicographic order equals chronological order.
    assert headers_seen == sorted(headers_seen), (
        f"date headers must appear in chronological order; got "
        f"{headers_seen}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Open and close and amend entries all rendered
# (each entry rendered as: TYPE timestamp followed by its field
# key=value pairs, multiline-friendly)
# --------------------------------------------------------------------------- #

def test_open_entry_rendered_with_type_and_fields(write_entries):
    """An open entry must render with its type label and its three open
    field keys somewhere in the output."""
    ts = _iso_offset(_dt.timedelta(hours=-2))
    write_entries([
        _make_entry(
            ts, type="open", entry_id="o1",
            extra={
                "yesterday": "Y-VAL",
                "today": "T-VAL",
                "blockers": "B-VAL",
            },
        )
    ])
    from standup import history
    out = history("this week")
    assert "open" in out, (
        f"history output must label open entries with their type; got:\n{out}"
    )
    # Field keys present (key=value pairs).
    assert "yesterday" in out
    assert "today" in out
    assert "blockers" in out
    # Field values present.
    assert "Y-VAL" in out
    assert "T-VAL" in out
    assert "B-VAL" in out


def test_close_entry_rendered_with_type_and_fields(write_entries):
    """A close entry must render with its type label and its three close
    field keys somewhere in the output."""
    ts = _iso_offset(_dt.timedelta(hours=-2))
    write_entries([
        _make_entry(
            ts, type="close", entry_id="c1",
            extra={
                "shifted": "S-VAL",
                "tomorrows_first_move": "TFM-VAL",
                "blocking": "BL-VAL",
            },
        )
    ])
    from standup import history
    out = history("this week")
    assert "close" in out
    assert "shifted" in out
    assert "tomorrows_first_move" in out
    assert "blocking" in out
    assert "S-VAL" in out
    assert "TFM-VAL" in out
    assert "BL-VAL" in out


def test_amend_entry_rendered_with_type_and_fields(write_entries):
    """An amend entry must render with its type label and the mirrored
    field keys somewhere in the output."""
    ts = _iso_offset(_dt.timedelta(hours=-1))
    write_entries([
        {
            "id": "a1",
            "session_id": "sess-1",
            "type": "amend",
            "timestamp": ts,
            "amends_id": "id-of-original",
            "yesterday": "AMEND-Y",
            "today": "AMEND-T",
            "blockers": "AMEND-B",
        }
    ])
    from standup import history
    out = history("this week")
    assert "amend" in out
    assert "AMEND-Y" in out
    assert "AMEND-T" in out
    assert "AMEND-B" in out


def test_entry_renders_timestamp(write_entries):
    """The entry's timestamp must appear in its rendering line."""
    ts = _iso_offset(_dt.timedelta(hours=-2))
    write_entries([_make_entry(ts, entry_id="e1")])
    from standup import history
    out = history("this week")
    assert ts in out, (
        f"entry rendering must include its timestamp; expected {ts!r} "
        f"in:\n{out}"
    )


def test_mixed_types_all_rendered_in_one_output(write_entries):
    """A log mixing open + close + amend within the same window must
    render all three types — none silently dropped."""
    base = _local_now() - _dt.timedelta(hours=6)
    write_entries([
        _make_entry(
            base.isoformat(), type="open", entry_id="op",
            extra={"yesterday": "OP-Y"},
        ),
        _make_entry(
            (base + _dt.timedelta(minutes=10)).isoformat(),
            type="close", entry_id="cl",
            extra={"shifted": "CL-S"},
        ),
        {
            "id": "am",
            "session_id": "s",
            "type": "amend",
            "timestamp": (base + _dt.timedelta(minutes=20)).isoformat(),
            "amends_id": "op",
            "yesterday": "AM-Y",
            "today": "AM-T",
            "blockers": "AM-B",
        },
    ])
    from standup import history
    out = history("this week")
    assert "OP-Y" in out
    assert "CL-S" in out
    assert "AM-Y" in out


# --------------------------------------------------------------------------- #
# CRITERION — No ANSI escape codes in output (pure text)
# --------------------------------------------------------------------------- #

def test_output_has_no_ansi_escapes_empty_window(isolated_log):
    """Empty-state string must contain zero ANSI escape codes."""
    from standup import history
    out_w = history("this week")
    out_m = history("last month")
    assert not ANSI_ESC_RE.search(out_w), (
        f"empty-state string for 'this week' contains ANSI escape: {out_w!r}"
    )
    assert not ANSI_ESC_RE.search(out_m), (
        f"empty-state string for 'last month' contains ANSI escape: {out_m!r}"
    )


def test_output_has_no_ansi_escapes_with_content(write_entries):
    """Rendered content must contain zero ANSI escape codes."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="e1",
            extra={"yesterday": "value"},
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-3)),
            type="close", entry_id="e2",
            extra={"shifted": "value"},
        ),
    ])
    from standup import history
    out = history("this week")
    assert not ANSI_ESC_RE.search(out), (
        f"rendered output contains an ANSI escape sequence: {out!r}"
    )


def test_output_no_ansi_csi_sequences(write_entries):
    """Defensive: no CSI-style sequences (e.g. \\x1b[31m for red) leak
    through. Search for any \\x1b byte at all."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="e1",
        )
    ])
    from standup import history
    out = history("this week")
    assert "\x1b" not in out, (
        f"output must not contain ANY \\x1b byte; got:\n{out!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Invalid window value raises ValueError mentioning the
# offending value AND the valid options
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad_window",
    [
        "",
        "today",
        "yesterday",
        "1d",
        "7d",
        "30d",
        "this_week",         # underscored variant
        "this  week",        # double-space
        " this week",        # leading whitespace
        "this week ",        # trailing whitespace
        "This Week",         # case mismatch (spec says exact strings)
        "LAST MONTH",        # case mismatch
        "all",
        "everything",
        "year",
    ],
    ids=[
        "empty", "today", "yesterday", "1d", "7d", "30d",
        "underscored", "double-space", "leading-ws", "trailing-ws",
        "title-case-week", "upper-month", "all", "everything", "year",
    ],
)
def test_invalid_window_raises_value_error(isolated_log, bad_window):
    """Any window value other than the two accepted strings must raise
    ValueError."""
    from standup import history
    with pytest.raises(ValueError):
        history(bad_window)


def test_invalid_window_error_names_offending_value(isolated_log):
    """The ValueError message must mention the offending value so the
    operator can see what they typed wrong."""
    from standup import history
    with pytest.raises(ValueError) as exc_info:
        history("not-a-window")
    msg = str(exc_info.value)
    assert "not-a-window" in msg, (
        f"ValueError message must name the offending value "
        f"'not-a-window'; got: {msg!r}"
    )


def test_invalid_window_error_lists_valid_options(isolated_log):
    """The ValueError message must list the valid options so the
    operator knows what to use instead."""
    from standup import history
    with pytest.raises(ValueError) as exc_info:
        history("bogus-window-value")
    msg = str(exc_info.value)
    assert "this week" in msg, (
        f"ValueError message must list 'this week' as a valid option; "
        f"got: {msg!r}"
    )
    assert "last month" in msg, (
        f"ValueError message must list 'last month' as a valid option; "
        f"got: {msg!r}"
    )


def test_only_two_valid_window_strings(isolated_log):
    """Sanity: exactly the two specified strings are accepted; close
    variants are rejected. Locks the tight window grammar."""
    from standup import history
    # Accepted (do not raise):
    history("this week")
    history("last month")
    # Rejected (close variants):
    for variant in ("thisweek", "lastmonth", "this-week", "last-month"):
        with pytest.raises(ValueError):
            history(variant)


# --------------------------------------------------------------------------- #
# CRITERION — Non-string window raises ValueError or TypeError
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "bad",
    [None, 7, 30, 3.14, True, False, [], {}, b"this week", ("this week",)],
    ids=[
        "None", "int-7", "int-30", "float", "True", "False",
        "list", "dict", "bytes", "tuple",
    ],
)
def test_non_string_window_raises(isolated_log, bad):
    """Non-string window values must raise loudly — either ValueError or
    TypeError is acceptable per the spec."""
    from standup import history
    with pytest.raises((ValueError, TypeError)):
        history(bad)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# CRITERION — history does NOT write to the log (read-only)
# --------------------------------------------------------------------------- #

def test_history_does_not_create_log_when_absent(isolated_log):
    """history must NOT create LOG_PATH (it is read-only)."""
    assert not isolated_log.exists()
    from standup import history
    history("this week")
    history("last month")
    assert not isolated_log.exists(), (
        "history must not create LOG_PATH; the function is read-only"
    )


def test_history_does_not_modify_existing_log(write_entries):
    """The exact bytes of LOG_PATH must be unchanged after history runs.
    Belt-and-suspenders check that history never appends or truncates."""
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="ro-1",
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(days=-15)),
            entry_id="ro-2",
        ),
        _make_entry(
            _iso_offset(_dt.timedelta(days=-100)),
            entry_id="ro-3",
        ),
    ])
    import standup
    bytes_before = standup.LOG_PATH.read_bytes()
    from standup import history
    history("this week")
    history("last month")
    bytes_after = standup.LOG_PATH.read_bytes()
    assert bytes_before == bytes_after, (
        "history must be read-only; LOG_PATH bytes changed across "
        "history() calls"
    )


def test_history_does_not_route_through_append_entry(write_entries, monkeypatch):
    """history must NOT call ``_append_entry`` — it is the read-only
    surface. Trace via monkeypatch."""
    import standup

    append_calls: list[dict] = []
    real_append = standup._append_entry

    def tracking_append(entry):
        append_calls.append(dict(entry))
        return real_append(entry)

    monkeypatch.setattr(standup, "_append_entry", tracking_append)

    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="ro-trace",
        )
    ])
    standup.history("this week")
    standup.history("last month")

    assert append_calls == [], (
        "history must not call _append_entry (read-only surface); "
        f"got {len(append_calls)} append call(s)"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — history routes through _read_entries (the canonical reader)
# (not strictly mandated, but Story-12 acceptance says it uses
# _read_entries; this trace makes the contract explicit)
# --------------------------------------------------------------------------- #

def test_history_routes_through_read_entries(write_entries, monkeypatch):
    """history must delegate reads to ``_read_entries`` so it inherits
    the corrupt-line skipping / missing-file resilience contract."""
    import standup

    read_calls: list[int] = []
    real_read = standup._read_entries

    def tracking_read():
        read_calls.append(1)
        return real_read()

    monkeypatch.setattr(standup, "_read_entries", tracking_read)

    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="rr-1",
        )
    ])
    standup.history("this week")

    assert len(read_calls) >= 1, (
        "history must call _read_entries at least once per invocation; "
        f"got {len(read_calls)} call(s)"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — multiple invocations are independent (no caching)
# --------------------------------------------------------------------------- #

def test_history_reflects_log_changes_between_calls(write_entries):
    """history must read on every call, not cache. Add an entry between
    calls and confirm the second call sees it."""
    # First call — empty log path:
    import standup
    log_file = standup.LOG_PATH
    if log_file.exists():
        log_file.unlink()
    out_first = standup.history("this week")
    # Now write content:
    write_entries([
        _make_entry(
            _iso_offset(_dt.timedelta(hours=-2)),
            entry_id="post-call",
            extra={"yesterday": "POST-CALL-MARKER"},
        )
    ])
    out_second = standup.history("this week")
    assert "POST-CALL-MARKER" not in out_first
    assert "POST-CALL-MARKER" in out_second, (
        "history must read on every call; second call did not pick up "
        "the entry written between calls"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — history with submit_open / close_standup-built entries
# (not just hand-written JSONL)
# --------------------------------------------------------------------------- #

def test_history_renders_submit_open_built_entries(isolated_log):
    """Full integration: submit_open writes via _now_iso (so timestamp
    falls inside 'this week'), history renders it."""
    from standup import submit_open, history
    submit_open(
        session_id="integ-sess",
        yesterday="INTEG-Y",
        today="INTEG-T",
        blockers="INTEG-B",
    )
    out = history("this week")
    assert "INTEG-Y" in out
    assert "INTEG-T" in out
    assert "INTEG-B" in out
    assert "open" in out


def test_history_renders_close_standup_built_entries(isolated_log):
    """Full integration: close_standup writes via _now_iso (so timestamp
    falls inside 'this week'), history renders it."""
    from standup import close_standup, history
    close_standup(
        session_id="integ-sess-c",
        shifted="INTEG-S",
        tomorrows_first_move="INTEG-TFM",
        blocking="INTEG-BL",
    )
    out = history("this week")
    assert "INTEG-S" in out
    assert "INTEG-TFM" in out
    assert "INTEG-BL" in out
    assert "close" in out


# --------------------------------------------------------------------------- #
# EDGE CASE — multiline field values render multiline-friendly
# (output is plain text; embedded newlines in field values are preserved
# in the human-facing rendering)
# --------------------------------------------------------------------------- #

def test_multiline_field_value_content_visible(write_entries):
    """An entry whose field value contains real newlines must render in
    a way that the multi-line content is visible somewhere in the output
    (no truncation, no JSON-escape \\n that hides the content)."""
    ts = _iso_offset(_dt.timedelta(hours=-2))
    write_entries([
        _make_entry(
            ts, entry_id="ml-1",
            extra={
                "yesterday": "first-line\nsecond-line\nthird-line",
                "today": "single-line",
                "blockers": "no-blockers",
            },
        )
    ])
    from standup import history
    out = history("this week")
    # All three lines of the multi-line field value are visible in the
    # rendered output (whether the renderer indents them, keeps them
    # inline, or prefixes is up to implementation; the substrings must
    # appear).
    assert "first-line" in out
    assert "second-line" in out
    assert "third-line" in out
