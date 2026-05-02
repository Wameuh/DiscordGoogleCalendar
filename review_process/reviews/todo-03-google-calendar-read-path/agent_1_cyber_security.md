# Agent 1 - Cyber Security Reviewer

Status: Changes requested
Reviewed TODO: TODO 3 - Google Calendar Read Path
Review iteration: 1
Reviewed files:

- `src/discordcalendarbot/calendar/auth.py`
- `src/discordcalendarbot/calendar/client.py`
- `src/discordcalendarbot/calendar/mapper.py`
- `tests/test_google_calendar_read_path.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/calendar/client.py:57`
  Issue: The Google Calendar SDK request is executed without an enforced request timeout in the adapter path. The code correctly moves the synchronous SDK call behind `asyncio.to_thread`, but `request.execute()` can still block indefinitely if the underlying Google HTTP service was not built with a bounded timeout. The validated `GOOGLE_REQUEST_TIMEOUT_SECONDS` setting is not wired into this read path or asserted by tests.
  Impact: A stalled Google API call can tie up executor workers, delay or prevent digest completion, and create avoidable availability risk in the long-running bot. In later scheduler/idempotency work, an unbounded calendar read can also interact badly with run locks and retry windows.
  Required change: Make the Google request timeout an explicit part of the Calendar client/service construction contract, using the validated `GOOGLE_REQUEST_TIMEOUT_SECONDS` value. Prefer constructing the Google service with a bounded HTTP transport timeout, and add a focused test proving the read path cannot be configured without a finite timeout. A coroutine-level timeout may be useful as a guard, but it should not be the only control because it does not stop the worker thread's underlying network call.

## Approval Notes

No hard-coded OAuth secrets, API keys, calendar IDs, or Discord identifiers were introduced in the reviewed files. OAuth scope validation is least-privilege and exact for the v1 read-only Calendar scope. Token overwrite protection is present for token writes and sidecar metadata writes. The sidecar metadata contains operator-verification context, not refresh tokens or client secrets.

The mapper keeps private event fields in memory for downstream domain processing and does not log them. Those fields remain untrusted and must still pass through the planned Discord sanitizer and URL policy before any Discord output path is approved.

Checks were provided as passing: `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` with 29 passing tests. Approval is withheld until the Google Calendar request timeout is enforced in the read path.
