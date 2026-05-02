# Agent 3 - Testing Code Reviewer

Status: Changes requested
Reviewed TODO: TODO 1 - Project Foundation
Review iteration: 1
Reviewed files:

- `ARCHITECTURE.md`
- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `review_process/review_agents.md`
- `tests/test_project_foundation.py`
- `src/discordcalendarbot/config.py`
- `pyproject.toml`
- `.gitignore`
- Current git status and diff

## Findings

- Severity: Medium
  File: `tests/test_project_foundation.py:1`
  Issue: The foundation tests do not include the planned initial config-validation coverage. `ARCHITECTURE.md` lists TODO 1 as adding "initial security tests for ignore patterns and config validation", but the current suite only checks package metadata, default CLI exit status, and `.gitignore` patterns. `src/discordcalendarbot/config.py` is still a placeholder, so there is no regression test proving that missing or unsafe configuration fails closed.
  Impact: The project can appear to satisfy the foundation TODO while leaving the first security-sensitive configuration boundary untested. Later settings work could accidentally accept missing secrets, invalid timezones, invalid Discord IDs, or unsafe paths without an early failing test guiding the implementation.
  Required change: Add focused pytest coverage for the initial configuration contract, or narrow the TODO acceptance criteria if configuration validation is intentionally deferred. A minimal useful start would assert that the settings loader rejects missing required environment variables and accepts a fully populated valid environment without touching the network.

- Severity: Low
  File: `tests/test_project_foundation.py:23`
  Issue: The `.gitignore` test uses substring checks against the whole file.
  Impact: The test can pass if an expected pattern only appears as part of another pattern, in a comment, or in unrelated text. For example, `.env` can be satisfied by `.env.*`, so the test does not strictly protect the exact ignore entries required for local secrets and state.
  Required change: Parse `.gitignore` into normalized non-empty, non-comment lines and assert that the expected pattern set is a subset of those exact lines.

## Approval Notes

I ran `$env:UV_CACHE_DIR='.uv-cache'; uv run pytest`; the current suite passes with `3 passed`, but pytest emitted a cache warning because `.pytest_cache` could not be written in this workspace. The tests are typed, documented, located under `tests`, and use pytest rather than `unittest`.

Approval is blocked on the missing config-validation test coverage and the weak `.gitignore` assertion. No real network calls are present in the current tests.
