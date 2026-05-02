# Agent 5 - Documentation Reviewer

Status: Changes requested
Reviewed TODO: TODO 1: Project Foundation
Review iteration: 1
Reviewed files:

- `README.md`
- `ARCHITECTURE.md`
- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `review_process/review_agents.md`
- `.gitignore`
- `pyproject.toml`
- `src/discordcalendarbot/cli.py`
- `src/discordcalendarbot/app.py`
- `tests/test_project_foundation.py`

## Findings

- Severity: Medium
  File: `README.md:3`
  Issue: The README describes the repository as containing a bot that connects to Google Calendar and posts reminders, and lines 13-17 state that the bot runs with `discord.py`, schedules daily digests, uses OAuth, stores SQLite state, and supports operator commands. The current TODO 1 implementation is a scaffold: the CLI only builds a placeholder application descriptor, and the Discord, Google Calendar, scheduler, SQLite, and operator-command behavior is not implemented yet.
  Impact: A new user or reviewer may believe the bot can already be configured and run against Discord/Google Calendar, which could lead to failed setup attempts or unsafe assumptions about implemented security controls.
  Required change: Reword the README introduction and architecture summary to distinguish current foundation status from planned version 1 behavior. For example, state that the repository currently contains the project scaffold and architecture for a Discord Calendar Bot, and that the listed runtime capabilities are planned architecture, not yet implemented.

- Severity: Low
  File: `README.md:34`
  Issue: The README introduces `uv` tooling but does not document the foundation commands that are now supported by `pyproject.toml`, such as dependency sync, lint checks, format checks, and pytest.
  Impact: Developers do not have a concise setup and verification path for the newly added project tooling, even though TODO 1 added dependencies, Ruff configuration, pytest configuration, and `uv.lock`.
  Required change: Add a short development section with current commands, such as `uv sync --all-groups`, `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest`.

## Approval Notes

The architecture document is thorough and generally aligned with the intended module boundaries, `src/discordcalendarbot` package layout, `uv` tooling, security posture, and review workflow. The `.gitignore` secret/state patterns documented in `ARCHITECTURE.md` are present, and the project foundation test documents that behavior.

Approval is blocked only on README accuracy and developer onboarding clarity. Once the README separates current scaffold behavior from planned runtime behavior and includes the current `uv` verification commands, this documentation review can approve the TODO 1 foundation documentation.
