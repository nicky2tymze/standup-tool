"""
Acceptance tests for Story 7 — Latest-prior-day entry lookup with sentinel.

Rolls up to PO v2 Requirements 6 (open_standup() returns latest prior
entry) and 11 (first-run sentinel; no fake continuity).

Verifies the private helper
``_latest_prior_entry() -> dict`` in ``standup``:

  - importable as ``from standup import _latest_prior_entry``
  - NOT exported in ``standup.__all__`` (private, underscore-prefixed)
  - returns a dict with exactly two keys: "prior_entry" and "first_run"
  - Hit shape  : {"prior_entry": <full entry dict>, "first_run": False}
  - Miss shape : {"prior_entry": None,             "first_run": True}

  - "Yesterday's entry" is the entry whose timestamp date in LOCAL TZ
    is STRICTLY BEFORE today's local calendar date. Same-day and
    future-dated entries are excluded. "Latest" = highest timestamp.

  - LOG_PATH missing             -> Miss
  - LOG_PATH empty               -> Miss
  - All entries today (local TZ) -> Miss
  - Single prior-day entry       -> Hit (that entry)
  - Multiple prior-day entries   -> Hit (the latest of them)
  - Mix of today + prior         -> Hit (latest prior; today excluded)
  - Future-dated entries         -> excluded
  - Hit shape preserves the FULL entry dict (id, session_id, type,
    timestamp, ...fields) — not just the timestamp

Test isolation: every test monkeypatches ``standup.LOG_PATH`` to a
tmp_path file so the real ``Tools/Standup/log.jsonl`` is never touched.
Logs are built by writing JSONL strings directly — this story is
testable independently of Story 5's ``_append_entry``.

Stdlib only. pytest as the runner.
"""

from __future__ import annotations

import datetime as _dt
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
# Helpers for building timestamps with controllable date-relative offsets.
#
# These produce ISO 8601 strings with the local system's UTC offset, so the
# helper-under-test parses them as tz-aware and compares dates in the same
# local TZ that "today" is computed in.
#
# Offsets used:
#   - "today" entries           : now - 60 seconds         (same local date,
#                                                            not in the future)
#   - "prior-day" entries       : now - 25 hours, 26 hours,
#                                 27 hours, 32 days        (always strictly
#                                                            before today's
#                                                            local date,
#                                                            even across DST
#                                                            and timezone
#                                                            boundaries)
#   - "future" entries          : now + 25 hours           (strictly after now,
#                                                            so excluded)
# --------------------------------------------------------------------------- #

def _local_now() -> _dt.datetime:
    """Current local time, tz-aware (matches what the helper computes
    'today' against)."""
    return _dt.datetime.now().astimezone()


def _iso_offset(delta: _dt.timedelta) -> str:
    """Return an ISO 8601 string for ``now + delta`` with local offset.

    Uses ``astimezone()`` so the result carries the same offset
    ``_now_iso`` produces in production code paths.
    """
    return (_local_now() + delta).isoformat()


def _today_iso(seconds_back: int = 60) -> str:
    """Timestamp guaranteed to fall on today's local calendar date.

    Default is ``now - 60s`` so the timestamp is strictly in the past
    (not future-skewed, which would also exclude it) AND on today's
    local date (60s back never crosses midnight unless the test runs
    inside a 60-second window of midnight — which is acceptable risk
    for a unit test, but we still keep the helper documented so that
    failure is recognizable).
    """
    return _iso_offset(_dt.timedelta(seconds=-seconds_back))


def _prior_day_iso(hours_back: int = 25) -> str:
    """Timestamp guaranteed to be on a strictly prior local calendar date.

    25+ hours back guarantees a different local calendar date regardless
    of DST transitions or timezone offset (max DST jump is 1h; 25 - 1
    = 24h still rolls the date).
    """
    return _iso_offset(_dt.timedelta(hours=-hours_back))


def _future_iso(hours_ahead: int = 25) -> str:
    """Timestamp guaranteed to be strictly in the future, by at least one
    full local calendar date."""
    return _iso_offset(_dt.timedelta(hours=hours_ahead))


def _make_entry(
    timestamp: str,
    type: str = "open",
    entry_id: str = "id-default",
    session_id: str = "session-default",
    extra: dict | None = None,
) -> dict:
    """Build a minimal entry dict for the helper to inspect.

    The helper documented in the story compares timestamps and returns
    the full entry dict on hit; it does not validate other fields.
    Tests below extend ``extra`` to assert that the returned dict is
    the full original entry (e.g. carries ``yesterday``, ``today``,
    ``blockers`` etc).
    """
    e: dict = {
        "id": entry_id,
        "session_id": session_id,
        "type": type,
        "timestamp": timestamp,
    }
    if extra:
        e.update(extra)
    return e


# --------------------------------------------------------------------------- #
# Fixtures
#
# isolated_log:        path object pointing at a non-existent tmp file with
#                      LOG_PATH already monkeypatched to it.
# write_entries:       helper that writes a list of entry dicts as JSONL
#                      to that path (one entry per line, file order).
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Monkeypatch ``standup.LOG_PATH`` to a per-test tmp file.

    The file does NOT exist on entry — tests that need it absent get that
    behavior by default. Tests that need content present write it
    explicitly via ``write_entries``.
    """
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file


@pytest.fixture
def write_entries(isolated_log):
    """Return a helper that writes a list of entry dicts as JSONL to
    ``isolated_log``. One entry per line, file order preserved.

    Story 7 builds logs directly (not via Story 5's ``_append_entry``)
    so each test can pin entry timestamps deterministically.
    """
    def _write(entries):
        lines = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
        isolated_log.write_text(lines, encoding="utf-8")
        return isolated_log
    return _write


# --------------------------------------------------------------------------- #
# CRITERION — _latest_prior_entry is importable from `standup`
# --------------------------------------------------------------------------- #

def test_latest_prior_entry_importable():
    """`from standup import _latest_prior_entry` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import _latest_prior_entry  # noqa: F401
    assert callable(_latest_prior_entry)


def test_latest_prior_entry_is_attribute_on_module():
    """The helper must live on the standup module (not a submodule)."""
    import standup
    assert hasattr(standup, "_latest_prior_entry"), (
        "standup module must define _latest_prior_entry"
    )
    assert callable(standup._latest_prior_entry)


# --------------------------------------------------------------------------- #
# CRITERION — _latest_prior_entry is NOT in __all__ (private)
# --------------------------------------------------------------------------- #

def test_latest_prior_entry_not_in_dunder_all():
    """Private helpers must not be re-exported via __all__."""
    import standup
    assert "_latest_prior_entry" not in standup.__all__, (
        "_latest_prior_entry must be private (excluded from __all__); "
        f"current __all__ = {standup.__all__}"
    )


def test_latest_prior_entry_name_is_underscore_prefixed():
    """Adversarial: even if a future refactor adds a public alias, no
    name in ``__all__`` may resolve to the same callable."""
    import standup
    target = getattr(standup, "_latest_prior_entry", object())
    for name in standup.__all__:
        obj = getattr(standup, name, None)
        if obj is target:
            pytest.fail(
                f"Public alias {name!r} exposes _latest_prior_entry; "
                "private helpers must not be re-exported"
            )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: zero required params
# --------------------------------------------------------------------------- #

def test_signature_takes_no_required_params():
    """``_latest_prior_entry`` must be callable with no arguments."""
    import inspect
    from standup import _latest_prior_entry
    sig = inspect.signature(_latest_prior_entry)
    for name, p in sig.parameters.items():
        assert p.default is not inspect.Parameter.empty or p.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"_latest_prior_entry should accept zero required args; "
            f"required param {name!r} is missing a default"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Return-shape contract: dict with exactly the keys
# "prior_entry" and "first_run"
# --------------------------------------------------------------------------- #

def test_return_is_dict(isolated_log):
    """The return value must be a ``dict``."""
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert isinstance(result, dict), (
        f"expected dict, got {type(result).__name__}: {result!r}"
    )


def test_return_has_exact_keys_on_miss(isolated_log):
    """On Miss, dict has exactly {"prior_entry", "first_run"}."""
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert set(result.keys()) == {"prior_entry", "first_run"}, (
        f"Miss-shape keys must be exactly "
        f"{{'prior_entry', 'first_run'}}; got {set(result.keys())}"
    )


def test_return_has_exact_keys_on_hit(write_entries):
    """On Hit, dict has exactly {"prior_entry", "first_run"}."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="hit-1")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert set(result.keys()) == {"prior_entry", "first_run"}, (
        f"Hit-shape keys must be exactly "
        f"{{'prior_entry', 'first_run'}}; got {set(result.keys())}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — LOG_PATH does not exist  ->  Miss
# --------------------------------------------------------------------------- #

def test_missing_log_returns_miss(isolated_log):
    """When LOG_PATH does not exist, return the Miss sentinel."""
    assert not isolated_log.exists(), (
        "fixture invariant: log should not exist before the test acts"
    )
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_miss_prior_entry_is_exactly_none(isolated_log):
    """Miss sentinel: prior_entry is the value ``None`` — not an empty
    dict, not an empty string, not False."""
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] is None, (
        f"prior_entry on Miss must be exactly None (not {{}}, '', or False); "
        f"got {result['prior_entry']!r}"
    )


def test_miss_first_run_is_true_boolean(isolated_log):
    """Miss sentinel: first_run is the boolean ``True``."""
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is True, (
        f"first_run on Miss must be exactly True (boolean); "
        f"got {result['first_run']!r} (type={type(result['first_run']).__name__})"
    )


# --------------------------------------------------------------------------- #
# CRITERION — LOG_PATH empty  ->  Miss
# --------------------------------------------------------------------------- #

def test_empty_log_returns_miss(isolated_log):
    """File exists but contains zero bytes -> Miss sentinel."""
    isolated_log.write_text("", encoding="utf-8")
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_only_blank_lines_returns_miss(isolated_log):
    """A file containing only blank lines yields no entries (per Story 6
    contract) -> Miss sentinel."""
    isolated_log.write_text("\n\n\n", encoding="utf-8")
    from standup import _latest_prior_entry
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


# --------------------------------------------------------------------------- #
# CRITERION — All entries today (local TZ)  ->  Miss
# --------------------------------------------------------------------------- #

def test_single_today_entry_returns_miss(write_entries):
    """One entry, dated today -> Miss (not 'prior')."""
    write_entries([_make_entry(_today_iso(), entry_id="t1")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}, (
        "today-only log must return Miss; today is not 'prior'"
    )


def test_multiple_today_entries_returns_miss(write_entries):
    """Several entries, all dated today -> Miss."""
    write_entries([
        _make_entry(_today_iso(seconds_back=300), entry_id="t1"),
        _make_entry(_today_iso(seconds_back=200), entry_id="t2"),
        _make_entry(_today_iso(seconds_back=100), entry_id="t3"),
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}, (
        "all-today log must return Miss regardless of entry count"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Single prior-day entry  ->  Hit with that entry
# --------------------------------------------------------------------------- #

def test_single_prior_day_entry_returns_hit(write_entries):
    """One entry from yesterday -> Hit with that exact entry."""
    prior = _make_entry(
        _prior_day_iso(),
        entry_id="prior-1",
        session_id="sess-A",
        extra={"yesterday": "y", "today": "t", "blockers": "b"},
    )
    write_entries([prior])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False, (
        f"first_run must be False on Hit; got {result['first_run']!r}"
    )
    assert result["prior_entry"] == prior, (
        f"prior_entry must be the full entry dict; "
        f"expected {prior!r}, got {result['prior_entry']!r}"
    )


def test_single_prior_day_entry_hit_first_run_is_false_boolean(write_entries):
    """Hit sentinel: first_run is the boolean ``False`` (not 0, not '')."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False, (
        f"first_run on Hit must be exactly False (boolean); "
        f"got {result['first_run']!r} (type={type(result['first_run']).__name__})"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Multiple prior-day entries  ->  Hit with the LATEST
# (highest timestamp), regardless of file order
# --------------------------------------------------------------------------- #

def test_multiple_prior_days_returns_latest(write_entries):
    """Three prior-day entries; helper returns the one with highest
    timestamp."""
    oldest = _make_entry(
        _iso_offset(_dt.timedelta(days=-5)), entry_id="oldest"
    )
    middle = _make_entry(
        _iso_offset(_dt.timedelta(days=-2)), entry_id="middle"
    )
    latest = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)), entry_id="latest"
    )
    write_entries([oldest, middle, latest])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == latest, (
        f"helper must pick the highest-timestamp prior entry; "
        f"expected entry id 'latest', got {result['prior_entry']!r}"
    )


def test_latest_is_by_timestamp_not_insertion_order(write_entries):
    """File order is reversed (latest written first); helper still picks
    the highest timestamp, not the first or last line of the file."""
    oldest = _make_entry(
        _iso_offset(_dt.timedelta(days=-30)), entry_id="oldest"
    )
    latest = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)), entry_id="latest"
    )
    middle = _make_entry(
        _iso_offset(_dt.timedelta(days=-3)), entry_id="middle"
    )
    # Insertion order intentionally NOT timestamp order.
    write_entries([latest, oldest, middle])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == latest, (
        "'Latest' must be by highest timestamp value, not by insertion order"
    )


def test_two_prior_entries_same_day_returns_higher_timestamp(write_entries):
    """Two prior entries that fall on the SAME prior calendar date —
    helper picks the one with the higher timestamp (within that day)."""
    earlier = _make_entry(
        _iso_offset(_dt.timedelta(hours=-30)),  # ~ yesterday morning
        entry_id="earlier",
    )
    later = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)),  # ~ yesterday evening
        entry_id="later",
    )
    write_entries([earlier, later])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == later, (
        "multiple prior entries on the same day: pick highest timestamp"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Mix of today + prior days  ->  Hit with latest prior
# (today excluded from candidacy)
# --------------------------------------------------------------------------- #

def test_today_and_prior_returns_prior(write_entries):
    """Today-entry exists with a higher timestamp than the prior-day
    entry; the helper still returns the prior entry because today is
    excluded by the strictly-before-today rule."""
    prior = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)),
        entry_id="prior",
    )
    today = _make_entry(
        _iso_offset(_dt.timedelta(seconds=-30)),  # newer than prior
        entry_id="today",
    )
    write_entries([prior, today])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == prior, (
        "today-entry has the highest absolute timestamp but must NOT be "
        "selected — only entries strictly before today's local date count"
    )


def test_today_first_then_prior_returns_prior(write_entries):
    """Same as above with reversed file order — today written first."""
    today = _make_entry(
        _iso_offset(_dt.timedelta(seconds=-30)),
        entry_id="today",
    )
    prior = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)),
        entry_id="prior",
    )
    write_entries([today, prior])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == prior


def test_many_today_one_prior_returns_the_prior(write_entries):
    """Several today entries plus one prior — the lone prior is the Hit
    even though today entries dominate the file."""
    today_entries = [
        _make_entry(_today_iso(seconds_back=s), entry_id=f"today-{s}")
        for s in (10, 60, 600, 3600)
    ]
    prior = _make_entry(_prior_day_iso(), entry_id="the-prior")
    # Interleave today and prior in the file.
    write_entries([today_entries[0], today_entries[1], prior, today_entries[2], today_entries[3]])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == prior


# --------------------------------------------------------------------------- #
# CRITERION — Future-dated entries are excluded
# --------------------------------------------------------------------------- #

def test_future_only_returns_miss(write_entries):
    """Only future-dated entries — helper returns Miss (futures are not
    'prior' even though they aren't 'today' either)."""
    write_entries([
        _make_entry(_future_iso(hours_ahead=25), entry_id="f1"),
        _make_entry(_future_iso(hours_ahead=72), entry_id="f2"),
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}, (
        "future-dated entries are not 'prior'; expected Miss"
    )


def test_future_and_prior_returns_prior(write_entries):
    """Mix of future + prior — helper picks the prior, ignoring the
    future entry entirely (even if its timestamp is numerically higher)."""
    prior = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)), entry_id="prior"
    )
    future = _make_entry(
        _iso_offset(_dt.timedelta(hours=48)), entry_id="future"
    )
    write_entries([future, prior])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == prior, (
        "future entry must be excluded from candidacy; "
        f"got {result['prior_entry']!r}"
    )


def test_future_today_and_prior_returns_prior(write_entries):
    """Three classes: future, today, prior — only prior qualifies."""
    future = _make_entry(_future_iso(), entry_id="future")
    today = _make_entry(_today_iso(), entry_id="today")
    prior = _make_entry(_prior_day_iso(), entry_id="prior")
    write_entries([future, today, prior])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == prior


# --------------------------------------------------------------------------- #
# CRITERION — Far-past entries (e.g. last month) work the same way
# --------------------------------------------------------------------------- #

def test_far_past_entry_returns_hit(write_entries):
    """A single entry from ~32 days ago is still 'prior' and qualifies."""
    far_past = _make_entry(
        _iso_offset(_dt.timedelta(days=-32)), entry_id="far"
    )
    write_entries([far_past])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == far_past


def test_far_past_only_picks_most_recent_prior(write_entries):
    """Multiple far-past entries — helper picks the most recent of them."""
    a = _make_entry(_iso_offset(_dt.timedelta(days=-100)), entry_id="a")
    b = _make_entry(_iso_offset(_dt.timedelta(days=-50)),  entry_id="b")
    c = _make_entry(_iso_offset(_dt.timedelta(days=-10)),  entry_id="c")
    write_entries([a, b, c])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == c, (
        "with multiple far-past entries, the most recent (c, ~10 days back) "
        "must be picked"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Hit shape carries the FULL entry dict (not just timestamp)
# --------------------------------------------------------------------------- #

def test_hit_returns_full_entry_dict(write_entries):
    """The returned ``prior_entry`` carries every key from the source
    entry (id, session_id, type, timestamp, plus type-specific fields)."""
    full = _make_entry(
        _prior_day_iso(),
        type="open",
        entry_id="entry-xyz-123",
        session_id="session-abc-456",
        extra={
            "yesterday": "wrote tests for Story 6",
            "today": "writing tests for Story 7",
            "blockers": "none",
        },
    )
    write_entries([full])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    pe = result["prior_entry"]
    assert pe is not None
    # Every original key must round-trip with the original value.
    for k, v in full.items():
        assert k in pe, f"prior_entry missing key {k!r}; got {pe!r}"
        assert pe[k] == v, (
            f"prior_entry[{k!r}] mismatch: expected {v!r}, got {pe[k]!r}"
        )


def test_hit_returns_dict_type(write_entries):
    """``prior_entry`` on Hit is a dict, not a tuple/list/namedtuple."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert isinstance(result["prior_entry"], dict), (
        f"prior_entry on Hit must be a dict; got "
        f"{type(result['prior_entry']).__name__}"
    )


def test_hit_with_close_type_entry_returns_full_dict(write_entries):
    """Close-type entries also work (helper compares only timestamps,
    doesn't filter by entry type)."""
    close_entry = _make_entry(
        _prior_day_iso(),
        type="close",
        entry_id="close-1",
        session_id="sess-1",
        extra={
            "shifted": "no",
            "tomorrows_first_move": "wake up",
            "blocking": "nothing",
        },
    )
    write_entries([close_entry])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == close_entry, (
        "type='close' entries must also be candidates for 'latest prior'"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Miss shape: prior_entry is exactly None (identity)
# --------------------------------------------------------------------------- #

def test_miss_after_today_only_prior_entry_is_none_identity(write_entries):
    """``prior_entry is None`` — strict identity, not just equality."""
    write_entries([_make_entry(_today_iso(), entry_id="t")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] is None, (
        f"prior_entry must be exactly None; got {result['prior_entry']!r}"
    )


def test_miss_after_future_only_prior_entry_is_none_identity(write_entries):
    """``prior_entry is None`` after future-only log."""
    write_entries([_make_entry(_future_iso(), entry_id="f")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] is None, (
        f"prior_entry must be exactly None on future-only Miss; "
        f"got {result['prior_entry']!r}"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Boundary clarity at midnight (local)
#
# The story specifies: "midnight today is 'today'; 23:59:59 yesterday is
# 'prior'". We can't pin midnight precisely without freezing the clock,
# but we CAN assert that an entry at "today's midnight (00:00:00 local)"
# is NOT prior (it shares today's local date).
# --------------------------------------------------------------------------- #

def test_today_midnight_local_is_not_prior(write_entries):
    """An entry whose timestamp is today's local midnight (00:00:00)
    shares today's local calendar date — so it's NOT 'prior'."""
    now = _local_now()
    # Today's midnight in local TZ, tz-aware via the same offset as 'now'.
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    entry = _make_entry(today_midnight.isoformat(), entry_id="midnight")
    write_entries([entry])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}, (
        "today's local midnight is on today's local date, so it is NOT "
        "'strictly before today' — expected Miss"
    )


def test_yesterday_last_second_is_prior(write_entries):
    """An entry at 23:59:59 on the prior local calendar date IS prior."""
    now = _local_now()
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_last_second = today_midnight - _dt.timedelta(seconds=1)
    entry = _make_entry(
        yesterday_last_second.isoformat(),
        entry_id="yesterday-last-second",
    )
    write_entries([entry])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False, (
        "23:59:59 on the prior local date is strictly before today; "
        "expected Hit"
    )
    assert result["prior_entry"] == entry


def test_today_midnight_and_yesterday_last_second_picks_yesterday(write_entries):
    """Together: today's 00:00:00 (excluded) plus yesterday's 23:59:59
    (included, only prior entry) -> Hit on yesterday's last second.

    Catches an off-by-one where an implementation accidentally treats
    today's midnight as 'prior'."""
    now = _local_now()
    today_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_last_second = today_midnight - _dt.timedelta(seconds=1)

    today_entry = _make_entry(
        today_midnight.isoformat(), entry_id="today-midnight"
    )
    yesterday_entry = _make_entry(
        yesterday_last_second.isoformat(), entry_id="yesterday-2359",
    )
    write_entries([today_entry, yesterday_entry])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == yesterday_entry, (
        "expected the 23:59:59 yesterday entry to be selected; "
        f"got {result['prior_entry']!r}"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Helper does not depend on entry order, type, or extra fields
# --------------------------------------------------------------------------- #

def test_entry_order_does_not_affect_outcome(write_entries):
    """Same entries, two file orders, same Hit result. Verifies the
    helper sorts by timestamp internally."""
    e1 = _make_entry(_iso_offset(_dt.timedelta(days=-3)),  entry_id="e1")
    e2 = _make_entry(_iso_offset(_dt.timedelta(days=-2)),  entry_id="e2")
    e3 = _make_entry(_iso_offset(_dt.timedelta(hours=-25)), entry_id="e3")

    # Forward order
    write_entries([e1, e2, e3])
    from standup import _latest_prior_entry
    forward_result = _latest_prior_entry()

    # Reverse order
    write_entries([e3, e2, e1])
    reverse_result = _latest_prior_entry()

    assert forward_result == reverse_result, (
        "result must depend on timestamp content, not file order; "
        f"forward={forward_result!r} reverse={reverse_result!r}"
    )
    assert forward_result["prior_entry"] == e3


def test_entry_type_does_not_filter(write_entries):
    """Open, close, and amend entries are all candidates — helper
    looks at timestamps only."""
    open_e = _make_entry(
        _iso_offset(_dt.timedelta(days=-3)),
        type="open", entry_id="o",
    )
    close_e = _make_entry(
        _iso_offset(_dt.timedelta(days=-2)),
        type="close", entry_id="c",
    )
    amend_e = _make_entry(
        _iso_offset(_dt.timedelta(hours=-25)),
        type="amend", entry_id="a",
    )
    write_entries([open_e, close_e, amend_e])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["prior_entry"] == amend_e, (
        "helper must consider all entry types; expected the amend with "
        "highest timestamp"
    )


# --------------------------------------------------------------------------- #
# EDGE CASE — Corrupt log doesn't matter — _read_entries handles skipping
# --------------------------------------------------------------------------- #

def test_corrupt_log_lines_do_not_break_helper(isolated_log):
    """Mix of malformed lines + a valid prior entry — helper still returns
    Hit because Story 6's _read_entries silently drops corrupt lines and
    surfaces only the valid entries to this helper."""
    valid_prior = _make_entry(_prior_day_iso(), entry_id="survivor")
    payload = (
        "this is not json\n"
        + json.dumps(valid_prior) + "\n"
        + "{ broken object\n"
        + "[1, 2, 3]\n"
    )
    isolated_log.write_text(payload, encoding="utf-8")

    from standup import _latest_prior_entry
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid_prior, (
        "valid prior entry must be returned even when other lines are "
        "malformed (Story 6's resilience contract feeds clean entries to "
        "this helper)"
    )


def test_corrupt_log_with_no_valid_prior_returns_miss(isolated_log):
    """All lines malformed, no valid entries -> empty entries from
    _read_entries -> Miss."""
    isolated_log.write_text(
        "garbage1\ngarbage2\n{also-bad\n",
        encoding="utf-8",
    )
    from standup import _latest_prior_entry
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


# --------------------------------------------------------------------------- #
# EDGE CASE — Repeated calls are stable
# --------------------------------------------------------------------------- #

def test_repeated_calls_return_equal_results(write_entries):
    """Two calls on the same log yield equal results — helper doesn't
    mutate state."""
    prior = _make_entry(_prior_day_iso(), entry_id="p")
    write_entries([prior])
    from standup import _latest_prior_entry
    a = _latest_prior_entry()
    b = _latest_prior_entry()
    assert a == b
    assert a["prior_entry"] == prior


def test_helper_does_not_mutate_log(write_entries):
    """Log file bytes must be byte-equal before and after the call."""
    prior = _make_entry(_prior_day_iso(), entry_id="p")
    log_path = write_entries([prior])
    before = log_path.read_bytes()
    from standup import _latest_prior_entry
    _latest_prior_entry()
    after = log_path.read_bytes()
    assert before == after, (
        "_latest_prior_entry mutated the log file; it must be read-only"
    )


# --------------------------------------------------------------------------- #
# Defensive guards — corrupt entry shapes (added Reviewer pass 2)
#
# The Reviewer flagged two code paths in _latest_prior_entry that had no
# direct test coverage:
#
#   GAP 1 (standup.py:458-460):
#     `if not isinstance(ts_str, str) or not ts_str: continue`
#     Defends against entries from _read_entries that lack a "timestamp"
#     key, or whose "timestamp" is None / empty string / non-string.
#
#   GAP 2 (standup.py:461-464):
#     `except (ValueError, TypeError): continue`
#     Defends against entries with string timestamps that _parse_iso
#     rejects (un-parseable garbage, naive offset-less ISO strings).
#
# These tests build the log JSONL directly so we can produce exact entry
# shapes (e.g. a dict missing the "timestamp" key altogether) that the
# normal _make_entry helper can't create. Each test asserts the
# corrupt entry is silently skipped — no raise from
# _latest_prior_entry, and Hit/Miss reflects only the surviving valid
# entries (if any).
# --------------------------------------------------------------------------- #

def _write_raw_jsonl(log_path: pathlib.Path, lines: list[dict]) -> pathlib.Path:
    """Write a list of raw dicts to ``log_path`` as JSONL, one per line.

    Unlike ``write_entries``, this does NOT route through ``_make_entry``
    so callers can construct entries with missing or non-string timestamp
    fields.
    """
    payload = "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in lines)
    log_path.write_text(payload, encoding="utf-8")
    return log_path


# --- GAP 1: missing / null / empty / non-string timestamp ----------------- #

def test_entry_missing_timestamp_key_is_skipped(isolated_log):
    """Entry dict has no ``timestamp`` key at all -> silently skipped.
    No other entries -> Miss."""
    _write_raw_jsonl(isolated_log, [
        {"id": "x", "session_id": "s", "type": "open"},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_entry_missing_timestamp_with_other_valid_prior_valid_wins(isolated_log):
    """Entry missing ``timestamp`` is skipped; a sibling valid prior
    entry wins the Hit."""
    valid = _make_entry(_prior_day_iso(), entry_id="valid-prior")
    _write_raw_jsonl(isolated_log, [
        {"id": "no-ts", "session_id": "s", "type": "open"},
        valid,
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid


def test_entry_with_null_timestamp_is_skipped(isolated_log):
    """``"timestamp": null`` (Python ``None``) -> skipped silently.
    No other entries -> Miss."""
    _write_raw_jsonl(isolated_log, [
        {"id": "n", "session_id": "s", "type": "open", "timestamp": None},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_entry_with_null_timestamp_plus_valid_prior_valid_wins(isolated_log):
    """Null-timestamp entry is skipped; valid prior entry wins."""
    valid = _make_entry(_prior_day_iso(), entry_id="valid-prior")
    _write_raw_jsonl(isolated_log, [
        {"id": "n", "session_id": "s", "type": "open", "timestamp": None},
        valid,
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid


def test_entry_with_empty_string_timestamp_is_skipped(isolated_log):
    """``"timestamp": ""`` (empty string) -> skipped silently.
    No other entries -> Miss."""
    _write_raw_jsonl(isolated_log, [
        {"id": "e", "session_id": "s", "type": "open", "timestamp": ""},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_entry_with_empty_string_timestamp_plus_valid_prior_valid_wins(isolated_log):
    """Empty-timestamp entry is skipped; valid prior entry wins."""
    valid = _make_entry(_prior_day_iso(), entry_id="valid-prior")
    _write_raw_jsonl(isolated_log, [
        {"id": "e", "session_id": "s", "type": "open", "timestamp": ""},
        valid,
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid


def test_entry_with_integer_timestamp_is_skipped(isolated_log):
    """Non-string timestamp (int) -> skipped silently. No other entries
    -> Miss."""
    _write_raw_jsonl(isolated_log, [
        {"id": "i", "session_id": "s", "type": "open", "timestamp": 12345},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_entry_with_float_timestamp_is_skipped(isolated_log):
    """Non-string timestamp (float) -> skipped silently."""
    _write_raw_jsonl(isolated_log, [
        {"id": "f", "session_id": "s", "type": "open", "timestamp": 12345.678},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_entry_with_bool_timestamp_is_skipped(isolated_log):
    """Non-string timestamp (bool) -> skipped silently. (``True`` is an
    int subclass in Python, so this also exercises the non-str guard.)"""
    _write_raw_jsonl(isolated_log, [
        {"id": "b", "session_id": "s", "type": "open", "timestamp": True},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_entry_with_list_timestamp_is_skipped(isolated_log):
    """Non-string timestamp (list) -> skipped silently."""
    _write_raw_jsonl(isolated_log, [
        {"id": "l", "session_id": "s", "type": "open",
         "timestamp": ["2026-05-08T12:00:00+00:00"]},
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_entry_with_non_string_timestamp_plus_valid_prior_valid_wins(isolated_log):
    """Non-string-timestamp entry is skipped; valid prior wins."""
    valid = _make_entry(_prior_day_iso(), entry_id="valid-prior")
    _write_raw_jsonl(isolated_log, [
        {"id": "i", "session_id": "s", "type": "open", "timestamp": 12345},
        valid,
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid


# --- GAP 2: un-parseable / naive ISO timestamp strings -------------------- #

def test_entry_with_garbage_timestamp_string_is_skipped(write_entries):
    """``"timestamp": "not-a-date"`` -> _parse_iso raises ValueError ->
    silently skipped. No other entries -> Miss."""
    write_entries([_make_entry("not-a-date", entry_id="garbage")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_entry_with_word_timestamp_is_skipped(write_entries):
    """``"timestamp": "yesterday"`` -> _parse_iso ValueError -> skipped."""
    write_entries([_make_entry("yesterday", entry_id="word")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_entry_with_naive_iso_timestamp_is_skipped(write_entries):
    """``"timestamp": "2026-05-08T12:00:00"`` (no timezone offset) ->
    _parse_iso rejects naive datetimes with ValueError -> skipped."""
    write_entries([_make_entry("2026-05-08T12:00:00", entry_id="naive")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_entry_with_naive_iso_date_only_is_skipped(write_entries):
    """``"timestamp": "2026-05-08"`` (date only, no time, no offset) ->
    rejected as naive -> skipped."""
    write_entries([_make_entry("2026-05-08", entry_id="date-only")])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}


def test_entry_with_garbage_timestamp_plus_valid_prior_valid_wins(write_entries):
    """Mix of one bad-timestamp entry + one valid prior -> valid wins."""
    valid = _make_entry(_prior_day_iso(), entry_id="valid-prior")
    write_entries([
        _make_entry("not-a-date", entry_id="garbage"),
        valid,
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid


def test_entry_with_naive_timestamp_plus_valid_prior_valid_wins(write_entries):
    """Naive-timestamp entry skipped; valid prior wins."""
    valid = _make_entry(_prior_day_iso(), entry_id="valid-prior")
    write_entries([
        _make_entry("2026-05-08T12:00:00", entry_id="naive"),
        valid,
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result["first_run"] is False
    assert result["prior_entry"] == valid


def test_all_entries_have_bad_timestamps_returns_miss(write_entries):
    """Every entry has a bad/un-parseable/naive timestamp -> all skipped
    -> Miss."""
    write_entries([
        _make_entry("not-a-date", entry_id="garbage"),
        _make_entry("yesterday", entry_id="word"),
        _make_entry("2026-05-08T12:00:00", entry_id="naive"),
        _make_entry("2026-05-08", entry_id="date-only"),
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_all_entries_have_bad_or_missing_timestamps_returns_miss(isolated_log):
    """Mix of every defensive case (missing key, null, empty string,
    non-string, garbage string, naive ISO) and zero valid entries ->
    Miss. The helper must silently skip ALL of them and not raise."""
    _write_raw_jsonl(isolated_log, [
        {"id": "1", "session_id": "s", "type": "open"},                       # missing key
        {"id": "2", "session_id": "s", "type": "open", "timestamp": None},    # null
        {"id": "3", "session_id": "s", "type": "open", "timestamp": ""},      # empty
        {"id": "4", "session_id": "s", "type": "open", "timestamp": 12345},   # non-string
        {"id": "5", "session_id": "s", "type": "open", "timestamp": "not-a-date"},
        {"id": "6", "session_id": "s", "type": "open",
         "timestamp": "2026-05-08T12:00:00"},                                  # naive
    ])
    from standup import _latest_prior_entry
    result = _latest_prior_entry()
    assert result == {"prior_entry": None, "first_run": True}
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_helper_does_not_raise_on_corrupt_entry_shapes(isolated_log):
    """The combined corrupt-shape log must NOT cause _latest_prior_entry
    itself to raise. (Warnings from _read_entries are upstream and
    permitted; this assertion targets the helper proper.)"""
    _write_raw_jsonl(isolated_log, [
        {"id": "1", "session_id": "s", "type": "open"},
        {"id": "2", "session_id": "s", "type": "open", "timestamp": None},
        {"id": "3", "session_id": "s", "type": "open", "timestamp": ""},
        {"id": "4", "session_id": "s", "type": "open", "timestamp": 12345},
        {"id": "5", "session_id": "s", "type": "open", "timestamp": "not-a-date"},
        {"id": "6", "session_id": "s", "type": "open",
         "timestamp": "2026-05-08T12:00:00"},
    ])
    from standup import _latest_prior_entry
    # If the helper raises for any of these inputs, this call propagates
    # the exception and the test fails — which is the assertion.
    result = _latest_prior_entry()
    assert isinstance(result, dict)
    assert set(result.keys()) == {"prior_entry", "first_run"}
