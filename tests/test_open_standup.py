"""
Acceptance tests for Story 8 — open_standup() public function.

Rolls up to PO v2 Requirements 3 (public API), 6 (latest-prior return),
9 (session identity), 11 (first-run sentinel).

Verifies the public function ``open_standup() -> dict`` in ``standup``,
which replaces the NotImplementedError stub from Story 1:

  - importable as ``from standup import open_standup``
  - present in ``standup.__all__`` (public)
  - no longer raises NotImplementedError when called
  - takes no arguments (zero-parameter signature)
  - returns a dict
  - returned dict has EXACTLY the keys
        {"session_id", "prior_entry", "first_run"}
    — not more, not less
  - session_id is a 32-char lowercase hex string (uuid4 hex format)
  - each call returns a new session_id (10 calls all distinct,
    no caching)
  - prior_entry is None and first_run is True when log is empty/absent
  - prior_entry is the latest prior-day entry dict and first_run is
    False when a prior-day entry exists
  - on Hit, prior_entry round-trips byte-for-byte through json.dumps +
    json.loads (preserves disk content exactly)
  - function does NOT write to log (file size unchanged before and
    after call)
  - function does NOT modify existing log entries
  - function is idempotent w.r.t. log state (calling repeatedly does
    not change the log)

Test isolation:
  - every test that touches the log monkeypatches ``standup.LOG_PATH``
    to a per-test ``tmp_path / "log.jsonl"`` so the real
    ``Tools/Standup/log.jsonl`` is never touched
  - test logs are built EITHER by writing JSONL strings directly
    (deterministic timestamps for date-relative cases) OR via the real
    ``_build_entry`` + ``_append_entry`` helpers (round-trip case)

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
# Helpers — build deterministic timestamps and entry dicts.
#
# Mirror the timestamp patterns from test_latest_prior.py so that "prior",
# "today", and "future" are unambiguous regardless of the local TZ or DST
# state at test time.
# --------------------------------------------------------------------------- #

UUID4_HEX_RE = re.compile(r"^[0-9a-f]{32}$")


def _local_now() -> _dt.datetime:
    """Current local time, tz-aware (matches what _now_iso would emit)."""
    return _dt.datetime.now().astimezone()


def _iso_offset(delta: _dt.timedelta) -> str:
    """Return an ISO 8601 string for ``now + delta`` with local offset."""
    return (_local_now() + delta).isoformat()


def _today_iso(seconds_back: int = 60) -> str:
    """Timestamp on today's local calendar date, strictly in the past."""
    return _iso_offset(_dt.timedelta(seconds=-seconds_back))


def _prior_day_iso(hours_back: int = 25) -> str:
    """Timestamp on a strictly prior local calendar date.

    25h back guarantees a different local date even with a 1h DST jump.
    """
    return _iso_offset(_dt.timedelta(hours=-hours_back))


def _make_entry(
    timestamp: str,
    type: str = "open",
    entry_id: str = "id-default",
    session_id: str = "session-default",
    extra: dict | None = None,
) -> dict:
    """Build a minimal entry dict (story-8 helper compares timestamps and
    returns the full dict on Hit; other fields are passthrough).
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
# isolated_log:    tmp file path, with standup.LOG_PATH monkeypatched to it.
#                  File does NOT exist on entry.
# write_entries:   helper that writes a list of dicts as JSONL to that path.
# --------------------------------------------------------------------------- #

@pytest.fixture
def isolated_log(tmp_path, monkeypatch):
    """Monkeypatch ``standup.LOG_PATH`` to a per-test tmp file.

    Reload the module first so any cached state from prior tests is
    cleared, then patch the resolved attribute to the tmp file. The
    file does NOT exist on entry — tests that need it absent get that
    behavior by default.
    """
    if "standup" in sys.modules:
        importlib.reload(sys.modules["standup"])
    import standup  # noqa: E402
    log_file = tmp_path / "log.jsonl"
    monkeypatch.setattr(standup, "LOG_PATH", log_file)
    return log_file


@pytest.fixture
def write_entries(isolated_log):
    """Return a helper that writes a list of dicts as JSONL to the
    isolated log file. One entry per line, file order preserved.
    """
    def _write(entries):
        lines = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
        isolated_log.write_text(lines, encoding="utf-8")
        return isolated_log
    return _write


# --------------------------------------------------------------------------- #
# CRITERION — open_standup is importable from `standup`
# --------------------------------------------------------------------------- #

def test_open_standup_importable():
    """`from standup import open_standup` must succeed."""
    if "standup" in sys.modules:
        del sys.modules["standup"]
    from standup import open_standup  # noqa: F401
    assert callable(open_standup)


def test_open_standup_is_attribute_on_module():
    """The function must live on the standup module."""
    import standup
    assert hasattr(standup, "open_standup"), (
        "standup module must define open_standup"
    )
    assert callable(standup.open_standup)


# --------------------------------------------------------------------------- #
# CRITERION — open_standup is in __all__ (public)
# --------------------------------------------------------------------------- #

def test_open_standup_in_dunder_all():
    """Public functions must be exported via __all__."""
    import standup
    assert "open_standup" in standup.__all__, (
        f"open_standup must be public (listed in __all__); "
        f"current __all__ = {standup.__all__}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Stub replaced: open_standup no longer raises NotImplementedError
# --------------------------------------------------------------------------- #

def test_open_standup_does_not_raise_not_implemented(isolated_log):
    """The Story-1 stub raised NotImplementedError; Story 8 replaces it.
    Calling open_standup() must complete without raising NotImplementedError.
    """
    from standup import open_standup
    try:
        open_standup()
    except NotImplementedError:
        pytest.fail(
            "open_standup() still raises NotImplementedError; Story 8 "
            "must replace the Story-1 stub with a working implementation"
        )


# --------------------------------------------------------------------------- #
# CRITERION — Signature: zero arguments
# --------------------------------------------------------------------------- #

def test_open_standup_takes_no_arguments():
    """open_standup() must accept zero arguments — no required, no
    optional, no varargs."""
    from standup import open_standup
    sig = inspect.signature(open_standup)
    assert list(sig.parameters.keys()) == [], (
        f"open_standup must accept zero parameters; "
        f"got {list(sig.parameters)}"
    )


def test_open_standup_does_not_swallow_args_silently():
    """Guard against ``def open_standup(*args, **kwargs)`` style stubs."""
    from standup import open_standup
    sig = inspect.signature(open_standup)
    for param in sig.parameters.values():
        assert param.kind not in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ), (
            f"open_standup must not accept *args/**kwargs; "
            f"found {param.name} of kind {param.kind}"
        )


def test_open_standup_rejects_positional_argument(isolated_log):
    """Calling with a positional argument must raise TypeError (signature
    is zero-arg, not just zero-required-arg)."""
    from standup import open_standup
    with pytest.raises(TypeError):
        open_standup("unexpected")  # type: ignore[call-arg]


def test_open_standup_rejects_keyword_argument(isolated_log):
    """Calling with a keyword argument must raise TypeError."""
    from standup import open_standup
    with pytest.raises(TypeError):
        open_standup(session_id="x")  # type: ignore[call-arg]


# --------------------------------------------------------------------------- #
# CRITERION — Returns a dict
# --------------------------------------------------------------------------- #

def test_open_standup_returns_dict_on_empty_log(isolated_log):
    """Return value must be a ``dict`` even when the log is absent."""
    from standup import open_standup
    result = open_standup()
    assert isinstance(result, dict), (
        f"expected dict, got {type(result).__name__}: {result!r}"
    )


def test_open_standup_returns_dict_on_populated_log(write_entries):
    """Return value must be a ``dict`` when the log has prior entries."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    result = open_standup()
    assert isinstance(result, dict)


# --------------------------------------------------------------------------- #
# CRITERION — Returned dict has EXACTLY the keys
# {"session_id", "prior_entry", "first_run"}
# --------------------------------------------------------------------------- #

EXPECTED_KEYS = {"session_id", "prior_entry", "first_run"}


def test_returned_dict_has_exact_keys_on_miss(isolated_log):
    """Empty log -> Miss; returned dict has exactly the expected keys."""
    from standup import open_standup
    result = open_standup()
    assert set(result.keys()) == EXPECTED_KEYS, (
        f"open_standup must return exactly {EXPECTED_KEYS}; "
        f"got {set(result.keys())}"
    )


def test_returned_dict_has_exact_keys_on_hit(write_entries):
    """Prior-day log -> Hit; returned dict has exactly the expected keys."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    result = open_standup()
    assert set(result.keys()) == EXPECTED_KEYS, (
        f"open_standup must return exactly {EXPECTED_KEYS}; "
        f"got {set(result.keys())}"
    )


def test_returned_dict_has_no_extra_keys_on_miss(isolated_log):
    """Adversarial: Miss must not add stray keys (e.g. 'log_path',
    'timestamp', 'opened_at', 'history')."""
    from standup import open_standup
    result = open_standup()
    extra = set(result.keys()) - EXPECTED_KEYS
    assert not extra, f"open_standup returned unexpected extra keys: {extra}"


def test_returned_dict_has_no_extra_keys_on_hit(write_entries):
    """Adversarial: Hit must not add stray keys."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    result = open_standup()
    extra = set(result.keys()) - EXPECTED_KEYS
    assert not extra, f"open_standup returned unexpected extra keys: {extra}"


def test_returned_dict_has_no_missing_keys_on_miss(isolated_log):
    """Adversarial: Miss must not drop any expected key."""
    from standup import open_standup
    result = open_standup()
    missing = EXPECTED_KEYS - set(result.keys())
    assert not missing, f"open_standup is missing required keys: {missing}"


def test_returned_dict_has_no_missing_keys_on_hit(write_entries):
    """Adversarial: Hit must not drop any expected key."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    result = open_standup()
    missing = EXPECTED_KEYS - set(result.keys())
    assert not missing, f"open_standup is missing required keys: {missing}"


# --------------------------------------------------------------------------- #
# CRITERION — session_id is a 32-char lowercase hex string (uuid4 hex)
# --------------------------------------------------------------------------- #

def test_session_id_is_string(isolated_log):
    """session_id must be a ``str``."""
    from standup import open_standup
    result = open_standup()
    assert isinstance(result["session_id"], str), (
        f"session_id must be a str; got {type(result['session_id']).__name__}"
    )


def test_session_id_is_32_char_lowercase_hex(isolated_log):
    """session_id must match uuid4().hex format: exactly 32 lowercase hex
    characters, no dashes, no prefix."""
    from standup import open_standup
    result = open_standup()
    sid = result["session_id"]
    assert UUID4_HEX_RE.match(sid), (
        f"session_id must be 32 lowercase hex chars (uuid4 hex); "
        f"got {sid!r}"
    )


def test_session_id_has_no_dashes(isolated_log):
    """uuid4().hex format excludes dashes; uuid4().__str__() includes them.
    Adversarial: catch a stub that returns ``str(uuid4())`` instead of
    ``uuid4().hex``."""
    from standup import open_standup
    result = open_standup()
    assert "-" not in result["session_id"], (
        f"session_id must use uuid4().hex format (no dashes); "
        f"got {result['session_id']!r}"
    )


def test_session_id_length_exactly_32(isolated_log):
    """Defensive check on length even if regex above is loosened later."""
    from standup import open_standup
    result = open_standup()
    assert len(result["session_id"]) == 32, (
        f"session_id length must be exactly 32; "
        f"got {len(result['session_id'])} for {result['session_id']!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Each call returns a unique session_id (no caching)
# --------------------------------------------------------------------------- #

def test_each_call_returns_unique_session_id(isolated_log):
    """10 sequential calls must yield 10 distinct session_ids — no caching."""
    from standup import open_standup
    sids = [open_standup()["session_id"] for _ in range(10)]
    assert len(set(sids)) == 10, (
        f"open_standup must mint a fresh session_id per call; "
        f"got {len(set(sids))} unique values across 10 calls: {sids}"
    )


def test_session_id_changes_across_calls_with_unchanged_log(write_entries):
    """Even when the log is unchanged between calls, session_id must
    differ — proves no caching on log state."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    sid_a = open_standup()["session_id"]
    sid_b = open_standup()["session_id"]
    assert sid_a != sid_b, (
        "session_id must be freshly minted on every call, even when the "
        "log state hasn't changed"
    )


def test_two_consecutive_calls_minimum_uniqueness(isolated_log):
    """Tightest possible case: two back-to-back calls must differ."""
    from standup import open_standup
    a = open_standup()["session_id"]
    b = open_standup()["session_id"]
    assert a != b


# --------------------------------------------------------------------------- #
# CRITERION — Empty log -> Miss return shape
#   prior_entry is None (identity), first_run is True (boolean identity)
# --------------------------------------------------------------------------- #

def test_missing_log_returns_miss_shape(isolated_log):
    """LOG_PATH does not exist -> prior_entry is None, first_run is True."""
    assert not isolated_log.exists(), (
        "fixture invariant: log should not exist before the test acts"
    )
    from standup import open_standup
    result = open_standup()
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_empty_log_returns_miss_shape(isolated_log):
    """LOG_PATH exists but is zero bytes -> Miss shape."""
    isolated_log.write_text("", encoding="utf-8")
    from standup import open_standup
    result = open_standup()
    assert result["prior_entry"] is None
    assert result["first_run"] is True


def test_miss_prior_entry_is_exactly_none_identity(isolated_log):
    """prior_entry on Miss must be exactly ``None`` (identity, not just
    falsey)."""
    from standup import open_standup
    result = open_standup()
    assert result["prior_entry"] is None, (
        f"prior_entry on Miss must be exactly None (not {{}}, '', 0, []); "
        f"got {result['prior_entry']!r}"
    )


def test_miss_first_run_is_true_boolean_identity(isolated_log):
    """first_run on Miss must be exactly the boolean ``True`` (not 1, not
    a truthy non-bool)."""
    from standup import open_standup
    result = open_standup()
    assert result["first_run"] is True, (
        f"first_run on Miss must be exactly True (boolean); "
        f"got {result['first_run']!r} "
        f"(type={type(result['first_run']).__name__})"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Today-only log -> Miss return shape
# --------------------------------------------------------------------------- #

def test_today_only_log_returns_miss(write_entries):
    """Log contains only today entries -> Miss (today is not 'prior')."""
    write_entries([
        _make_entry(_today_iso(seconds_back=300), entry_id="t1"),
        _make_entry(_today_iso(seconds_back=100), entry_id="t2"),
    ])
    from standup import open_standup
    result = open_standup()
    assert result["prior_entry"] is None
    assert result["first_run"] is True


# --------------------------------------------------------------------------- #
# CRITERION — Single prior-day entry -> Hit return shape with full content
# --------------------------------------------------------------------------- #

def test_single_prior_day_entry_returns_hit(write_entries):
    """One yesterday entry -> Hit; prior_entry is that exact dict;
    first_run is False."""
    prior = _make_entry(
        _prior_day_iso(),
        type="open",
        entry_id="prior-1",
        session_id="sess-A",
        extra={
            "yesterday": "wrote tests for Story 7",
            "today": "writing tests for Story 8",
            "blockers": "none",
        },
    )
    write_entries([prior])
    from standup import open_standup
    result = open_standup()
    assert result["first_run"] is False, (
        f"first_run must be False on Hit; got {result['first_run']!r}"
    )
    assert result["prior_entry"] == prior, (
        f"prior_entry must be the full prior-day entry; "
        f"expected {prior!r}, got {result['prior_entry']!r}"
    )


def test_hit_first_run_is_false_boolean_identity(write_entries):
    """first_run on Hit must be exactly the boolean ``False``."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    result = open_standup()
    assert result["first_run"] is False, (
        f"first_run on Hit must be exactly False (boolean); "
        f"got {result['first_run']!r} "
        f"(type={type(result['first_run']).__name__})"
    )


def test_hit_prior_entry_is_dict(write_entries):
    """prior_entry on Hit is a dict (not a tuple, list, or namedtuple)."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    result = open_standup()
    assert isinstance(result["prior_entry"], dict), (
        f"prior_entry on Hit must be a dict; "
        f"got {type(result['prior_entry']).__name__}"
    )


def test_hit_prior_entry_carries_full_content(write_entries):
    """Every key/value from the source entry is present in prior_entry —
    no field stripped, no field added."""
    full = _make_entry(
        _prior_day_iso(),
        type="open",
        entry_id="entry-xyz-123",
        session_id="session-abc-456",
        extra={
            "yesterday": "Y",
            "today": "T",
            "blockers": "B",
        },
    )
    write_entries([full])
    from standup import open_standup
    result = open_standup()
    pe = result["prior_entry"]
    assert pe is not None
    for k, v in full.items():
        assert k in pe, f"prior_entry missing key {k!r}; got {pe!r}"
        assert pe[k] == v, (
            f"prior_entry[{k!r}] mismatch: expected {v!r}, got {pe[k]!r}"
        )
    # And no surprise keys.
    assert set(pe.keys()) == set(full.keys()), (
        f"prior_entry must preserve exactly the source keys; "
        f"expected {set(full.keys())}, got {set(pe.keys())}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Multiple prior-day entries -> Hit returns the LATEST
# --------------------------------------------------------------------------- #

def test_multiple_prior_entries_returns_latest(write_entries):
    """Three prior-day entries; open_standup returns the one with the
    highest timestamp (delegating to _latest_prior_entry)."""
    oldest = _make_entry(_iso_offset(_dt.timedelta(days=-5)), entry_id="oldest")
    middle = _make_entry(_iso_offset(_dt.timedelta(days=-2)), entry_id="middle")
    latest = _make_entry(_iso_offset(_dt.timedelta(hours=-25)), entry_id="latest")
    write_entries([oldest, middle, latest])
    from standup import open_standup
    result = open_standup()
    assert result["first_run"] is False
    assert result["prior_entry"] == latest, (
        f"open_standup must surface the latest prior entry; "
        f"expected entry id 'latest', got {result['prior_entry']!r}"
    )


def test_latest_picked_regardless_of_file_order(write_entries):
    """Insertion order intentionally NOT timestamp order -> still picks
    by highest timestamp."""
    oldest = _make_entry(_iso_offset(_dt.timedelta(days=-30)), entry_id="oldest")
    latest = _make_entry(_iso_offset(_dt.timedelta(hours=-25)), entry_id="latest")
    middle = _make_entry(_iso_offset(_dt.timedelta(days=-3)), entry_id="middle")
    # Latest written first; oldest second; middle last.
    write_entries([latest, oldest, middle])
    from standup import open_standup
    result = open_standup()
    assert result["prior_entry"] == latest


def test_today_and_prior_returns_prior(write_entries):
    """Today entry has higher absolute timestamp than the prior entry,
    but only entries strictly before today's local date qualify."""
    prior = _make_entry(_iso_offset(_dt.timedelta(hours=-25)), entry_id="prior")
    today = _make_entry(_iso_offset(_dt.timedelta(seconds=-30)), entry_id="today")
    write_entries([prior, today])
    from standup import open_standup
    result = open_standup()
    assert result["first_run"] is False
    assert result["prior_entry"] == prior, (
        "today's entry must NOT be selected even though its timestamp is "
        "numerically larger; only entries strictly before today qualify"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Round-trip preservation: prior_entry on Hit equals the
# entry's exact disk content (json.dumps + json.loads round-trips identically)
# --------------------------------------------------------------------------- #

def test_prior_entry_round_trips_exact_disk_content(write_entries):
    """prior_entry equals what json.loads of the entry's disk line
    produces — no in-flight mutation, no stripped fields."""
    on_disk = _make_entry(
        _prior_day_iso(),
        type="open",
        entry_id="rt-entry",
        session_id="rt-sess",
        extra={
            "yesterday": "y",
            "today": "t",
            "blockers": "none",
        },
    )
    log_path = write_entries([on_disk])

    # Read the disk content back the way _read_entries would.
    raw_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 1, (
        f"fixture invariant: expected 1 line on disk, got {len(raw_lines)}"
    )
    disk_dict = json.loads(raw_lines[0])

    from standup import open_standup
    result = open_standup()
    assert result["prior_entry"] == disk_dict, (
        f"prior_entry must equal the disk-read dict byte-for-byte after "
        f"json round-trip; expected {disk_dict!r}, got {result['prior_entry']!r}"
    )


def test_prior_entry_round_trip_via_real_helpers(isolated_log):
    """Build the log via the production helpers (_build_entry +
    _append_entry) and confirm open_standup surfaces what the writer
    produced. Catches drift between writer and reader contracts."""
    import standup
    # Build a prior-day entry via the real builder, then mutate the
    # timestamp so it falls on a strictly-prior local date. This exercises
    # the production schema without depending on _now_iso landing yesterday.
    sid = "stable-session-id-for-test"
    entry = standup._build_entry(
        type="open",
        session_id=sid,
        fields={"yesterday": "y", "today": "t", "blockers": "b"},
    )
    entry["timestamp"] = _prior_day_iso()
    standup._append_entry(entry)

    result = standup.open_standup()
    assert result["first_run"] is False
    assert result["prior_entry"] == entry, (
        f"open_standup must round-trip the production-built entry; "
        f"expected {entry!r}, got {result['prior_entry']!r}"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Function does NOT write to log
# (file size unchanged before and after the call)
# --------------------------------------------------------------------------- #

def test_does_not_create_log_when_absent(isolated_log):
    """LOG_PATH does not exist on entry; calling open_standup must not
    create it. (close_standup / submit_open are responsible for writes.)"""
    assert not isolated_log.exists()
    from standup import open_standup
    open_standup()
    assert not isolated_log.exists(), (
        "open_standup must not create LOG_PATH on a Miss path; "
        "writing is submit_open's responsibility (Story 9)"
    )


def test_does_not_modify_existing_log_size(write_entries):
    """File size before == file size after one open_standup call."""
    prior = _make_entry(_prior_day_iso(), entry_id="p")
    log_path = write_entries([prior])
    size_before = log_path.stat().st_size
    from standup import open_standup
    open_standup()
    size_after = log_path.stat().st_size
    assert size_before == size_after, (
        f"open_standup must not write to LOG_PATH; "
        f"size went from {size_before} to {size_after}"
    )


def test_does_not_modify_existing_log_bytes(write_entries):
    """Byte-for-byte equality of log file before vs after the call."""
    prior = _make_entry(_prior_day_iso(), entry_id="p")
    log_path = write_entries([prior])
    bytes_before = log_path.read_bytes()
    from standup import open_standup
    open_standup()
    bytes_after = log_path.read_bytes()
    assert bytes_before == bytes_after, (
        "open_standup must not modify any byte of LOG_PATH; "
        "writing is submit_open's responsibility (Story 9)"
    )


def test_does_not_modify_existing_entries(write_entries):
    """Existing entries are untouched (parsed equality before vs after)."""
    prior = _make_entry(
        _prior_day_iso(),
        entry_id="p",
        session_id="s",
        extra={"yesterday": "y", "today": "t", "blockers": "b"},
    )
    log_path = write_entries([prior])
    lines_before = log_path.read_text(encoding="utf-8").splitlines()
    parsed_before = [json.loads(ln) for ln in lines_before if ln.strip()]
    from standup import open_standup
    open_standup()
    lines_after = log_path.read_text(encoding="utf-8").splitlines()
    parsed_after = [json.loads(ln) for ln in lines_after if ln.strip()]
    assert parsed_before == parsed_after, (
        "open_standup must not mutate any existing entry"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Idempotent w.r.t. log state: repeated calls don't change the log
# --------------------------------------------------------------------------- #

def test_idempotent_across_many_calls(write_entries):
    """Calling open_standup() many times in a row must leave the log
    completely unchanged."""
    prior = _make_entry(_prior_day_iso(), entry_id="p")
    log_path = write_entries([prior])
    bytes_before = log_path.read_bytes()
    from standup import open_standup
    for _ in range(10):
        open_standup()
    bytes_after = log_path.read_bytes()
    assert bytes_before == bytes_after, (
        "open_standup must be log-idempotent across repeated calls"
    )


def test_idempotent_when_log_absent(isolated_log):
    """Repeated calls on a Miss must not create the log file."""
    from standup import open_standup
    for _ in range(10):
        open_standup()
    assert not isolated_log.exists(), (
        "open_standup must not create LOG_PATH even after repeated calls "
        "on a Miss"
    )


# --------------------------------------------------------------------------- #
# CRITERION — Each call has fresh session_id even if log unchanged
# (proves session_id is minted per-call, not cached on log state)
# --------------------------------------------------------------------------- #

def test_session_id_unique_across_repeat_calls_unchanged_log(write_entries):
    """Same log content; back-to-back calls; every session_id distinct."""
    write_entries([_make_entry(_prior_day_iso(), entry_id="p")])
    from standup import open_standup
    sids = [open_standup()["session_id"] for _ in range(10)]
    assert len(set(sids)) == 10, (
        f"open_standup must not cache session_id even when log is "
        f"unchanged; got {len(set(sids))} unique values across 10 calls"
    )


def test_prior_entry_stable_across_repeat_calls(write_entries):
    """While session_id changes per call, prior_entry must reflect the
    log state and remain stable when the log is unchanged."""
    prior = _make_entry(_prior_day_iso(), entry_id="p")
    write_entries([prior])
    from standup import open_standup
    a = open_standup()
    b = open_standup()
    assert a["prior_entry"] == b["prior_entry"] == prior
    assert a["first_run"] is False
    assert b["first_run"] is False
    # And session_ids did differ.
    assert a["session_id"] != b["session_id"]


# --------------------------------------------------------------------------- #
# EDGE CASE — prior_entry / first_run reflect log state at call time
# (a log that gains a prior-day entry between calls flips Miss -> Hit)
# --------------------------------------------------------------------------- #

def test_prior_entry_reflects_log_state_at_call_time(isolated_log, write_entries):
    """Empty log -> Miss; then writing a prior-day entry and calling
    again -> Hit. Confirms open_standup reads the log fresh on each call."""
    from standup import open_standup
    # 1. Empty log -> Miss.
    miss = open_standup()
    assert miss["prior_entry"] is None
    assert miss["first_run"] is True
    # 2. Add a prior-day entry, call again -> Hit.
    prior = _make_entry(_prior_day_iso(), entry_id="newly-added")
    write_entries([prior])
    hit = open_standup()
    assert hit["first_run"] is False
    assert hit["prior_entry"] == prior


# --------------------------------------------------------------------------- #
# EDGE CASE — Return value type contracts
# --------------------------------------------------------------------------- #

def test_returned_dict_is_not_shared_across_calls(isolated_log):
    """Two calls must return distinct dict objects (no mutable shared
    state via a cached dict reference)."""
    from standup import open_standup
    a = open_standup()
    b = open_standup()
    assert a is not b, (
        "open_standup must mint a fresh dict per call; "
        "returning a shared/cached reference is unsafe"
    )


def test_session_id_value_is_lowercase(isolated_log):
    """uuid4().hex returns lowercase. Adversarial: catch a stub that
    upper-cases the hex or uses uuid4().hex.upper()."""
    from standup import open_standup
    sid = open_standup()["session_id"]
    assert sid == sid.lower(), (
        f"session_id must be lowercase hex; got {sid!r}"
    )
