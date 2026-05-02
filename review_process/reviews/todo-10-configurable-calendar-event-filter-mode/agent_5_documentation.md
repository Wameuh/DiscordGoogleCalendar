# Agent 5 - Documentation Reviewer

Status: Changes requested
Reviewed TODO: configurable-calendar-event-filter-mode
Review iteration: 1
Reviewed files:

- `.gitignore`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `docs/deployment.md`
- `src/discordcalendarbot/app.py`
- `src/discordcalendarbot/calendar/tag_filter.py`
- `src/discordcalendarbot/config.py`
- `src/discordcalendarbot/operator_commands.py`
- `src/discordcalendarbot/services/digest_service.py`
- `tests/test_config_domain_security.py`
- `tests/test_daily_digest_service_scheduler.py`
- `tests/test_discord_bot_publisher.py`
- `tests/test_operator_commands.py`
- `tests/test_project_foundation.py`

## Findings

- Severity: Low
  File: `ARCHITECTURE.md:291`
  Issue: The architecture "Files and directories to ignore" block is stale compared with the updated `.gitignore`. It still lists `token.json` but not `token.json.metadata.json`, and it omits the new local artifact protections for `.codex_tmp/`, `gitleaks-bin/`, `gitleaks-*-bin/`, `local-results.sarif`, and `*.zip`.
  Impact: Future agents and developers may treat the architecture document as the ignore-policy source of truth and miss sensitive OAuth metadata or local security-scan/download artifacts during pre-commit checks.
  Required change: Update the architecture ignore list to include the newly ignored sensitive/runtime artifact patterns, especially `token.json.metadata.json`, and keep it aligned with `.gitignore`.

- Severity: Low
  File: `README.md:103`
  Issue: The README security checklist says to keep `.env`, `credentials.json`, `token.json`, SQLite files, and local data directories out of git, but it does not mention OAuth token metadata, local archives, downloaded binaries, or cache/artifact folders covered by the new commit-safety rule.
  Impact: Operator-facing guidance is slightly weaker than the enforced workspace policy and may not steer humans away from staging the newly identified sensitive/runtime artifacts.
  Required change: Expand the README security note to include token metadata and local runtime artifacts, or point directly to `AGENTS.md` commit-safety rules for commit-time checks.

- Severity: Low
  File: `docs/deployment.md:157`
  Issue: Deployment secret guidance has the same stale artifact list as the README and does not mention `token.json.metadata.json`, local archives, downloaded binaries, cache folders, or private calendar/Discord data artifacts.
  Impact: Deployment operators may protect the primary token and credential files while overlooking adjacent metadata or temporary artifacts created during scans, downloads, or local troubleshooting.
  Required change: Update the deployment "Permissions And Secrets" bullet so it matches the new Commit Safety and `.gitignore` policy.

## Approval Notes

The `EVENT_FILTER_MODE` behavior itself is documented accurately across README, deployment, and architecture docs: `tagged` remains the default, `all` allows missing `EVENT_TAG`, and the privacy risk of posting all calendar events to Discord is clearly called out. The `AGENTS.md` Commit Safety section is present and aligned with the requested workflow. Approval is blocked only on keeping the public safety documentation synchronized with the expanded ignore/commit-safety policy.
