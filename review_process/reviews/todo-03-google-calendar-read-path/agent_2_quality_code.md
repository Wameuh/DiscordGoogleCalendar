# Agent 2 - Quality Code Reviewer

Status: Changes requested
Reviewed TODO: TODO 3 - Google Calendar Read Path
Review iteration: 1
Reviewed files:

- `ARCHITECTURE.md`
- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `.cursor/rules/python-fastapi.mdc`
- `review_process/review_agents.md`
- `src/discordcalendarbot/calendar/auth.py`
- `src/discordcalendarbot/calendar/client.py`
- `src/discordcalendarbot/calendar/mapper.py`
- `src/discordcalendarbot/domain/digest.py`
- `src/discordcalendarbot/domain/events.py`
- `src/discordcalendarbot/cli.py`
- `tests/test_google_calendar_read_path.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/calendar/auth.py:68`
  Issue: `load_authorized_credentials()` passes `[READONLY_CALENDAR_SCOPE]` into `Credentials.from_authorized_user_file()` before validating `credentials.scopes`. With the Google auth library, the resulting `Credentials.scopes` can reflect the requested scopes supplied by the caller rather than the scopes recorded in the token file, so the subsequent `validate_readonly_scopes(credentials.scopes)` check does not reliably verify what the loaded OAuth token actually grants.
  Impact: This weakens the architecture boundary that says runtime must verify loaded credentials contain only the v1 read-only Calendar scope. Future maintainers may believe broad-scope token files are rejected when this loader can normalize the in-memory credentials to the expected scope first. That is both a maintainability trap and an architecture-fit issue for the read path.
  Required change: Validate the scopes recorded in the authorized-user token data before constructing credentials with requested scopes, or load credentials without overriding scopes and validate the loaded grant before returning. Add a focused regression test using a token payload that records a broader Calendar scope and assert `load_authorized_credentials()` raises `GoogleAuthError`.

## Approval Notes

The calendar client and mapper otherwise fit the architecture well: Google SDK calls are isolated behind an injected adapter and `asyncio.to_thread`, raw event mapping is pure and typed, local-day overlap filtering stays in the domain boundary, and tests avoid real network calls.

Docstrings, type annotations, naming, and module responsibilities are generally consistent with the workspace rules. No FastAPI-specific code was added.

Verified checks:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`

Residual quality risk after the required fix is mainly future wiring: the OAuth browser bootstrap command and startup composition still need to call these primitives consistently as later TODOs implement operator commands and runtime integration.
