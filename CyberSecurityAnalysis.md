# Cyber Security Analysis

## Scope

This document is a fresh architecture-level security review of `ARCHITECTURE.md` for the Discord Calendar Bot. It reviews the updated architecture as designed, plus the current repository state where it affects security assumptions.

This is not a source-code audit or penetration test. The application is still mostly at architecture/planning stage, so many findings are implementation risks: they are security requirements that must be proven in code, tests, CI, and deployment documentation.

## System Summary

The planned system is a long-running `discord.py` bot with an internal `APScheduler` daily job. It reads one or more private Google Calendars through OAuth, filters events by a configured marker, formats a Discord-safe digest, and posts it to one configured guild and channel.

There is no public inbound HTTP server in v1. The bot needs outbound access to Discord and Google Calendar.

## Protected Assets

- Discord bot token.
- Google OAuth client credentials and refresh token.
- Private calendar event data: summaries, descriptions, locations, links, times, recurrence details, and possible meeting URLs.
- Discord guild, channel, role, and message metadata.
- SQLite digest run state and partial delivery state.
- Logs, dry-run output, and CLI terminal output.
- The host account and filesystem running the long-lived process.
- Future command authorization data if slash commands or event creation are added.

## Positive Security Controls In The Updated Architecture

- No inbound web server or webhook endpoint for v1.
- Read-only Google Calendar OAuth scope for the daily digest.
- Minimal Discord permissions: `View Channel` and `Send Messages`.
- Minimal/default Discord gateway intents and no privileged message content intent.
- Explicit guild and channel validation before scheduler startup.
- Mentions disabled by default with `discord.AllowedMentions.none()`.
- Optional role mention is constrained to one configured role ID.
- Event content is explicitly treated as untrusted input.
- Markdown neutralization, URL policy, truncation, and omission of descriptions by default are now included.
- Configuration is environment-backed and typed.
- Paths are resolved and validated before use.
- Secret files and state files are ignored in `.gitignore`.
- Startup includes secret file permission checks.
- Logging sanitization is included in the runtime lifecycle.
- SQLite stores hashes for calendar IDs and event tags rather than raw values in run keys.
- Partial delivery reconciliation is planned.
- `--force` requires `--confirm-force`.
- Dependency lockfile review, secret scanning, and vulnerability scanning are called out.
- Windows and Linux deployment hardening are both acknowledged.

## Current Repository Check

The current `.gitignore` now includes the documented sensitive patterns:

```text
.env
.env.*
credentials.json
token.json
*.sqlite3
*.sqlite3-*
data/
.state/
```

This resolves the previous critical mismatch between the architecture and repository ignore rules. The remaining security work is mostly implementation and operational proof.

## Critical Issues

### 1. Secret Permission Validation Is Architecture-Required But Hard To Implement Correctly Cross-Platform

**Evidence:** The architecture requires file permission checks for `.env`, Google credentials, OAuth token files, SQLite state, and parent directories on both Windows and Linux.

**Risk:** If these checks are incomplete or warning-only, local users or compromised processes may read Google refresh tokens, Discord bot tokens, SQLite state, or logs. Windows ACL inspection is especially easy to under-specify.

**Recommendation:**

- Implement a dedicated `security/filesystem_permissions.py` module with platform-specific behavior.
- On Linux and macOS, fail closed for group/world-readable secret files unless an explicit development override is set.
- On Windows, inspect ACLs and flag broad principals such as `Everyone`, `Users`, `Authenticated Users`, and domain-wide groups.
- Include parent directory checks, not just file checks.
- Document the exact accepted Windows ACL shape.
- Add tests for Linux mode parsing and Windows ACL parsing behind testable adapters.

### 2. Calendar Event Content Remains The Main Data Injection Boundary

**Evidence:** Google Calendar fields can be created by humans or external calendar integrations, then rendered into Discord.

**Risk:** Event content can cause mention abuse, markdown spoofing, phishing links, misleading hostnames, private meeting URL exposure, oversized output, bidi/control character confusion, or social engineering through a trusted bot identity.

**Recommendation:**

- Build a single formatter/sanitizer boundary used by every Discord message path.
- Neutralize Discord mentions independently from `AllowedMentions`.
- Escape or normalize Discord markdown, code blocks, masked links, custom emoji syntax, channel mentions, role mentions, and user mentions.
- Strip or replace Unicode control characters and bidirectional override characters.
- Truncate every untrusted field before joining the final message.
- Prefer omitting descriptions and conference links for v1.
- Add golden tests with malicious calendar payload fixtures.

### 3. Secrets Can Still Leak Through Operational Output

**Evidence:** The architecture says logs are sanitized, dry-run prints real digest content to stdout, and OAuth bootstrap prints account information.

**Risk:** Terminal scrollback, service logs, crash dumps, CI logs, or copied dry-run output may expose private calendar content, email addresses, channel IDs, token paths, or exception details.

**Recommendation:**

- Treat dry-run output as sensitive by default in documentation.
- Make `dry-run --redact` or `--summary-only` prominent.
- Never log rendered digest bodies at normal log levels.
- Sanitize SDK exceptions before persistence and logging.
- Add redaction for token-like strings, OAuth client secrets, Discord token patterns, bearer tokens, URLs with query strings, and local secret paths.
- Cap stored and logged exception text.

### 4. Host Compromise Gives Broad Access To Calendar And Discord Assets

**Evidence:** The design uses a long-running process with local OAuth refresh tokens, Discord bot token, SQLite state, and logs on disk.

**Risk:** Any compromise of the host account can expose tokens and private calendar data. A long-lived bot also keeps a valid Discord connection and refresh-capable Google credentials available.

**Recommendation:**

- Run as a dedicated non-admin/non-root service account.
- Store secrets outside the source tree in directories owned only by the service account.
- Use OS-level secret stores where practical for production deployments.
- Add token rotation and incident response instructions.
- Keep the process supervisor restart policy bounded to avoid restart storms.
- Avoid running local OAuth bootstrap on the production host unless it is trusted and controlled.

## High Issues

### 5. Authorization Model For Future Slash Commands Is Not Yet Designed

**Evidence:** Slash commands are excluded from v1 but are a stated future extension. Event creation from Discord is also mentioned.

**Risk:** Future commands will introduce inbound user-controlled input, authorization decisions, abuse prevention, audit requirements, and possibly Google write scopes.

**Recommendation:**

- Add a future-facing authorization section before implementing any slash command.
- Define allowed Discord roles/users per command.
- Add rate limits and audit logs for manual send, status, role mention changes, and event creation.
- Keep write-capable Google scopes in a separate adapter/configuration path.
- Consider separate credentials for read-only digest and future write actions.

### 6. Force Repost And Reconciliation Commands Are Powerful Local Operations

**Evidence:** `send-digest --force --confirm-force` and `reconcile-digest` can override normal delivery state.

**Risk:** A local operator mistake or local account compromise can duplicate digests, hide missed deliveries, or mark unposted content as delivered.

**Recommendation:**

- Require explicit target date, channel, and confirmation text for destructive state changes.
- Log sanitized operator action records.
- Make reconciliation append-only where possible rather than overwriting existing state.
- Store `forced_by`, `forced_at`, and reason fields if operator identity is available.
- Add dry-run preview before force posting.

### 7. SQLite Integrity And Concurrency Need Careful Implementation

**Evidence:** SQLite is the idempotency ledger and partial delivery record. It decides whether a digest should post, skip, retry, or reconcile.

**Risk:** Incorrect transaction boundaries, stale lock handling, clock skew, or SQLite write failures can cause duplicate posts, missed posts, or unrecoverable partial state.

**Recommendation:**

- Use atomic insert/update transactions for claim operations.
- Enable WAL mode if appropriate for the deployment.
- Ensure `lock_expires_at` uses a controlled `Clock` and timezone-aware timestamps.
- Store partial Discord message IDs immediately after each accepted send.
- Treat database write failure after Discord acceptance as high-severity.
- Add property-style tests or concurrency tests for duplicate claim attempts.

### 8. Dependency Supply Chain Controls Are Planned But Not Yet Enforced

**Evidence:** The architecture calls for `uv.lock`, update tooling, vulnerability scanning, and secret scanning, but `pyproject.toml` currently has no runtime dependencies and no CI is shown.

**Risk:** When dependencies are added, vulnerable or compromised packages could access tokens, event data, or host files.

**Recommendation:**

- Commit `uv.lock` as soon as dependencies are added.
- Add CI that runs Ruff, pytest, secret scanning, and dependency vulnerability scanning.
- Review transitive dependency changes in PRs.
- Pin major versions intentionally.
- Avoid dynamic imports from user-controlled directories.

### 9. Google OAuth Bootstrap Can Bind The Wrong Identity Or Scope

**Evidence:** `google-auth-login` is an interactive local command and writes the refresh token.

**Risk:** A user may authorize the wrong Google account, grant unexpected scopes, overwrite a valid production token, or run the flow on an untrusted machine.

**Recommendation:**

- Display authenticated email, granted scopes, token output path, and calendar list preview.
- Require confirmation before writing the token.
- Refuse to overwrite existing tokens without `--force`.
- Validate that granted scopes exactly match enabled features.
- Record token creation time and account email in a local metadata file without storing secrets.

### 10. URL Policy Needs Precise Defaults

**Evidence:** The architecture says links are optional, `https` only by default, hostnames should be displayed, and private meeting URLs should be omitted unless enabled.

**Risk:** Ambiguous URL handling may still leak Google Meet/Zoom/Teams links or allow phishing through misleading calendar text.

**Recommendation:**

- Define exact allowed fields and default behavior:
  - Event description links: omitted.
  - Google event HTML links: omitted.
  - Conference links: omitted by default.
  - Location URLs: shown only if `https` and not recognized as private meeting links.
- Reject masked markdown links.
- Display plain URL plus hostname or only hostname depending on privacy needs.
- Strip query strings by default unless explicitly required.

## Medium Issues

### 11. Data Retention Is Mentioned But Not Specified

**Evidence:** SQLite retention is required, but no retention period or cleanup behavior is defined.

**Risk:** Run metadata, errors, and message IDs accumulate indefinitely and increase exposure after host compromise.

**Recommendation:**

- Define retention for successful, skipped, failed, and partial runs.
- Keep partial and failed runs longer than successful runs if needed for operations.
- Add a cleanup command or scheduled maintenance task.
- Ensure cleanup does not delete unresolved partial deliveries.

### 12. Configuration Path Validation Can Create Usability/Security Tension

**Evidence:** The architecture rejects secret paths inside the git working tree unless ignored.

**Risk:** Implementing this poorly may either block safe development workflows or allow unsafe paths through symlink, relative path, or case-sensitivity edge cases.

**Recommendation:**

- Resolve symlinks before validation.
- Compare normalized absolute paths.
- Treat Windows paths case-insensitively.
- Check ignore status using git where available rather than reimplementing `.gitignore` parsing.
- Fail closed for production mode and warn in development mode only if explicitly configured.

### 13. Discord Role Validation Needs A Definition Of Privileged Roles

**Evidence:** The architecture says to reject managed and privileged roles for automatic mention behavior.

**Risk:** "Privileged role" is ambiguous. Implementers may only reject admin roles and miss broad notification roles or sensitive operational roles.

**Recommendation:**

- Define privileged role checks explicitly:
  - Reject `@everyone`.
  - Reject managed/integration roles.
  - Reject roles with `administrator`, `manage_guild`, `manage_roles`, `manage_channels`, or similar elevated permissions.
  - Optionally require an allowlist of role IDs.
- Log the configured role name and member count during startup validation.

### 14. Rate Limit And Retry Policy Needs Implementation Bounds

**Evidence:** The architecture requires bounded exponential backoff with jitter and respecting Discord `Retry-After`.

**Risk:** Unbounded retries can extend past lock TTL, cause duplicate ownership decisions, or amplify provider incidents.

**Recommendation:**

- Define max attempts per provider.
- Define max total elapsed retry time.
- Make lock TTL greater than worst-case retry duration plus cleanup margin.
- Persist retry attempt counts.
- Avoid retrying after any accepted Discord message unless resuming a known partial delivery.

### 15. Timezone And Clock Behavior Can Affect Security-Relevant Idempotency

**Evidence:** The target date and idempotency key depend on timezone and current time.

**Risk:** Host clock drift, DST, or timezone misconfiguration can post for the wrong day, skip a digest, or create unexpected run keys.

**Recommendation:**

- Use `zoneinfo` exclusively for local date calculations.
- Log current UTC time, configured timezone, computed local time, target date, and next scheduled run at startup.
- Test DST transition days for `Europe/Kiev` and other configured zones.
- Document that production hosts should use NTP/time sync.

### 16. Calendar Data Minimization Needs Product Decisions

**Evidence:** The digest may include all-day events, timed events, optional location/link, and future description support.

**Risk:** Posting more fields than necessary increases privacy exposure in Discord.

**Recommendation:**

- For v1, include only title and time unless explicitly enabled.
- Make location, link, and description opt-in separately.
- Document privacy implications of each display field.
- Remove the event tag from titles before output.

### 17. Local CLI Commands Are Not Authenticated Beyond Host Access

**Evidence:** Operator commands are local CLI commands.

**Risk:** Any user with access to the service account shell or project environment can run recovery, dry-run, OAuth, send, or reconcile commands.

**Recommendation:**

- Restrict service account shell access.
- Keep `.env` and token files unreadable to other users.
- Consider a command-level safety check that refuses powerful commands unless running as the expected service account.
- Record operator actions where possible.

## Low Issues

### 18. No Explicit Secret Rotation Schedule

**Risk:** Long-lived Discord and Google tokens may remain valid indefinitely after accidental exposure.

**Recommendation:** Document how and when to rotate the Discord bot token, revoke Google OAuth tokens, and regenerate local token files.

### 19. No Backup Encryption Requirement

**Risk:** Backups of token files, SQLite state, and logs may expose the same sensitive data as the live host.

**Recommendation:** Require encrypted backups or exclude tokens from general backups and recreate them through OAuth bootstrap.

### 20. No Explicit Privacy Notice For Discord Channel Members

**Risk:** Users may not realize calendar data is being copied into Discord, where retention, search, bots, and channel membership differ from Google Calendar.

**Recommendation:** Document which calendar fields are posted and ensure the target channel audience is appropriate.

### 21. Google Calendar Sharing Model Is Out Of Scope But Important

**Risk:** If many users or external integrations can edit tagged calendar events, they can indirectly influence bot output.

**Recommendation:** Restrict who can edit source calendars or use a dedicated digest calendar/tag controlled by trusted editors.

## Security Requirements To Preserve During Implementation

- The bot must never require Google write scopes for the v1 daily digest.
- The bot must never enable Discord privileged message content intent for v1.
- The bot must not parse mentions from calendar text.
- The formatter must treat all calendar fields as untrusted.
- The application must not log tokens, OAuth payloads, raw rendered digest content, or raw SDK exception payloads.
- SQLite must not store event summaries, descriptions, locations, attendees, or raw calendar IDs for v1.
- Force reposts must require both `--force` and `--confirm-force`.
- Partial delivery must not trigger a full automatic repost.
- Secret/state paths must be resolved and checked before use.
- Secret files must be ignored by git and protected by filesystem permissions.

## Recommended Security Backlog

1. Implement cross-platform secret and state file permission checks.
2. Implement the Discord content sanitizer and URL policy before any posting feature.
3. Add centralized log and exception sanitization.
4. Add SQLite atomic claim, partial delivery, sanitization, and retention behavior.
5. Add force/reconcile operator audit fields and confirmation flows.
6. Add OAuth bootstrap scope and account verification.
7. Add CI secret scanning and dependency vulnerability scanning.
8. Commit `uv.lock` once dependencies are added.
9. Add deployment documentation for Windows and Linux service accounts.
10. Add future slash-command authorization design before implementing commands.

## Security Test Cases

- `.gitignore` contains all documented secret and state patterns.
- Settings reject invalid timezones, invalid time formats, unsafe path values, and role mention misconfiguration.
- Secret file permission checks detect unsafe Unix modes.
- Windows ACL inspection detects broad read principals through a test adapter.
- Path validation resolves symlinks and rejects unsafe in-repo secret paths unless ignored.
- Google OAuth credentials are limited to expected scopes.
- OAuth bootstrap refuses to overwrite token files without force.
- Dry-run avoids normal application logs and supports redaction.
- Formatter neutralizes `@everyone`, user mentions, role mentions, channel mentions, custom emoji syntax, markdown links, code blocks, and bidi/control characters.
- Formatter truncates every untrusted event field.
- URL policy omits private meeting links and rejects non-HTTPS links.
- Publisher uses `AllowedMentions.none()` by default.
- Publisher allows only the configured role when enabled.
- Role validation rejects `@everyone`, managed roles, and elevated-permission roles.
- SQLite claim is atomic under concurrent scheduled/manual execution.
- SQLite caps and sanitizes `last_error`.
- Partial delivery never causes automatic full repost.
- Reconciliation command never fetches Google Calendar data.
- Retry logic respects Discord `Retry-After` and total lock TTL bounds.
- Scheduler catch-up cannot post twice across reconnects or restarts.

## Overall Assessment

The updated architecture is materially stronger than the first version. It now captures the main security themes: secret hygiene, path validation, least privilege, untrusted calendar content, mention safety, sanitized logging, dependency scanning, deployment hardening, and operational recovery.

The highest remaining risk is implementation drift. The design is now security-aware, but the project must prove those requirements with focused modules, tests, CI checks, and deployment documentation. The most important areas to implement carefully are cross-platform permission validation, Discord content sanitization, URL filtering, log redaction, SQLite idempotency, and guarded operator commands.
