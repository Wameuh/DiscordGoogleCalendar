# Agent 3 - Testing Code Reviewer

Status: Changes requested
Reviewed TODO: TODO 3: Google Calendar Read Path
Review iteration: 1
Reviewed files:

- `tests/test_google_calendar_read_path.py`

## Findings

- Severity: Low
  File: `tests/test_google_calendar_read_path.py:112`
  Issue: The test constructs `OAuthTokenMetadata` with `created_at=date(2026, 5, 2)`, but the production dataclass declares `created_at` as `datetime`.
  Impact: The test boundary does not honor the typed production contract, so a future type-checking pass or stricter metadata behavior could fail even though the test currently passes at runtime.
  Required change: Use a `datetime` value for `created_at`, preferably a fixed deterministic timestamp.

- Severity: Low
  File: `tests/test_google_calendar_read_path.py:127`
  Issue: The `monkeypatch` pytest fixture is annotated as `pytest.MonkeyPatch` instead of using the workspace rule's `TYPE_CHECKING` fixture-type import pattern.
  Impact: This deviates from the test typing convention required for pytest fixtures and makes the file inconsistent with the project's testing guidance.
  Required change: Import `TYPE_CHECKING`, add `from _pytest.monkeypatch import MonkeyPatch` under that guard, and annotate the fixture as `MonkeyPatch`.

## Approval Notes

The behavior coverage is otherwise meaningful for this TODO: tests use pytest, include docstrings and return annotations, avoid real Google network calls through deterministic fakes, assert the Calendar `events.list` contract, validate read-only OAuth guardrails, cover timed and all-day mapping, malformed time payloads, cancellation filtering, out-of-window filtering, and deduplication. I ran `uv run pytest tests/test_google_calendar_read_path.py`, and the 9 tests in this file pass.

Residual optional gaps that do not block approval after the required typing fixes: the client response sanitation path for non-list `items` or non-dict list entries, `iCalUID` fallback, mixed all-day/timed rejection, default title behavior, optional text trimming, and invalid non-refreshable credential paths could be added later if those behaviors become regression-sensitive.
