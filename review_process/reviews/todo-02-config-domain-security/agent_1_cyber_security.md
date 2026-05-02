# Agent 1 - Cyber Security Reviewer

Status: Changes requested
Reviewed TODO: TODO 2 - Configuration, Domain, And Security Primitives
Review iteration: 1
Reviewed files:

- `ARCHITECTURE.md`
- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `review_process/review_agents.md`
- `.gitignore`
- `src/discordcalendarbot/config.py`
- `src/discordcalendarbot/domain/digest.py`
- `src/discordcalendarbot/domain/events.py`
- `src/discordcalendarbot/security/filesystem_permissions.py`
- `src/discordcalendarbot/security/log_sanitizer.py`
- `tests/test_config_domain_security.py`
- `tests/test_project_foundation.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/security/log_sanitizer.py:8`
  Issue: Log redaction covers Discord-style tokens, bearer tokens, and `client_secret`, but it does not redact common OAuth credential keys such as `refresh_token`, `access_token`, `token`, or private key material when those values appear as structured exception text or JSON-like output.
  Impact: Google OAuth token loading, refresh, or credential parsing failures can include token-file fields in exception messages or debug output. Without key-based redaction for these fields, a refresh token or access token could be persisted to logs or stored errors, violating the architecture requirement to keep OAuth tokens and secrets out of logs.
  Required change: Add case-insensitive key-based redaction patterns for OAuth/token fields such as `refresh_token`, `access_token`, `token`, and `private_key`, preserving only the key/prefix. Add focused tests that prove those fields are removed from sanitized output.

- Severity: Medium
  File: `src/discordcalendarbot/security/filesystem_permissions.py:64`
  Issue: Windows broad-principal detection compares `ace.principal` with `BROAD_WINDOWS_PRINCIPALS` using exact case-sensitive strings.
  Impact: Windows principal names are not security-sensitive by case. An adapter that returns `BUILTIN\\USERS`, `authenticated users`, or another casing variant would bypass this check and fail to flag broadly readable token or credential files.
  Required change: Normalize principals with `casefold()` or another explicit Windows-name normalization before comparison, and add a test using a casing variant of a broad principal.

- Severity: Low
  File: `src/discordcalendarbot/security/filesystem_permissions.py:41`
  Issue: `check_unix_secret_mode` compares the full `mode` integer against permission bits. If callers pass `Path.stat().st_mode`, the file-type bits are included and a safe `0600` file can be incorrectly reported as broader than expected.
  Impact: The future startup permission adapter may fail closed on correctly protected Unix secret files, making deployments brittle and potentially encouraging callers to strip mode bits inconsistently outside the security primitive.
  Required change: Mask the provided mode with `0o777` before calculating unsafe bits and reporting the displayed mode. Add a test that passes a realistic `stat`-style mode such as `0o100600`.

## Approval Notes

The typed settings layer rejects missing required values, invalid timezones, invalid time values, oversized Discord message limits, unsupported tag fields, and role mention enablement without a role ID. Configured secret and state paths are resolved before validation, git ignore checks are used for paths inside the project tree, symlink-aware containment is present through `Path.resolve()`, and the domain date-window primitives do not introduce direct security exposure.

Residual risk remains in the redaction and permission primitives listed above. The review used the provided statement that `uv run ruff check .`, `uv run ruff format --check .`, and `uv run pytest` pass; those checks do not remove the required security fixes.
