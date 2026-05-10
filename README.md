# standup-tool

A single-user, append-only daily-standup logging tool. Drives an
open / close cycle per day with five public functions and a single
JSONL log.

Part of a small development suite shaped on the same patterns:

- `standup-tool` — the daily-standup loop (this repo)
- `po-tool` — product-owner pipeline (interview → backlog → iteration)
- `sm-tool` — scrum-master pipeline (iteration → stories → handoff)

Each tool ships on the same shape: append-only JSONL log, content-oriented
schema, close-and-flow lifecycle. Two tools have shipped; the third is
in active build.

## What it does

A standup session opens, captures three answers (yesterday / today /
blockers), closes with three more (shifted / tomorrow's first move /
blocking), and the next session can read history at two windows. The
log is the source of truth — no separate database, no out-of-band
state. Every entry is appended, never edited; corrections happen by
appending an `amend` entry that points at its target.

## Public API

```python
from standup import (
    LOG_PATH,
    open_standup,
    submit_open,
    close_standup,
    history,
    amend,
)
```

| Function | Purpose |
|---|---|
| `open_standup()` | Mint a fresh session id; return the latest prior-day entry (if any) so the next standup has context. Read-only. |
| `submit_open(session_id, yesterday, today, blockers)` | Append the open-phase entry for the session. |
| `close_standup(session_id, shifted, tomorrows_first_move, blocking)` | Append the close-phase entry for the session. |
| `history(window)` | Render a chronological view of entries within a rolling window. Accepts `"this week"` (7 days) or `"last month"` (30 days). |
| `amend(amends_id, fields)` | Append a correction entry pointing at an existing open or close. Field shape must mirror the target's. |

`LOG_PATH` is computed from the module's location so the path is
correct regardless of working directory.

## Installation

Stdlib only — Python 3.10+. No external runtime dependencies.

```bash
git clone https://github.com/nicky2tymze/standup-tool
cd standup-tool
python -m pytest tests/
```

To use the module from your own code, add the repo to your `PYTHONPATH`
or import `standup` directly from a script that lives in the repo root.

## Schema

Every log line is a JSON object with these always-present keys:

| Key | Type | Meaning |
|---|---|---|
| `id` | str | 32-char lowercase hex (uuid4) |
| `session_id` | str | 32-char lowercase hex; groups one day's open + close + amends |
| `type` | str | `"open"` \| `"close"` \| `"amend"` |
| `timestamp` | str | ISO 8601 with explicit local TZ offset |

Plus the type-specific field set:

- `open` — `yesterday`, `today`, `blockers`
- `close` — `shifted`, `tomorrows_first_move`, `blocking`
- `amend` — same field set as the target it points at, plus `amends_id`

The schema separates **content words** (entities, like the field values
above) from **function words** (operators that connect them). Only
content has identity; structure is the grammar between them.

## Tests

690 tests across 13 test files. Run with:

```bash
python -m pytest tests/
```

Tests assert the API contract end-to-end: ids are minted fresh per
call, the log is append-only, malformed lines are skipped without
raising, the prior-day lookup uses local-TZ calendar boundaries,
amendments mirror the target type's shape, and so on.

## How it was built

This tool was dogfooded throughout its build — every commit added a
story, the next commit landed its tests passing. The pipeline was
test-writer → coder → reviewer per story, with each story closing
cleanly before the next opened (close-and-flow). The same shape
produced `po-tool` and is in use for `sm-tool`.

## License

MIT — see [LICENSE](LICENSE).

Copyright (c) 2026 Nick Trolian
