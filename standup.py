"""Standup tool — main module (skeleton).

Story 1 defines only the module shape:
  - the LOG_PATH constant, computed from this file's location
  - three public functions as stubs that raise NotImplementedError

Story 2 adds two private timestamp helpers (_now_iso, _parse_iso) used
by later stories to construct and parse log entries with local-offset
ISO 8601 timestamps. They are intentionally NOT in __all__.

Implementations land in subsequent stories. Stdlib only; Python 3.10+.
"""

from __future__ import annotations

import datetime as _dt
import json as _json
import uuid as _uuid
import warnings as _warnings
from pathlib import Path

# --------------------------------------------------------------------------- #
# LOG_PATH — resolved relative to this module file (NOT hardcoded).
# Computing from __file__ makes the path correct regardless of cwd or where
# the package is installed/cloned, which the acceptance tests verify by
# changing cwd between imports.
# --------------------------------------------------------------------------- #

LOG_PATH: Path = Path(__file__).resolve().parent / "log.jsonl"


# --------------------------------------------------------------------------- #
# Public API — stubs only. Each raises NotImplementedError on call.
# Future stories will fill in behavior; the signatures here are the contract
# downstream stories must honor.
# --------------------------------------------------------------------------- #

def open_standup() -> dict:
    """Open a new standup session.

    Mints a fresh session id and looks up the latest prior-day entry in
    the log (without writing to it). Returns a dict with exactly three
    keys:

        ``session_id``   — a fresh 32-char lowercase hex id (uuid4)
                           minted on every call (no caching).
        ``prior_entry``  — the latest entry whose local-TZ calendar date
                           is strictly before today, or ``None`` when no
                           qualifying entry exists.
        ``first_run``    — ``True`` when ``prior_entry`` is ``None``,
                           ``False`` otherwise.

    Reads the log on every call so the result reflects current state.
    Does not create, modify, or truncate ``LOG_PATH`` — writing is the
    responsibility of ``submit_open`` (Story 9). Returns a fresh dict
    object per call; no shared mutable state.
    """
    session_id = _new_session_id()
    prior = _latest_prior_entry()
    return {
        "session_id": session_id,
        "prior_entry": prior["prior_entry"],
        "first_run": prior["first_run"],
    }


def submit_open(
    session_id: str,
    yesterday: str,
    today: str,
    blockers: str,
) -> dict:
    """Submit an open-phase standup entry for ``session_id``.

    Public glue between the open-phase command and the log: validates
    ``session_id`` is a non-empty string, delegates entry construction
    (and field-value validation) to ``_build_entry`` with ``type='open'``,
    delegates persistence to ``_append_entry``, and returns the entry
    that was written so callers can verify or echo it.

    The returned dict equals the entry on disk (no copy / no drift); a
    fresh dict is produced per call. Field-value type checks live in
    ``_build_entry`` — passing a non-string for ``yesterday``, ``today``,
    or ``blockers`` raises ``TypeError`` naming the offending field.

    Raises:
        ValueError: ``session_id`` is empty, or (per this function's
            contract) is not a string.
        TypeError: any of ``yesterday`` / ``today`` / ``blockers`` is
            not a string (raised by ``_build_entry``).
    """
    # Validate session_id locally so the error tone is specific to this
    # function's contract; _build_entry would also reject these values
    # but its message is framed for its own callers.
    if not isinstance(session_id, str):
        raise ValueError(
            f"session_id must be a string, got {type(session_id).__name__}"
        )
    if not session_id:
        raise ValueError("session_id must not be empty")

    # _build_entry validates field-value types and constructs the dict.
    # Routing through it keeps schema rules in exactly one place.
    entry = _build_entry(
        type="open",
        session_id=session_id,
        fields={
            "yesterday": yesterday,
            "today": today,
            "blockers": blockers,
        },
    )

    # _append_entry is the single source of truth for log writes.
    _append_entry(entry)
    return entry


def close_standup(
    session_id: str,
    shifted: str,
    tomorrows_first_move: str,
    blocking: str,
) -> dict:
    """Submit a close-phase standup entry for ``session_id``.

    Public glue between the close-phase command and the log: validates
    ``session_id`` is a non-empty string, delegates entry construction
    (and field-value validation) to ``_build_entry`` with ``type='close'``,
    delegates persistence to ``_append_entry``, and returns the entry
    that was written so callers can verify or echo it.

    Per PO v2 Req 10 ("no orphan recovery"), this function does NOT
    enforce the existence of a matching open entry — it writes the
    close entry regardless of session_id pairing — and does NOT enforce
    one-close-per-session uniqueness.

    The returned dict equals the entry on disk (no copy / no drift); a
    fresh dict is produced per call. Field-value type checks live in
    ``_build_entry`` — passing a non-string for ``shifted``,
    ``tomorrows_first_move``, or ``blocking`` raises ``TypeError``
    naming the offending field.

    Raises:
        ValueError: ``session_id`` is empty, or (per this function's
            contract) is not a string.
        TypeError: any of ``shifted`` / ``tomorrows_first_move`` /
            ``blocking`` is not a string (raised by ``_build_entry``).
    """
    # Validate session_id locally so the error tone is specific to this
    # function's contract; _build_entry would also reject these values
    # but its message is framed for its own callers.
    if not isinstance(session_id, str):
        raise ValueError(
            f"session_id must be a string, got {type(session_id).__name__}"
        )
    if not session_id:
        raise ValueError("session_id must not be empty")

    # _build_entry validates field-value types and constructs the dict.
    # Routing through it keeps schema rules in exactly one place.
    entry = _build_entry(
        type="close",
        session_id=session_id,
        fields={
            "shifted": shifted,
            "tomorrows_first_move": tomorrows_first_move,
            "blocking": blocking,
        },
    )

    # _append_entry is the single source of truth for log writes.
    _append_entry(entry)
    return entry


def history(window: str) -> str:
    """Return rendered standup history for the given time ``window``.

    Accepts exactly two window values:

        ``"this week"``   — rolling trailing 7 days from now
        ``"last month"``  — rolling trailing 30 days from now

    Reads existing entries via ``_read_entries`` (read-only — never
    writes) and parses each entry's timestamp via ``_parse_iso``. Filters
    to entries whose timestamp falls within the rolling window, groups
    them by their local-calendar date (YYYY-MM-DD header), orders date
    groups chronologically (oldest first), and within each group orders
    entries by timestamp ascending. Each entry renders as
    ``TYPE TIMESTAMP`` followed by indented ``key=value`` lines for its
    fields.

    Returns plain text (no ANSI escapes). Empty windows return a
    documented empty-state string rather than the literal empty string
    or an exception.

    Raises:
        ValueError: ``window`` is not one of the two accepted strings.
            The message names the offending value AND lists the valid
            options. Non-string ``window`` also raises ``ValueError``
            (the spec accepts either ``ValueError`` or ``TypeError``;
            we standardize on ``ValueError`` so all bad-window inputs
            land in the same except clause for callers).
    """
    VALID = ("this week", "last month")

    if not isinstance(window, str):
        raise ValueError(
            f"window must be a string, got {type(window).__name__}; "
            f"valid options are {list(VALID)}"
        )
    if window not in VALID:
        raise ValueError(
            f"window must be one of {list(VALID)}, got {window!r}"
        )

    now = _dt.datetime.now().astimezone()
    if window == "this week":
        cutoff = now - _dt.timedelta(days=7)
        empty_msg = "(no standup entries in this week)"
    else:  # "last month"
        cutoff = now - _dt.timedelta(days=30)
        empty_msg = "(no standup entries in last month)"

    entries, _skipped = _read_entries()

    in_range: list[tuple[_dt.datetime, dict]] = []
    for entry in entries:
        ts_str = entry.get("timestamp")
        if not isinstance(ts_str, str) or not ts_str:
            continue
        try:
            ts = _parse_iso(ts_str)
        except (ValueError, TypeError):
            continue
        if ts < cutoff:
            continue
        if ts > now:
            # Future-dated entries are not "history".
            continue
        in_range.append((ts, entry))

    if not in_range:
        return empty_msg

    # Sort chronologically (oldest first). Stable sort preserves file
    # order for equal timestamps.
    in_range.sort(key=lambda pair: pair[0])

    # Group by local-calendar date. Build the order list as we go so
    # iteration mirrors chronological order (oldest day first).
    groups: dict[str, list[tuple[_dt.datetime, dict]]] = {}
    order: list[str] = []
    for ts, entry in in_range:
        local_date = ts.astimezone().date().isoformat()
        if local_date not in groups:
            groups[local_date] = []
            order.append(local_date)
        groups[local_date].append((ts, entry))

    # Render each date group as: header line, then per-entry block.
    # Entry header line carries `type` and `timestamp`; remaining keys
    # render below as indented `key=value` pairs. `id` and `session_id`
    # appear in that block so an operator can correlate amends to their
    # targets and so test fixtures that tag entries by id can verify
    # the right entry made it through filtering.
    SKIP_FIELD_KEYS = {"type", "timestamp"}  # rendered in the header line
    FIELD_ORDER = {
        "open": ["id", "session_id", "yesterday", "today", "blockers"],
        "close": ["id", "session_id", "shifted", "tomorrows_first_move",
                  "blocking"],
    }

    blocks: list[str] = []
    for date_str in order:
        lines: list[str] = [date_str]
        for ts, entry in groups[date_str]:
            etype = entry.get("type", "?")
            timestamp = entry.get("timestamp", "")
            lines.append(f"  {etype} {timestamp}")
            ordered_keys = FIELD_ORDER.get(etype)
            if ordered_keys is None:
                # amend OR unknown — render every non-header key the
                # entry carries, in insertion order. amend mirrors the
                # open or close shape; id / session_id / amends_id all
                # surface so the entry can be traced.
                ordered_keys = [
                    k for k in entry.keys() if k not in SKIP_FIELD_KEYS
                ]
            for k in ordered_keys:
                if k in entry:
                    lines.append(f"    {k}={entry[k]}")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Private timestamp helpers (Story 2).
#
# Intentionally underscore-prefixed and NOT exported in __all__: they are
# implementation details that later stories use to build log entries.
# --------------------------------------------------------------------------- #

def _now_iso() -> str:
    """Return the current local wall-clock time as an ISO 8601 string
    with a concrete timezone offset.

    Uses ``datetime.now().astimezone()`` — calling ``astimezone`` with no
    argument attaches the local system's timezone to a naive ``now()``,
    which is the stdlib idiom for "current local time, tz-aware". The
    result includes microseconds and a ``[+-]HH:MM`` offset.
    """
    return _dt.datetime.now().astimezone().isoformat()


def _parse_iso(s: str) -> _dt.datetime:
    """Parse an ISO 8601 string into a timezone-aware ``datetime``.

    Accepts the forms produced by ``_now_iso`` plus other valid ISO 8601
    inputs that ``datetime.fromisoformat`` understands. Also accepts the
    trailing ``Z`` suffix (UTC) by normalizing it to ``+00:00`` before
    parsing — Python 3.10's ``fromisoformat`` does not accept ``Z``
    natively, so we handle it explicitly for portability.

    Raises ``ValueError`` on any input that is not a valid, tz-aware
    ISO 8601 datetime. Naive (offset-less) ISO inputs are rejected.
    Non-string inputs raise ``TypeError`` (loud, not silent).
    """
    if not isinstance(s, str):
        raise TypeError(
            f"_parse_iso requires a str, got {type(s).__name__}"
        )
    if not s:
        raise ValueError("_parse_iso received an empty string")

    # Normalize a trailing 'Z' (UTC) to '+00:00' so this works on
    # Python 3.10 as well as 3.11+. fromisoformat in 3.11+ accepts 'Z'
    # natively, but normalizing keeps behavior uniform across versions.
    candidate = s
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    parsed = _dt.datetime.fromisoformat(candidate)

    # ISO 8601 with offset -> tz-aware. Reject naive results so callers
    # can rely on the contract (round-trips preserve UTC instant).
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"_parse_iso requires a timezone-aware ISO 8601 string; "
            f"input {s!r} parsed to a naive datetime"
        )

    return parsed


# --------------------------------------------------------------------------- #
# Private id helpers (Story 3).
#
# Two distinct names are deliberate: call sites read clearer when an entry id
# is allocated by ``_new_entry_id()`` and a session id by ``_new_session_id()``,
# even though both produce values in the same uuid4 hex format. They are
# private (underscore-prefixed) and intentionally NOT exported in __all__.
#
# ``uuid.uuid4().hex`` yields exactly 32 lowercase hex characters with no
# dashes and no prefix — the format the acceptance tests assert.
# --------------------------------------------------------------------------- #

def _new_entry_id() -> str:
    """Return a fresh log-entry id: 32 lowercase hex chars (uuid4)."""
    return _uuid.uuid4().hex


def _new_session_id() -> str:
    """Return a fresh standup-session id: 32 lowercase hex chars (uuid4)."""
    return _uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# Private append-only writer (Story 5).
#
# Single source of truth for "write one entry to the JSONL log". Every
# future caller (open_standup, close_standup, etc.) routes through this
# helper so the append-only invariant lives in exactly one place.
#
# Design choices:
#   - Serialize the line BEFORE opening the file. If json.dumps raises
#     (non-serializable value) the file is never touched, so the existing
#     log cannot be partially corrupted.
#   - ensure_ascii=False keeps unicode characters as their actual UTF-8
#     bytes rather than \uXXXX escapes — round-trip preserves the source
#     glyphs exactly.
#   - newline="\n" suppresses Windows' default LF -> CRLF translation in
#     text mode; the spec mandates platform-independent LF terminators.
#   - Append mode ("a") with UTF-8 encoding; never reads, never truncates.
#
# Private (underscore-prefixed) and intentionally NOT in __all__.
# --------------------------------------------------------------------------- #

def _append_entry(entry: dict) -> None:
    """Append one entry as a JSON line to ``LOG_PATH``.

    Validates that ``entry`` is a ``dict`` (raises ``TypeError`` if not),
    serializes it with ``json.dumps(..., ensure_ascii=False)`` so that
    non-serializable values raise before the file is opened, then writes
    ``json_line + "\\n"`` in append mode with explicit UTF-8 encoding and
    LF-only line terminators.

    Returns ``None``. Never reads existing log content; never truncates.
    """
    if not isinstance(entry, dict):
        raise TypeError(
            f"_append_entry requires a dict, got {type(entry).__name__}"
        )

    # Serialize first so json.dumps's TypeError propagates cleanly without
    # leaving a half-written line on disk.
    json_line = _json.dumps(entry, ensure_ascii=False)

    with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(json_line + "\n")


# --------------------------------------------------------------------------- #
# Private resilient line-by-line reader (Story 6).
#
# Reads ``LOG_PATH`` and returns:
#   - ``entries``: list[dict] of successfully parsed JSON objects, in file
#     order
#   - ``skipped``: list[(line_number, raw_line)] for lines that failed to
#     parse as a JSON object — line numbers are physical 1-indexed positions
#
# Resilience contract:
#   - Missing or empty LOG_PATH -> ([], [])
#   - Blank / whitespace-only lines silently skipped (NOT in either list)
#   - Malformed JSON lines surface in ``skipped`` and trigger a single
#     ``warnings.warn`` naming the count and at least one location
#   - Non-dict top-level JSON values (numbers, arrays, strings) are treated
#     as malformed (entries is typed list[dict]; non-dicts have no place there)
#   - ``errors="replace"`` decodes binary garbage into replacement chars so
#     decode never raises; the resulting line then fails json.loads and
#     surfaces as malformed
#   - File-access OSErrors return whatever was collected so far rather than
#     raising — corrupt log must not bring the tool down
#
# Private (underscore-prefixed) and NOT in __all__.
# --------------------------------------------------------------------------- #

def _read_entries() -> tuple[list[dict], list[tuple[int, str]]]:
    """Read ``LOG_PATH`` line-by-line, returning (entries, skipped).

    Never raises on bad content. Surfaces malformed lines via
    ``warnings.warn`` (count + locations) so the operator can size the
    damage at a glance without losing the valid entries that survived.
    """
    entries: list[dict] = []
    skipped: list[tuple[int, str]] = []

    if not LOG_PATH.exists():
        return entries, skipped

    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
            for line_num, line in enumerate(fh, start=1):
                stripped = line.strip()
                if not stripped:
                    # Blank / whitespace-only line: silent skip.
                    continue
                try:
                    obj = _json.loads(stripped)
                except _json.JSONDecodeError:
                    skipped.append((line_num, line))
                    continue
                if not isinstance(obj, dict):
                    # Top-level non-dict JSON (number, array, string, bool,
                    # null) has no slot in entries (typed list[dict]); treat
                    # as malformed so the operator sees it.
                    skipped.append((line_num, line))
                    continue
                entries.append(obj)
    except OSError:
        # File-access failure mid-read: return what we have so far rather
        # than propagating. The contract is non-raising.
        return entries, skipped

    if skipped:
        line_nums = [str(ln) for ln, _ in skipped]
        _warnings.warn(
            f"_read_entries: skipped {len(skipped)} malformed "
            f"line(s) at line(s) {', '.join(line_nums)}",
            stacklevel=2,
        )

    return entries, skipped


# --------------------------------------------------------------------------- #
# Private entry-builder (Story 4).
#
# Single source of truth for "construct one log entry, validated against its
# type-specific schema". Every future caller (open_standup, close_standup,
# amend flows) routes through this helper so schema validation lives in
# exactly one place.
#
# Design choices:
#   - Always-present keys (id, session_id, type, timestamp) are minted from
#     the existing private helpers — _new_entry_id() and _now_iso() —
#     keeping id/timestamp generation centralized.
#   - The input ``fields`` dict is never mutated; values are copied key-by-key
#     into a fresh result dict so the returned object shares no references
#     with caller state.
#   - amends_id is added to the result ONLY when type='amend'. Non-amend
#     types must omit the key entirely; downstream JSON serialization treats
#     "key absent" and "key present with null" differently.
#   - Validation runs BEFORE any dict construction. A failed call raises
#     and returns nothing — callers never see a partial dict.
#   - The parameter name ``type`` shadows the builtin per the spec; we use
#     ``type(x).__name__`` style elsewhere in the module, but inside this
#     function we reach for the builtin via ``builtins`` only when needed
#     for error messages naming the offending Python type.
#
# Private (underscore-prefixed) and intentionally NOT in __all__.
# --------------------------------------------------------------------------- #

_OPEN_FIELDS = frozenset({"yesterday", "today", "blockers"})
_CLOSE_FIELDS = frozenset({"shifted", "tomorrows_first_move", "blocking"})
_VALID_ENTRY_TYPES = frozenset({"open", "close", "amend"})


def _build_entry(
    type: str,
    session_id: str,
    fields: dict,
    amends_id: str | None = None,
) -> dict:
    """Construct a fully-validated log entry dict for one of the three
    canonical entry types.

    Returns a fresh ``dict`` with the always-present keys
    ``id``, ``session_id``, ``type``, ``timestamp`` plus the
    type-specific field keys (and ``amends_id`` when ``type='amend'``).

    Raises ``ValueError`` for any schema or value-domain violation, and
    ``TypeError`` for non-dict ``fields`` or non-string field values.
    Validation is total — a failed call never returns a partial dict.
    """
    import builtins as _builtins

    # 1. validate `type` is the right Python type and the right value.
    if not isinstance(type, str):
        raise ValueError(
            f"type must be a string, got {_builtins.type(type).__name__}"
        )
    if type not in _VALID_ENTRY_TYPES:
        raise ValueError(
            f"type must be one of {set(_VALID_ENTRY_TYPES)}, got {type!r}"
        )

    # 2. validate session_id is a non-empty string.
    if not isinstance(session_id, str):
        raise ValueError(
            f"session_id must be a string, got "
            f"{_builtins.type(session_id).__name__}"
        )
    if not session_id:
        raise ValueError("session_id must not be empty")

    # 3. validate fields is a dict (TypeError per spec).
    if not isinstance(fields, dict):
        raise TypeError(
            f"fields must be a dict, got {_builtins.type(fields).__name__}"
        )

    # 4. validate amends_id rules — pairing with type matters BEFORE we
    #    care about field-key shape.
    if type == "amend":
        if amends_id is None:
            raise ValueError("amends_id is required when type='amend'")
        if not isinstance(amends_id, str):
            raise ValueError(
                f"amends_id must be a string, got "
                f"{_builtins.type(amends_id).__name__}"
            )
        if not amends_id:
            raise ValueError("amends_id must not be empty")
    else:
        if amends_id is not None:
            raise ValueError(
                f"amends_id is only valid with type='amend'; "
                f"got type={type!r} with amends_id={amends_id!r}"
            )

    # 5. validate field-key set against the type's expected schema.
    keys = frozenset(fields.keys())
    if type == "open":
        expected = _OPEN_FIELDS
    elif type == "close":
        expected = _CLOSE_FIELDS
    else:  # amend — must match open OR close
        if keys == _OPEN_FIELDS:
            expected = _OPEN_FIELDS
        elif keys == _CLOSE_FIELDS:
            expected = _CLOSE_FIELDS
        else:
            missing_open = _OPEN_FIELDS - keys
            extra_open = keys - _OPEN_FIELDS
            missing_close = _CLOSE_FIELDS - keys
            extra_close = keys - _CLOSE_FIELDS
            raise ValueError(
                f"type='amend' fields must mirror open "
                f"({set(_OPEN_FIELDS)}) or close ({set(_CLOSE_FIELDS)}); "
                f"got keys={set(keys)}; "
                f"vs open: missing={set(missing_open)}, extra={set(extra_open)}; "
                f"vs close: missing={set(missing_close)}, extra={set(extra_close)}"
            )

    if keys != expected:
        missing = expected - keys
        extra = keys - expected
        raise ValueError(
            f"type={type!r} requires fields {set(expected)}; "
            f"missing={set(missing)}, extra={set(extra)}"
        )

    # 6. validate every field value is a string. Naming the offending key
    #    in the error message is part of the contract.
    for k, v in fields.items():
        if not isinstance(v, str):
            raise TypeError(
                f"field {k!r} must be a string, got "
                f"{_builtins.type(v).__name__} value {v!r}"
            )

    # 7. construct the entry. Always-present keys first, then amends_id
    #    (if applicable), then the type-specific field values copied from
    #    the input dict — never aliasing.
    entry: dict = {
        "id": _new_entry_id(),
        "session_id": session_id,
        "type": type,
        "timestamp": _now_iso(),
    }
    if amends_id is not None:
        entry["amends_id"] = amends_id
    for k in expected:
        entry[k] = fields[k]
    return entry


# --------------------------------------------------------------------------- #
# Private latest-prior-entry lookup with sentinel (Story 7).
#
# Returns one of two shapes:
#   Hit:  {"prior_entry": <full entry dict>, "first_run": False}
#   Miss: {"prior_entry": None,              "first_run": True}
#
# "Latest prior" = the entry with the highest timestamp value among
# entries whose timestamp's local-TZ calendar date is STRICTLY BEFORE
# today's local calendar date. Today's entries and future-dated entries
# are excluded from candidacy.
#
# Routes through ``_read_entries`` and ``_parse_iso`` from prior stories
# so the resilience contract (corrupt-line skipping, missing-file
# handling) is inherited rather than reimplemented here.
#
# Private (underscore-prefixed) and intentionally NOT in __all__.
# --------------------------------------------------------------------------- #

def _latest_prior_entry() -> dict:
    """Find the latest entry strictly before today's local calendar date.

    Returns the Hit shape ``{"prior_entry": <dict>, "first_run": False}``
    when at least one prior-day entry exists, or the Miss shape
    ``{"prior_entry": None, "first_run": True}`` when no qualifying entry
    is present (missing log, empty log, all-today-or-future log, all
    corrupt log, etc.).
    """
    entries, _skipped = _read_entries()
    if not entries:
        return {"prior_entry": None, "first_run": True}

    # Today's local calendar date — the cutoff. Entries on this date or
    # later are excluded.
    now_aware = _dt.datetime.now().astimezone()
    today_local = now_aware.date()

    prior: list[tuple[_dt.datetime, dict]] = []
    for entry in entries:
        ts_str = entry.get("timestamp")
        if not isinstance(ts_str, str) or not ts_str:
            # Malformed — should not occur post-Story-6, but guard anyway.
            continue
        try:
            ts = _parse_iso(ts_str)
        except (ValueError, TypeError):
            continue
        # Compare in local TZ so "today" lines up with how the cutoff was
        # computed above.
        ts_local_date = ts.astimezone().date()
        if ts_local_date >= today_local:
            # Today or future calendar date — excluded.
            continue
        if ts > now_aware:
            # Belt-and-suspenders: a strictly-future timestamp shouldn't
            # land on a strictly-prior date, but exclude it if it does.
            continue
        prior.append((ts, entry))

    if not prior:
        return {"prior_entry": None, "first_run": True}

    # Highest timestamp wins; ties resolved by the stable sort keeping
    # file order, which doesn't matter for the contract (any tie-break
    # yields equal entries by the test fixtures).
    prior.sort(key=lambda pair: pair[0])
    latest = prior[-1][1]
    return {"prior_entry": latest, "first_run": False}


def amend(amends_id: str, fields: dict) -> dict:
    """Append an amendment entry that points at an existing target entry.

    Locates the target by ``amends_id`` via ``_read_entries``, validates
    that the target exists and is NOT itself an amend (amends are a flat
    layer over open/close, not a chain), then constructs the amend entry
    via ``_build_entry`` with ``type='amend'``, the target's
    ``session_id`` (INHERITED — not provided by caller), the caller's
    ``fields`` dict, and ``amends_id`` set to the target's id. Persists
    via ``_append_entry`` and returns the entry that was written.

    The original target entry's bytes on disk are never modified — the
    amend is appended after, preserving the append-only invariant of
    PO v2 Requirement 8.

    Field-key mirror enforcement (must match open or close shape exactly)
    and field-value type checks live in ``_build_entry``; passing a wrong
    field set raises ``ValueError`` and a non-string field value raises
    ``TypeError`` naming the offending field.

    Raises:
        ValueError: ``amends_id`` is not a string; ``amends_id`` is
            empty; no entry in the log has ``id == amends_id``; or the
            located target is itself an amend.
        TypeError: any field value is not a string (raised by
            ``_build_entry``).
    """
    # Validate amends_id locally so the error tone is specific to this
    # function's contract.
    if not isinstance(amends_id, str):
        raise ValueError(
            f"amends_id must be a string, got {type(amends_id).__name__}"
        )
    if not amends_id:
        raise ValueError("amends_id must not be empty")

    # Locate the target via the production reader. _read_entries inherits
    # the resilience contract (missing log -> [], malformed lines skipped).
    entries, _skipped = _read_entries()
    target = None
    for entry in entries:
        if entry.get("id") == amends_id:
            target = entry
            break
    if target is None:
        raise ValueError(f"no entry found with id {amends_id!r}")
    if target.get("type") == "amend":
        raise ValueError(
            f"cannot amend an amend (entry id {amends_id!r} is itself an amend)"
        )

    # The amend's field-key set must mirror the TARGET's type specifically.
    # _build_entry accepts either mirror for type='amend'; here we constrain
    # it further so amending an open target with close-shape fields (or
    # vice versa) raises before construction. Field-VALUE type checks
    # (non-string values) and any non-dict ``fields`` argument still flow
    # through _build_entry, which raises TypeError for those cases —
    # that's why we route through isinstance(fields, dict) here rather
    # than calling .keys() on a possibly-non-dict.
    target_type = target.get("type")
    if isinstance(fields, dict):
        keys = frozenset(fields.keys())
        if target_type == "open" and keys != _OPEN_FIELDS:
            missing = _OPEN_FIELDS - keys
            extra = keys - _OPEN_FIELDS
            raise ValueError(
                f"amend of an open target requires fields {set(_OPEN_FIELDS)}; "
                f"missing={set(missing)}, extra={set(extra)}"
            )
        if target_type == "close" and keys != _CLOSE_FIELDS:
            missing = _CLOSE_FIELDS - keys
            extra = keys - _CLOSE_FIELDS
            raise ValueError(
                f"amend of a close target requires fields {set(_CLOSE_FIELDS)}; "
                f"missing={set(missing)}, extra={set(extra)}"
            )

    # _build_entry validates fields (mirror shape + value types) and
    # constructs the dict. session_id is INHERITED from the target.
    entry = _build_entry(
        type="amend",
        session_id=target["session_id"],
        fields=fields,
        amends_id=amends_id,
    )

    # _append_entry is the single source of truth for log writes.
    _append_entry(entry)
    return entry


__all__ = [
    "LOG_PATH",
    "amend",
    "close_standup",
    "history",
    "open_standup",
    "submit_open",
]
