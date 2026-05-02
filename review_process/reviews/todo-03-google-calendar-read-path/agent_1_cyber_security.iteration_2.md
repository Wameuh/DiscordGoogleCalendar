# Agent 1 - Cyber Security Reviewer

Status: Changes requested
Reviewed TODO: TODO 3 - Google Calendar Read Path
Review iteration: 2
Reviewed files:

- `src/discordcalendarbot/calendar/auth.py`
- `src/discordcalendarbot/calendar/client.py`
- `src/discordcalendarbot/calendar/mapper.py`
- `tests/test_google_calendar_read_path.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/calendar/client.py:45`
  Issue: The read path now wraps the executor future in `asyncio.wait_for`, but the synchronous Google SDK call still runs inside the worker thread at `src/discordcalendarbot/calendar/client.py:98` and is not cancelled or bounded at the HTTP transport/request level. If `request.execute()` hangs, the coroutine returns after `request_timeout_seconds`, but the worker can remain blocked until the underlying client or OS times out. The tests also do not prove the SDK transport itself receives a finite timeout.
  Impact: Repeated stalled Google Calendar calls can consume executor workers in the long-running bot, delaying future digest runs and creating an avoidable availability risk. The coroutine-level timeout is a useful guard for callers, but it does not fully enforce the network timeout required by the security checklist.
  Required change: Build or inject the Google Calendar service with a bounded HTTP transport/request timeout derived from the validated `GOOGLE_REQUEST_TIMEOUT_SECONDS` setting, or otherwise make the per-request executor function use a cancellable/bounded transport. Keep the existing `asyncio.wait_for` as a caller-facing guard, and add a focused test proving the Google service/request construction receives a finite timeout.

## Approval Notes

The least-privilege credential fix is approved: `load_authorized_credentials()` validates scopes from the stored token JSON before constructing `Credentials`, and `refresh_credentials_if_needed()` revalidates credential scopes before and after refresh. This closes the previous risk where a broad-scope token file could be normalized into apparently read-only in-memory credentials.

The Google Calendar pagination fix is approved from a security and completeness perspective: the adapter follows `nextPageToken`, keeps `showDeleted=False`, filters non-dict items from raw responses, and does not introduce logging of raw event content or OAuth material.

No hard-coded OAuth secrets, API keys, calendar IDs, Discord IDs, or private token values were introduced. OAuth token overwrite protection and non-secret metadata writing remain in place.

Checks run during this review:

- `uv run ruff check .` - passed
- `uv run ruff format --check .` - passed
- `uv run pytest tests/test_google_calendar_read_path.py` - 11 passed
- `uv run pytest` - 31 passed

Approval is still withheld until the Google Calendar network call has a transport-level finite timeout, not only a coroutine wait timeout around the executor future.
