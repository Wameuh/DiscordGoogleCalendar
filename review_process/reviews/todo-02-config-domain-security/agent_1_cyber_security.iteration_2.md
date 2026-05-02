# Agent 1 - Cyber Security Reviewer

Status: Changes requested
Reviewed TODO: TODO 2 - Configuration, Domain, And Security Primitives
Review iteration: 2
Reviewed files:

- `ARCHITECTURE.md`
- `CyberSecurityAnalysis.md`
- `README.md`
- `.cursor/rules/python-best-practices.mdc`
- `.cursor/rules/python-fastapi.mdc`
- `review_process/review_agents.md`
- `src/discordcalendarbot/config.py`
- `src/discordcalendarbot/domain/digest.py`
- `src/discordcalendarbot/domain/events.py`
- `src/discordcalendarbot/security/filesystem_permissions.py`
- `src/discordcalendarbot/security/log_sanitizer.py`
- `tests/test_config_domain_security.py`
- `tests/test_project_foundation.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/security/log_sanitizer.py:11`
  Issue: The follow-up redaction now covers `refresh_token`, `access_token`, and `id_token`, but it still does not redact the generic OAuth `token` key used by Google OAuth credential files.
  Impact: If token-file contents or structured exception text are sanitized after a Google credential load or refresh failure, an access token stored under a plain `token` field can remain visible in logs or stored errors. That leaves a realistic credential-leak path even though the more specific token keys are now protected.
  Required change: Add a case-insensitive key-based redaction pattern for `token`, preserving only the key/prefix, and add a focused test that proves `token=...` or JSON-like `"token": "..."` values are removed from sanitized output.

## Approval Notes

The previous Windows ACL finding is resolved: broad-principal matching now casefolds configured principals and ACE principals, and `tests/test_config_domain_security.py:173` covers a lowercase `users` principal.

The previous Unix permission-mode finding is resolved: `check_unix_secret_mode` masks mode values with `0o777` before calculating unsafe bits, and `tests/test_config_domain_security.py:159` covers a realistic stat-style mode with file-type bits.

The sanitizer also now redacts `refresh_token`, `access_token`, and `id_token`, with regression coverage in `tests/test_config_domain_security.py:202`. However, the generic `token` field remains a required security fix before Agent 1 can approve this TODO.

Verification run during this review:

- `uv run ruff check .` - passed
- `uv run ruff format --check .` - passed
- `uv run pytest` - passed, 20 tests
