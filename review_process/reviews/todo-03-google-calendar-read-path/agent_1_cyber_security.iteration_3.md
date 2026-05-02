# Agent 1 - Cyber Security Reviewer

Status: Approved
Reviewed TODO: TODO 3 - Google Calendar Read Path
Review iteration: 3
Reviewed files:

- `src/discordcalendarbot/calendar/auth.py`
- `src/discordcalendarbot/calendar/client.py`
- `src/discordcalendarbot/config.py`
- `tests/test_google_calendar_read_path.py`
- `pyproject.toml`
- `uv.lock`

## Findings

No security findings remain.

## Approval Notes

The remaining timeout finding from iteration 2 is resolved. `build_calendar_service()` now constructs an `httplib2.Http` instance with the configured `request_timeout_seconds`, wraps it in `google_auth_httplib2.AuthorizedHttp`, and passes that bounded authorized transport to `googleapiclient.discovery.build()` with discovery caching disabled. `GoogleCalendarClient.list_events_for_window()` still wraps the executor await in `asyncio.wait_for`, so callers retain a coroutine-level guard while the synchronous SDK network path also has a finite transport timeout.

The timeout value is still validated through `GOOGLE_REQUEST_TIMEOUT_SECONDS` in `load_settings()` with an inclusive `1..120` second range. The new `google-auth-httplib2` dependency is declared in `pyproject.toml` and locked in `uv.lock`; it is a focused Google auth transport adapter needed to apply the timeout to the existing Google API client.

Least-privilege OAuth handling remains acceptable. Stored token JSON scopes are validated before `Credentials.from_authorized_user_info()` is called, credentials are revalidated before and after refresh, and the accepted scope remains exactly `https://www.googleapis.com/auth/calendar.readonly`. The reviewed code does not introduce hard-coded production secrets, OAuth tokens, API keys, calendar IDs, Discord IDs, or logging of credential/event payload material.

The test coverage is security-relevant and adequate for this follow-up: it verifies transport timeout wiring without network access, rejects broader stored-token scopes, exercises pagination, and uses fakes/mocks for Google Calendar boundaries. Reported checks pass: `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` with 32 passed and one Google Python 3.10 deprecation warning.

Residual risk: the Google Calendar client still depends on the synchronous Google API SDK, so cancellation cannot forcibly stop already-running Python worker code. With the added transport timeout plus the existing `asyncio.wait_for` boundary, this is accepted for TODO 3.
