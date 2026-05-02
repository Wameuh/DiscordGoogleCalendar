# Agent 4 - Integration test reviewer

Status: Changes requested
Reviewed TODO: TODO 3 - Google Calendar Read Path
Review iteration: 1
Reviewed files:

- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `.cursor/rules/python-fastapi.mdc`
- `ARCHITECTURE.md`
- `review_process/review_agents.md`
- `src/discordcalendarbot/calendar/auth.py`
- `src/discordcalendarbot/calendar/client.py`
- `src/discordcalendarbot/calendar/mapper.py`
- `src/discordcalendarbot/domain/digest.py`
- `src/discordcalendarbot/domain/events.py`
- `src/discordcalendarbot/services/digest_service.py`
- `src/discordcalendarbot/app.py`
- `tests/test_google_calendar_read_path.py`
- `pyproject.toml`

## Findings

- Severity: High
  File: `src/discordcalendarbot/calendar/auth.py:68`
  Issue: `load_authorized_credentials()` passes `[READONLY_CALENDAR_SCOPE]` into `Credentials.from_authorized_user_file()` and then validates `credentials.scopes`. The Google credentials object reports the requested scopes supplied at load time, so a token JSON that records a broader stored scope can still appear read-only at this boundary.
  Impact: Startup/service wiring can accept a refresh token that was originally granted broader Calendar access, which violates the architecture's least-privilege and fail-closed scope validation requirement for the Google read path.
  Required change: Validate the token file's stored/granted scope metadata before constructing or accepting the credentials, then add an integration-style test proving `load_authorized_credentials()` rejects a token JSON containing `https://www.googleapis.com/auth/calendar` even when the loader requests the read-only scope.

- Severity: Medium
  File: `src/discordcalendarbot/calendar/client.py:48`
  Issue: The Google Calendar adapter executes only one `events().list(...).execute()` call and does not follow `nextPageToken`.
  Impact: Future digest service wiring can silently miss events on busy calendars because only the first page of the bounded local-day query is returned. Unit checks currently assert the first request parameters and executor isolation, but they do not protect full cross-page retrieval behavior.
  Required change: Loop on `nextPageToken`, pass `pageToken` only for continuation requests, accumulate dictionary `items` from each page, and add a fake-service test that verifies pagination remains inside the `asyncio.to_thread` executor boundary while preserving the required `events.list` parameters.

## Approval Notes

The implemented modules are otherwise aligned with the planned architecture boundaries for TODO 3. Google API calls are isolated in `calendar/client.py` and run through `asyncio.to_thread`; the adapter sends the required bounded-window parameters (`calendarId`, `timeMin`, `timeMax`, `singleEvents`, `orderBy`, `showDeleted`, and `timeZone`); mapping is separate from the client; local-day filtering reuses the pure domain overlap rule; cancelled events and duplicate stable identities are filtered before future tag filtering and digest formatting.

Local checks completed successfully:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest` with 29 passed tests

Approval is withheld until the credential-scope validation boundary checks the stored grant rather than only the requested load scope, and the Calendar client handles paginated `events.list` responses so future service wiring cannot drop valid events.
