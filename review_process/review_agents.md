# Review Subagents

Use these prompt templates when a development TODO item is completed. The main agent should provide the completed TODO item, changed files, relevant diff or implementation summary, applicable architecture notes, and any relevant rule files.

## Invocation Protocol

1. Complete one planned TODO item.
2. Identify which files and behaviors changed.
3. Create a review folder under `review_process/reviews/` using this format: `todo-<number>-<short-slug>/`.
4. Run the relevant review subagents using the prompts below.
5. Require each subagent to write its report as a markdown file in the TODO review folder.
6. Fix confirmed findings before starting the next TODO item.
7. Re-run the affected reviewers after fixes.
8. Continue the loop until every required reviewer report has `Status: Approved`.
9. If a finding conflicts with the architecture design or requires a product decision, discuss it with the user before changing the architecture.
10. Before final delivery, run all five review subagents for any non-trivial development task.

## Review Artifact Protocol

Each TODO review folder must contain one markdown report per required reviewer:

- `agent_1_cyber_security.md`
- `agent_2_quality_code.md`
- `agent_3_testing_code.md`
- `agent_4_integration_test.md`
- `agent_5_documentation.md`

Each report must use this structure:

```markdown
# Agent <number> - <reviewer name>

Status: Approved | Changes requested
Reviewed TODO: <todo title or identifier>
Review iteration: <number>
Reviewed files:

- `<path>`

## Findings

- Severity: Critical | High | Medium | Low
  File: `<path>:<line>`
  Issue: <what is wrong>
  Impact: <why it matters>
  Required change: <smallest useful fix>

## Approval Notes

<Use this section to explain why the reviewer approves, or what residual risk remains.>
```

The orchestrator must preserve previous review reports when a new iteration is needed. For follow-up reviews, append an iteration suffix before the extension, such as `agent_2_quality_code.iteration_2.md`.

## Approval Loop

- `Status: Approved` means the reviewer accepts the current changes for its review scope.
- `Status: Changes requested` means the orchestrator must fix or explicitly resolve findings before moving on.
- The orchestrator may not mark a TODO complete until every required reviewer has approved the latest relevant iteration.
- If the orchestrator disagrees with a finding, it must document the reason in the report folder and ask the user when the decision affects architecture, security, product behavior, or test strategy.
- The final response must summarize the review folder path, reviewer statuses, and fixes made from review feedback.

## Agent 1 - Cyber Security Reviewer

### Goal

Review completed changes for security risks, unsafe defaults, secrets handling, dependency risk, authentication and authorization issues, input validation gaps, logging leaks, and network or API misuse.

### Initial Prompt

You are Agent 1, the cyber security reviewer for this workspace.

Review the completed TODO item from a security perspective. Focus on concrete risks introduced or missed by the change.

Inputs you will receive:

- Completed TODO item.
- Changed files and relevant diff or summary.
- Relevant architecture notes.
- Applicable workspace rules from `AGENTS.md` and `.cursor/rules`.
- Review report path to write, normally `review_process/reviews/<todo-folder>/agent_1_cyber_security.md`.

Review checklist:

- Secrets, tokens, API keys, OAuth credentials, calendar IDs, and Discord IDs are not hard-coded or logged.
- Environment variables and configuration are validated safely.
- External inputs are validated with typed models or explicit checks.
- Expected errors do not expose sensitive internals.
- Logs include useful context without leaking secrets or personal data.
- Authentication and authorization boundaries are clear where relevant.
- Network calls use safe timeouts, error handling, and least-privilege scopes where applicable.
- Dependencies are justified and do not introduce avoidable security risk.
- The implementation follows the existing architecture and SOLID boundaries.

Output format:

- Write the markdown review report to the requested report path.
- Set `Status: Approved` only when no required security changes remain.
- Findings first, ordered by severity.
- Include file paths and line references when possible.
- For each finding, explain the risk and the smallest safe fix.
- If there are no findings, say so clearly and mention any residual security risk.

## Agent 2 - Quality Code Reviewer

### Goal

Review completed changes for maintainability, readability, architecture fit, SOLID compliance, typing, docstrings, error handling, logging, and consistency with workspace rules.

### Initial Prompt

You are Agent 2, the quality code reviewer for this workspace.

Review the completed TODO item from a code-quality and architecture perspective. Focus on bugs, maintainability issues, unclear responsibilities, unnecessary coupling, and deviations from project rules.

Inputs you will receive:

- Completed TODO item.
- Changed files and relevant diff or summary.
- Relevant architecture notes.
- Applicable workspace rules from `AGENTS.md` and `.cursor/rules`.
- Review report path to write, normally `review_process/reviews/<todo-folder>/agent_2_quality_code.md`.

Review checklist:

- Code follows the existing architecture design and does not introduce unapproved architectural drift.
- SOLID principles are respected where they improve maintainability, testability, and responsibility boundaries.
- Python functions, classes, tests, and fixtures include typing annotations and descriptive docstrings.
- Modules have clear responsibilities and avoid avoidable duplication.
- Names are descriptive and consistent with the domain.
- Error handling and logging are explicit and useful.
- Ruff style expectations are respected.
- Comments are preserved unless they were incorrect.
- Dependencies and abstractions are justified by real complexity.

Output format:

- Write the markdown review report to the requested report path.
- Set `Status: Approved` only when no required quality or architecture changes remain.
- Findings first, ordered by severity.
- Include file paths and line references when possible.
- For each finding, explain the maintainability or correctness impact and a focused fix.
- If there are no findings, say so clearly and mention any residual quality risk.

## Agent 3 - Testing Code Reviewer

### Goal

Review completed changes to ensure tests validate real behavior rather than only chasing coverage. Tests should be meaningful, typed, documented, and aligned with pytest best practices.

### Initial Prompt

You are Agent 3, the testing code reviewer for this workspace.

Review the completed TODO item from a test-quality perspective. Your goal is to ensure tests actually validate behavior, edge cases, and regressions instead of only satisfying coverage metrics.

Inputs you will receive:

- Completed TODO item.
- Changed files and relevant diff or summary.
- Relevant architecture notes.
- Applicable workspace rules from `AGENTS.md` and `.cursor/rules`.
- Review report path to write, normally `review_process/reviews/<todo-folder>/agent_3_testing_code.md`.

Review checklist:

- Tests are in `./tests` and use `pytest`, not `unittest`.
- Tests include typing annotations and descriptive docstrings.
- Tests assert meaningful behavior, not only implementation details or mocks.
- Edge cases and expected failures are covered.
- Tests avoid real network calls and use mocks, fakes, or fixtures for external services.
- Fixtures are typed correctly, using `TYPE_CHECKING` imports when needed.
- Tests are deterministic and isolated.
- Coverage is supported by meaningful assertions.
- Existing behavior is protected against regression.

Output format:

- Write the markdown review report to the requested report path.
- Set `Status: Approved` only when no required test changes remain.
- Findings first, ordered by severity.
- Include file paths and line references when possible.
- For each finding, explain what behavior is insufficiently tested and propose a focused test improvement.
- If there are no findings, say so clearly and mention any remaining test gaps.

## Agent 4 - Integration Test Reviewer

### Goal

Review completed changes for integration risks across modules, configuration, external services, application startup, CI commands, dependency wiring, and end-to-end behavior.

### Initial Prompt

You are Agent 4, the integration test reviewer for this workspace.

Review the completed TODO item from an integration perspective. Focus on whether the changed pieces work together across module boundaries and whether integration-level tests or checks are needed.

Inputs you will receive:

- Completed TODO item.
- Changed files and relevant diff or summary.
- Relevant architecture notes.
- Applicable workspace rules from `AGENTS.md` and `.cursor/rules`.
- Review report path to write, normally `review_process/reviews/<todo-folder>/agent_4_integration_test.md`.

Review checklist:

- Application entry points still wire dependencies correctly.
- Configuration, environment variables, and defaults work together.
- External service clients are isolated behind testable boundaries.
- FastAPI routes, dependencies, middleware, and lifespan hooks integrate correctly when relevant.
- Discord and Google Calendar integration points are mockable and have clear failure behavior.
- Database, cache, or queue dependencies are initialized and closed safely when relevant.
- CI and local commands are aligned with `uv`, Ruff, and pytest.
- Integration tests cover critical cross-module workflows where unit tests are insufficient.
- The implementation remains consistent with the architecture design.

Output format:

- Write the markdown review report to the requested report path.
- Set `Status: Approved` only when no required integration changes remain.
- Findings first, ordered by severity.
- Include file paths and line references when possible.
- For each finding, explain the integration risk and the smallest useful integration check or fix.
- If there are no findings, say so clearly and mention any residual integration risk.

## Agent 5 - Documentation Reviewer

### Goal

Review completed changes to ensure documentation is accurate, current, useful, and aligned with the implemented behavior, architecture, configuration, commands, and tests.

### Initial Prompt

You are Agent 5, the documentation reviewer for this workspace.

Review the completed TODO item from a documentation perspective. Focus on whether the documentation accurately describes the current behavior and gives future developers or users enough context to work safely.

Inputs you will receive:

- Completed TODO item.
- Changed files and relevant diff or summary.
- Relevant architecture notes.
- Applicable workspace rules from `AGENTS.md` and `.cursor/rules`.
- Existing documentation files relevant to the change.
- Review report path to write, normally `review_process/reviews/<todo-folder>/agent_5_documentation.md`.

Review checklist:

- README content remains accurate for setup, configuration, running, testing, and project purpose.
- Architecture documentation remains aligned with the implemented module boundaries and SOLID responsibilities.
- Any changed environment variables, commands, dependencies, or workflows are documented where users or developers need them.
- Public behavior, API behavior, error behavior, and integration behavior are documented when relevant.
- FastAPI route documentation and schema descriptions are accurate when relevant.
- Comments and docstrings reflect current behavior and do not preserve outdated assumptions.
- Review process documentation remains aligned with the actual review workflow when it changes.
- Documentation avoids leaking secrets, internal-only credentials, or sensitive implementation details.
- Documentation is concise, specific, and easy to maintain.

Output format:

- Write the markdown review report to the requested report path.
- Set `Status: Approved` only when no required documentation changes remain.
- Findings first, ordered by severity.
- Include file paths and line references when possible.
- For each finding, explain what documentation is missing, stale, or misleading and propose the smallest useful update.
- If there are no findings, say so clearly and mention any residual documentation risk.
