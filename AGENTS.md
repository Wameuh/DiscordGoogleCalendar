# Agent Instructions

This workspace uses Cursor rule files as the detailed source of coding guidance. Agents should read and follow the applicable rules before making changes.

## Workspace Rules

- Python best practices: `.cursor/rules/python-best-practices.mdc`
- FastAPI API development: `.cursor/rules/python-fastapi.mdc`

## Rule Selection

- Apply the Python best-practices rule for all Python files, tests, tooling, documentation, and project-structure changes.
- Apply the FastAPI rule when adding or editing API routes, routers, dependencies, request or response schemas, middleware, lifespan hooks, or service code used by a FastAPI application.
- When both rules apply, follow both. The general Python rule sets baseline quality expectations; the FastAPI rule adds API-specific conventions.

## Local Project Notes

- Prefer `uv` for dependency and command execution.
- Keep new source code under `src/discordcalendarbot` as the project grows.
- Keep tests under `tests`.
- Even when user conversation happens in French, write source code, tests, docstrings, comments, commit-ready documentation, and developer-facing messages in English unless the user explicitly requests localized user-facing content.
- Ensure each development follows SOLID architecture principles where they improve maintainability, testability, and clear responsibility boundaries.
- Comply with the existing architecture design. If a requested change conflicts with the architecture or reveals a design issue, discuss it with the user and agree on the path forward before changing the architecture.

## Commit Safety

- Before every commit, explicitly verify that no sensitive file or private runtime artifact is staged.
- Never commit `.env`, `.env.*`, `credentials.json`, `token.json`, OAuth token files, Discord tokens, Google credentials, SQLite databases, logs, local archives, downloaded binaries, cache folders, or private calendar/Discord data.
- Prefer explicit `git add <path>` for intended files. Avoid broad staging such as `git add -A` unless the staged file list is reviewed immediately afterward.
- Before committing, inspect:
  - `git status --short`
  - `git diff --cached --name-only`
  - `git diff --cached`
- If any sensitive path or secret-like content is staged, unstage it before committing and update `.gitignore` or documentation if needed.
- Each final response after a commit must mention that the staged files were checked for sensitive content.

## Review Subagents

- Use `review_process/review_agents.md` as the source of truth for review subagent roles and prompts.
- For each completed TODO item, create a review folder under `review_process/reviews/` using this format: `todo-<number>-<short-slug>/`.
- Each review subagent must write its own markdown report in that TODO review folder:
  - `agent_1_cyber_security.md`
  - `agent_2_quality_code.md`
  - `agent_3_testing_code.md`
  - `agent_4_integration_test.md`
  - `agent_5_documentation.md`
- After completing each planned TODO item, run the relevant review subagents before moving to the next TODO when the change touches code, tests, architecture, documentation, configuration, dependencies, CI, or security-sensitive behavior.
- Use all five review subagents before final delivery for any non-trivial development task:
  - Agent 1: Cyber security reviewer.
  - Agent 2: Quality code reviewer.
  - Agent 3: Testing code reviewer.
  - Agent 4: Integration test reviewer.
  - Agent 5: Documentation reviewer.
- Provide each subagent with the completed TODO item, changed files, relevant diff or summary, applicable architecture notes, and the rule files listed above.
- Treat subagent feedback as review findings. Fix confirmed issues before continuing. If a finding conflicts with the architecture design or requires a product decision, discuss it with the user and agree on the path forward.
- Continue the review loop until every required reviewer report has `Status: Approved`. If any report has `Status: Changes requested`, fix the issues and request another review from the affected reviewer before proceeding.
- Summarize which review subagents ran and what was addressed in the final response.
