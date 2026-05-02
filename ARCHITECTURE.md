# Discord Calendar Bot Architecture

## Decision

This project uses a long-running `discord.py` bot with an internal daily scheduler.

The immediate product goal is simple: on one configured Discord server and one configured Discord channel, send one message every day at 7:00 AM listing the Google Calendar events for that day that contain a configured tag.

Architecture 2, a scheduled CLI job, would be simpler for only that goal. This project intentionally keeps Architecture 1 because it is a better foundation for future Discord-native behavior, such as slash commands, adding Google Calendar events from Discord, manual digest triggers, status checks, role mention controls, or reminder commands.

The design still keeps the core business logic independent from Discord so the calendar, filtering, formatting, storage, and digest services remain testable and reusable.

## Source Context

This architecture follows:

- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `ressources/discord_bot_research.md`
- `ressources/google_calendar_research.md`
- `CyberSecurityAnalysis.md`

No FastAPI component is required for the first version. The bot only needs outbound access to Discord and Google Calendar.

## Product Scope

Version 1 must:

- Connect to Discord as a bot.
- Target one configured Discord guild and one configured channel.
- Read one or more configured Google calendars.
- Select events that contain a configured tag.
- Send a daily digest at 7:00 AM in a configured timezone.
- Avoid duplicate daily posts under normal failure and restart conditions.
- Support a dry run and manual digest trigger for local recovery.

Version 1 does not need:

- FastAPI or an inbound web server.
- Google Calendar push notifications.
- Multi-guild configuration.
- Slash commands, although the architecture should make them easy to add later.
- A database server.

## Supported Platforms

The bot must run on both Windows and Linux.

Cross-platform requirements:

- Use Python and `uv` commands that work on both platforms.
- Avoid hard-coded path separators; use `pathlib.Path`.
- Resolve and validate configured paths before use.
- Keep secrets, token files, SQLite state, and logs outside shared or world-readable directories.
- Use `zoneinfo` timezone names such as `Europe/Kiev`; do not rely on the host machine timezone.
- Keep the scheduler timezone explicit with `BOT_TIMEZONE`.
- Support platform-appropriate process supervision:
  - Windows: a dedicated user account plus a service wrapper, scheduled startup task, or another supervisor that restarts the long-running process.
  - Linux: a dedicated user account plus systemd, Docker, or another supervisor with restart limits.

The application behavior must be the same on both platforms. Platform-specific differences should be isolated to deployment documentation and filesystem permission checks.

## Package Layout

Application code should live under `src/discordcalendarbot`.

```text
src/discordcalendarbot/
  __init__.py
  __main__.py
  app.py
  cli.py
  config.py
  logging_config.py
  domain/
    __init__.py
    events.py
    digest.py
  calendar/
    __init__.py
    auth.py
    client.py
    mapper.py
    tag_filter.py
  discord/
    __init__.py
    bot.py
    cli_publisher.py
    publisher.py
    formatter.py
    sanitizer.py
    url_policy.py
  scheduler/
    __init__.py
    daily_digest.py
  security/
    __init__.py
    filesystem_permissions.py
    log_sanitizer.py
  storage/
    __init__.py
    repository.py
    sqlite.py
  services/
    __init__.py
    digest_service.py
  operator_commands.py
```

Tests should live under `tests`.

## Module Responsibilities

`__main__.py`
: Starts the application with `uv run python -m discordcalendarbot`.

`app.py`
: Composition root. It builds settings, logging, Google clients, Discord clients, storage, scheduler, and services.

`cli.py`
: Thin argparse entrypoint for local operator commands.

`operator_commands.py`
: Local operator command implementations, including OAuth bootstrap, dry run, manual digest sending, forced-send confirmation, and reconciliation.

`config.py`
: Typed environment-backed settings. It validates secrets, Discord IDs, calendar IDs, timezone, daily post time, tag behavior, and storage path.

`logging_config.py`
: Central logging setup. Logs should include run date, guild ID, channel ID, calendar count, event count, digest status, and error class. Logs must not include secrets or OAuth tokens.

`domain/events.py`
: Pure domain models such as `CalendarEvent`, `EventTime`, and normalized calendar metadata.

`domain/digest.py`
: Pure digest rules. TODO 2 implements local-day windows, overlap checks, and digest data structures; sorting and empty-day behavior are completed with tag filtering and formatting in TODO 4.

`calendar/auth.py`
: Google OAuth credential loading, refresh, and first-time login support.

`calendar/client.py`
: Google Calendar API adapter. It fetches raw event payloads from configured calendars.

`calendar/mapper.py`
: Converts Google event payloads into domain `CalendarEvent` objects.

`calendar/tag_filter.py`
: Encapsulates tag matching and displayed-title cleanup.

`discord/bot.py`
: Owns the `discord.py` bot lifecycle, minimal intents, readiness handling, channel validation, and scheduler startup guard.

`discord/cli_publisher.py`
: Temporary gateway-ready Discord publisher used by local `send-digest` commands.

`discord/publisher.py`
: Sends messages to the configured Discord channel and applies safe mention behavior.

`discord/formatter.py`
: Converts a daily digest into one or more Discord message payloads.

`discord/sanitizer.py`
: Single boundary for neutralizing untrusted calendar text before it is rendered into Discord messages.

`discord/url_policy.py`
: Owns URL extraction, filtering, privacy decisions, and display rules for event links.

`scheduler/daily_digest.py`
: Owns the internal 7:00 AM schedule using `APScheduler` and the bot event loop.

`security/filesystem_permissions.py`
: Cross-platform checks for secret files, state files, and parent directories.

`security/log_sanitizer.py`
: Central redaction for exceptions, structured log fields, stored errors, token-like strings, URLs with query strings, and local secret paths.

`storage/repository.py`
: Defines repository protocols for digest run state.

`storage/sqlite.py`
: SQLite implementation for idempotency, run locking, attempts, and delivery metadata.

`services/digest_service.py`
: Main use case. It coordinates idempotency checks, calendar reads, filtering, formatting, publishing, and persistence.

## Core Interfaces

Business logic should depend on small protocols rather than concrete SDK clients.

Expected boundaries:

- `CalendarEventSource`: list events for a local date window.
- `TagFilter`: decide whether a normalized event belongs in the digest.
- `DigestFormatter`: render digest data into Discord-safe message parts.
- `DiscordContentSanitizer`: sanitize every untrusted event field before formatting.
- `UrlPolicy`: decide whether an event URL may be shown and how it is displayed.
- `DiscordPublisher`: publish message parts to the configured channel.
- `DigestRunRepository`: claim, inspect, mark success, mark failure, and record partial delivery.
- `LogSanitizer`: redact unsafe strings before logging or storing errors.
- `FilesystemPermissionChecker`: validate secret and state file permissions.
- `Clock`: provide current time for scheduler, catch-up, and tests.

These boundaries keep tests fast and avoid network calls in unit tests.

## Runtime Lifecycle

1. The process starts through `discordcalendarbot.__main__`.
2. Settings are loaded from environment variables.
3. Configured paths are resolved, normalized, and checked for unsafe locations.
4. Secret file permissions are checked with platform-specific rules.
5. Logging is configured with sanitization.
6. SQLite schema is initialized if needed.
7. Google OAuth credentials are loaded and refreshed if possible.
8. The Discord bot is created with minimal intents.
9. The bot connects to Discord.
10. On readiness, the bot validates the configured guild and channel.
11. The scheduler starts exactly once, even if Discord reconnects and `on_ready` fires again.
12. The scheduler registers the daily digest job for 7:00 AM in `BOT_TIMEZONE`.
13. A startup catch-up check runs if the bot starts after 7:00 AM but before the configured cutoff.
14. Daily digest execution uses `DailyDigestService`.
15. Shutdown closes scheduler, Discord connection, and SQLite resources cleanly.

## Daily Digest Flow

1. Determine the target local date in `BOT_TIMEZONE`.
2. Build the digest idempotency key from:
   - digest date
   - timezone
   - guild ID
   - channel ID
   - configured calendar IDs
   - event tag
3. Check for an existing successful digest before making Google API calls.
4. If a successful digest exists, exit without posting.
5. Claim the digest run in SQLite so overlapping manual and scheduled executions cannot both post.
6. Compute the local day window: `[local midnight, next local midnight)`.
7. Fetch Google Calendar events for each configured calendar.
8. Normalize raw Google payloads into domain events.
9. Post-filter events by local-day overlap.
10. Remove cancelled events.
11. Apply tag filtering.
12. Sort and group events.
13. Format one or more Discord message parts.
14. If there are no tagged events and empty digest posting is disabled, mark the run as skipped.
15. Post message parts to Discord.
16. Store Discord message IDs and mark the run as posted.
17. If an error occurs, store sanitized failure context and retry classification.

## Configuration

All deployment-specific values must come from environment variables. A local `.env` file may be supported for development and must be ignored by git.

Required:

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_CHANNEL_ID=
GOOGLE_CREDENTIALS_PATH=
GOOGLE_TOKEN_PATH=
GOOGLE_CALENDAR_IDS=primary
EVENT_TAG=#discord-daily
BOT_TIMEZONE=Europe/Kiev
DAILY_DIGEST_TIME=07:00
SQLITE_PATH=./data/discordcalendarbot.sqlite3
```

Optional:

```text
EVENT_TAG_FIELDS=summary,description
POST_EMPTY_DIGEST=false
EMPTY_DIGEST_TEXT=No tagged events today.
ENABLE_ROLE_MENTION=false
DISCORD_ROLE_MENTION_ID=
CATCH_UP_CUTOFF_TIME=10:00
GOOGLE_REQUEST_TIMEOUT_SECONDS=20
DISCORD_PUBLISH_TIMEOUT_SECONDS=20
MAX_DISCORD_MESSAGE_CHARS=1900
SCHEDULER_MISFIRE_GRACE_SECONDS=900
RUN_LOCK_TTL_SECONDS=900
LOG_LEVEL=INFO
```

Files and directories to ignore:

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

Configuration validation must also enforce security constraints:

- Reject invalid timezone names and invalid time formats.
- Reject `MAX_DISCORD_MESSAGE_CHARS` above Discord's hard limit.
- Validate timeout, retry, and lock TTL ranges.
- Fail if role mentions are enabled without a valid configured role ID.
- Resolve configured paths before opening files.
- Reject secret paths inside the git working tree unless those paths are ignored.
- Resolve symlinks before path validation.
- Compare normalized absolute paths.
- Treat Windows path comparisons as case-insensitive.
- Prefer asking git whether a path is ignored when git is available instead of reimplementing `.gitignore` parsing.
- Keep raw calendar IDs and event tags out of logs. Hash them when they are only needed for idempotency keys.

## Security Architecture

The bot handles sensitive assets:

- Discord bot token.
- Google OAuth client credentials and refresh token.
- Private calendar event content.
- Discord guild, channel, role, and message metadata.
- SQLite digest state.
- Logs and dry-run output.
- The host account running the long-lived process.

Security principles:

- Use least privilege for Google OAuth, Discord permissions, host accounts, and filesystem access.
- Treat all Google Calendar event fields as untrusted input.
- Keep secrets out of git, logs, exceptions, and normal command output.
- Prefer fail-closed behavior for unsafe credentials, permissions, paths, and configuration.
- Keep read-only Google scope for v1. Add write scopes only when event creation is implemented.
- Make force reposts and OAuth bootstrap explicit, auditable operator actions.

### Secret And File Permission Controls

At startup, validate sensitive paths:

- `GOOGLE_TOKEN_PATH`
- `GOOGLE_CREDENTIALS_PATH`
- `.env`, when used
- `SQLITE_PATH`
- parent directories for token and state files

Unix-like hosts:

- Secret files should be mode `0600`.
- Secret directories should be mode `0700`.
- If a secret file is group-readable or world-readable, fail closed or emit a high-severity startup error according to the configured policy.

Windows hosts:

- Secret files should be readable only by the service account, the current user, and required administrators.
- Inspect ACLs and flag broad principals such as `Everyone`, `Users`, `Authenticated Users`, and broad domain groups.
- The accepted ACL shape should be documented for the chosen deployment model.

The first implementation may start with warnings on Windows if ACL inspection is not yet implemented, but the architecture target is platform-aware permission validation.

Permission validation should be implemented behind adapters so tests can exercise Unix mode parsing and Windows ACL parsing without depending on the host OS.

### Deployment Hardening

Run the bot as a dedicated least-privilege user or service account:

- Do not run as administrator or root.
- Disable interactive login for the service account where practical.
- Keep project files, OAuth token files, SQLite state, and logs in directories owned by that account.
- Use a process supervisor with restart limits.
- Keep backup and restore procedures for token files and SQLite state.
- Rotate the Discord bot token and revoke Google tokens if credentials are exposed.
- Prefer OS-level secret stores for production deployments where practical.
- Keep restart policies bounded to avoid restart storms during invalid-token or invalid-config failures.
- Avoid running OAuth bootstrap on the production host unless that host is trusted and controlled.

On Linux, systemd or Docker are suitable. On Windows, use a service wrapper, a scheduled startup task, or another supervisor that can run the long-lived process and restart it safely.

Backups that include token files, SQLite state, or logs must be encrypted. If backups cannot be protected appropriately, exclude OAuth tokens and recreate them through OAuth bootstrap during restore.

### Dependency And CI Security

When dependencies are added:

- Commit and review `uv.lock`.
- Pin major versions intentionally.
- Use Dependabot, Renovate, or a similar update workflow.
- Add dependency vulnerability scanning in CI.
- Add secret scanning in CI or pre-commit.
- Avoid loading optional plugins or arbitrary modules from user-controlled paths.

CI should run Ruff, pytest, secret scanning, and dependency vulnerability scanning before changes are merged.

## Google Calendar Integration

Use OAuth for private calendar access. An API key is not enough for private Google Calendar data.

Use the read-only scope for v1:

```text
https://www.googleapis.com/auth/calendar.readonly
```

Initial setup:

1. Create a Google Cloud project.
2. Enable the Google Calendar API.
3. Configure OAuth consent.
4. Create OAuth client credentials.
5. Save the credential JSON at `GOOGLE_CREDENTIALS_PATH`.
6. Run a local OAuth bootstrap command to create `GOOGLE_TOKEN_PATH`.

Runtime behavior:

- Load credentials from `GOOGLE_TOKEN_PATH`.
- Refresh tokens automatically.
- Fail clearly if credentials are missing, invalid, or require interactive consent.
- Keep the OAuth browser flow out of normal bot startup.
- Treat credential and token files as secrets.
- Verify that loaded credentials contain only the scopes required by the enabled features.

The official Google Python client is synchronous. Calendar calls must be isolated in the calendar adapter and executed with `asyncio.to_thread` or an equivalent executor boundary so the Discord event loop is not blocked by Google I/O.

OAuth bootstrap is sensitive operator functionality:

- Run `google-auth-login` only on a trusted machine.
- Print the authenticated Google account email after login.
- Print the granted scopes, token output path, and a short calendar list preview before writing the token.
- Require explicit confirmation before writing the token file.
- Refuse to overwrite an existing token unless `--force` is supplied.
- Verify the resulting credentials include the read-only calendar scope for v1.
- Store non-secret token metadata, such as account email, granted scopes, and creation time, in a sidecar metadata file for operator verification.

## Calendar Query Rules

For each configured calendar, call `events.list` with:

```text
timeMin=<target local midnight converted to RFC3339>
timeMax=<next local midnight converted to RFC3339>
singleEvents=true
orderBy=startTime
showDeleted=false
timeZone=<BOT_TIMEZONE>
```

After fetching:

- Normalize all event start and end values into `BOT_TIMEZONE`.
- Include all-day events whose date range overlaps the target local date.
- Include timed events that overlap the target local date, even if they start before midnight or end after midnight.
- Include recurring event instances after expansion with `singleEvents=true`.
- Ignore cancelled events.
- Deduplicate stable Google instances by calendar ID plus event instance identity.

This daily bounded query is simpler than incremental sync for v1. Incremental sync can be introduced later if the bot starts doing frequent polling or real-time reminders.

## Tag Filtering

Google Calendar does not provide a universal user-facing tag field, so v1 uses a visible text marker.

Default behavior:

- `EVENT_TAG` is an exact token, for example `#discord-daily` or `[discord]`.
- `EVENT_TAG_FIELDS` defaults to `summary,description`.
- Matching is case-insensitive.
- Matching is token-aware so `#discord` does not match `#discordant`.
- Google descriptions are normalized before matching: strip HTML tags, decode entities, and collapse whitespace.
- If the tag appears in the event summary, remove it from the displayed title.

Future tag strategies can be added behind the same `TagFilter` boundary:

- Google `extendedProperties.private`
- Google `extendedProperties.shared`
- event color ID
- dedicated calendar instead of a tag

Source calendar permissions matter. Anyone who can edit a tagged source calendar can influence bot output in Discord. Prefer a dedicated digest calendar or restrict edit access to trusted users if the main calendar has broad editors or external integrations.

## Discord Integration

Use `discord.py`.

Required permissions:

- View Channel
- Send Messages

Optional permission:

- Read Message History, only if a future feature needs to inspect channel history

Gateway intents:

- Use default or minimal intents.
- Do not enable privileged message content intent for v1.

Channel validation:

- Guild exists and matches `DISCORD_GUILD_ID`.
- Channel exists and belongs to that guild.
- Channel supports bot messages.
- Bot has `View Channel` and `Send Messages`.

Mention safety:

- Disable mentions by default with `discord.AllowedMentions.none()`.
- If `ENABLE_ROLE_MENTION=true`, prepend only the configured role mention.
- Explicitly allow only `DISCORD_ROLE_MENTION_ID`.
- Never allow `@everyone`, user mentions, or role mentions parsed from calendar event text.
- Validate that the configured role belongs to `DISCORD_GUILD_ID`.
- Reject `@everyone`, managed roles, and privileged roles for automatic mention behavior.
- Treat roles as privileged if they have permissions such as `administrator`, `manage_guild`, `manage_roles`, `manage_channels`, or similarly elevated operational permissions.
- Prefer an explicit allowlist of mentionable role IDs.
- Log the configured role name and member count at startup after validation.

Message behavior:

- Post one logical digest per day.
- Split into multiple numbered messages only if needed for Discord length limits.
- Store all Discord message IDs for split digests.
- Include local date, all-day events, timed events, and optional location/link if allowed by URL policy.
- Do not expose Google internal IDs.

Calendar event content is untrusted input:

- Pass every event summary, description, location, and link label through `DiscordContentSanitizer`.
- Neutralize Discord mentions in text independently from `AllowedMentions`.
- Escape or normalize Discord markdown, code blocks, masked links, custom emoji syntax, channel mentions, role mentions, and user mentions.
- Strip or replace Unicode control characters and bidirectional override characters.
- Truncate long summaries, descriptions, locations, and links.
- Omit descriptions by default unless a future product requirement needs them.
- Avoid masked markdown links for untrusted URLs.
- Include only title and time in v1 by default.
- Make location, link, and description display separately opt-in.
- Remove the event tag from displayed titles before output.

URL policy defaults:

- Event description links are omitted.
- Google event `htmlLink` values are omitted.
- Conference links, including Google Meet, Zoom, and Teams links, are omitted by default.
- Location URLs are shown only when location display is enabled, the URL uses `https`, and it is not recognized as a private meeting link.
- Masked markdown links are rejected.
- Query strings are stripped unless a future feature explicitly requires them.
- Display either the hostname or a plain sanitized URL plus hostname; do not hide the destination behind custom link text.

## Scheduling

Use `APScheduler` with `AsyncIOScheduler`.

Daily trigger:

```text
CronTrigger(hour=<hour>, minute=<minute>, timezone=BOT_TIMEZONE)
```

Rules:

- Start the scheduler only after Discord readiness and channel validation.
- Guard scheduler startup with an in-memory flag because `on_ready` can fire more than once.
- Use `max_instances=1` for the daily job.
- Use a short misfire grace period, such as 15 minutes.
- Use `BOT_TIMEZONE` for the scheduled time, target date, and displayed event times.
- On startup, if no successful digest exists and current local time is after 7:00 AM but before `CATCH_UP_CUTOFF_TIME`, send the digest once.
- After `CATCH_UP_CUTOFF_TIME`, skip automatic catch-up and require a manual command.
- At startup, log current UTC time, configured timezone, computed local time, target date, and next scheduled run.
- Production hosts should use NTP or another reliable time synchronization mechanism.

DST behavior:

- The timezone-aware cron trigger is authoritative.
- The target day window is calculated from local midnight to next local midnight in `BOT_TIMEZONE`.
- Tests should cover normal days and DST transition days for the configured timezone.

## SQLite State

Use local SQLite for digest-level idempotency and run history.

Recommended table: `digest_runs`

```text
run_key TEXT PRIMARY KEY
target_date TEXT NOT NULL
timezone TEXT NOT NULL
guild_id TEXT NOT NULL
channel_id TEXT NOT NULL
calendar_ids_hash TEXT NOT NULL
event_tag_hash TEXT NOT NULL
status TEXT NOT NULL
attempt_count INTEGER NOT NULL DEFAULT 0
discord_message_ids TEXT
partial_discord_message_ids TEXT
lock_owner TEXT
locked_at TEXT
lock_expires_at TEXT
last_error TEXT
last_error_kind TEXT
created_at TEXT NOT NULL
updated_at TEXT NOT NULL
finished_at TEXT
```

Useful statuses:

- `posting`
- `posted`
- `skipped_empty`
- `failed_retryable`
- `failed_non_retryable`
- `partial_posted`

Run key:

```text
daily:<target_date>:<timezone>:<guild_id>:<channel_id>:<calendar_ids_hash>:<event_tag_hash>
```

Rules:

- Claim a run with an atomic insert or compare-and-update transaction.
- If the run is already `posted`, exit successfully.
- If another process owns a non-expired `posting` lock, exit without posting.
- If a lock is stale, mark it failed or reclaim it according to repository policy.
- If a publish fails before Discord accepts a message, mark failure as retryable or non-retryable.
- If some split message parts were posted, record `partial_posted` with known message IDs.
- Do not blindly repost a full digest after partial delivery.
- If Discord accepts a message but SQLite cannot record success, log the Discord message ID immediately. Manual reconciliation may be required.
- Store the minimum state needed for idempotency and reconciliation.
- Do not store event summaries, descriptions, locations, attendees, or raw calendar IDs unless a future audited feature requires it.
- Sanitize and cap `last_error`.
- Set restrictive permissions on the SQLite file.
- Define a retention policy for old digest runs.
- Enable WAL mode when it improves reliability for the deployment.
- Use timezone-aware timestamps from the injected `Clock`.
- Treat database write failure after Discord accepts a message as high severity.

An event-level audit table is optional and should not be added until needed.

Retention defaults:

- Successful and skipped runs: keep 90 days.
- Retryable and non-retryable failed runs: keep 180 days.
- Partial delivery and force/reconciliation records: keep until manually resolved, then retain 180 days.
- Cleanup must never delete unresolved partial deliveries.

## Retry Policy

Retry inside one digest run for transient failures:

- Google 5xx
- Discord 429
- Discord 5xx
- network timeouts

Use bounded exponential backoff with jitter. Respect Discord `Retry-After` headers. Keep the total retry duration below `RUN_LOCK_TTL_SECONDS` so another invocation does not incorrectly treat the run as stale.

Default retry bounds:

- Discord transient failures: at most 3 attempts.
- Google transient failures: at most 3 attempts.
- Total retry elapsed time must be less than `RUN_LOCK_TTL_SECONDS` minus a cleanup margin.
- Persist retry attempt counts.

Do not retry automatically for non-retryable failures:

- invalid Discord token
- missing Discord permissions
- missing Discord channel
- invalid Google credentials
- Google authorization failure requiring user action
- invalid configuration

Avoid retrying after Discord has accepted a message unless the ledger proves the accepted message belongs to a partial delivery that can be resumed safely.

## Operator Commands

The bot should expose local CLI commands even though it is primarily a long-running Discord process.

Suggested commands:

```text
uv run python -m discordcalendarbot google-auth-login --confirm-write-token token.json
uv run python -m discordcalendarbot dry-run --date 2026-05-02
uv run python -m discordcalendarbot send-digest --date 2026-05-02
uv run python -m discordcalendarbot send-digest --date 2026-05-02 --force --confirm-force 2026-05-02 --channel-id <discord_channel_id>
uv run python -m discordcalendarbot reconcile-digest --date 2026-05-02 --message-id <discord_message_id> --confirm-reconcile 2026-05-02
```

`dry-run` should:

- Load real configuration.
- Validate Google auth.
- Fetch calendar events.
- Apply local-day and tag filtering.
- Render the Discord message.
- Print the message to stdout without writing private event details to normal application logs.
- Avoid marking a run as posted.
- Support `--redact` or `--summary-only` for safer troubleshooting.

`send-digest` should:

- Use the same `DailyDigestService` as the scheduler.
- Respect idempotency by default.
- Require explicit target date and channel for forced posts.
- Require both `--force` and a confirmation flag whose value includes the target date, for example `--confirm-force 2026-05-02`.
- Show a dry-run preview before force posting unless the operator explicitly disables preview.
- Store force repost attempts separately from normal idempotency keys.
- Log force reposts with sanitized operator context.
- Store `forced_at`, `forced_reason`, and `forced_by` when operator identity is available.

`reconcile-digest` should:

- Let an operator mark a run as posted or partial using known Discord message IDs.
- Require explicit confirmation.
- Never fetch Google Calendar data.
- Prefer append-only reconciliation records over overwriting existing state.

Future slash commands should call the same service layer rather than duplicating business logic.

Before adding slash commands, define command authorization, audit logging, rate limits, and input validation. Keep Google write scopes out of the daily digest process until event creation is actually implemented.

Local CLI commands are authenticated by host access. Restrict service account shell access, keep `.env` and token files unreadable to other users, and consider refusing powerful commands unless they are run as the expected service account.

## Future Command Authorization

Slash commands and event creation are out of scope for v1, but they must not be added without an explicit authorization model.

Before adding commands:

- Define allowed Discord users or roles per command.
- Add rate limits per user and command.
- Add audit logs for manual digest sends, status checks, role mention changes, calendar selection changes, reminder changes, and event creation.
- Validate all command input before it reaches Google Calendar or storage.
- Keep Google write scopes separate from the read-only daily digest path.
- Consider separate credentials for read-only digest behavior and future write actions.
- Keep command handlers thin and call application services.

## Dependencies

Runtime dependencies:

```text
discord.py
APScheduler
google-api-python-client
google-auth-httplib2
google-auth-oauthlib
pydantic-settings
python-dotenv
aiosqlite
```

Development dependencies:

```text
pytest
pytest-asyncio
pytest-mock
ruff
freezegun
```

Use `uv` for dependency management and command execution.

Commit `uv.lock` once dependencies are added. Dependency updates should be reviewed and scanned for known vulnerabilities before deployment.

## Testing Strategy

Use `pytest`. Do not use `unittest`. Avoid real network calls in unit tests.

Unit tests:

- `.gitignore` includes documented secret and state patterns.
- Settings parsing and validation.
- Settings reject unsafe or missing secret paths.
- Settings reject role mentions without a valid configured role.
- Path validation resolves symlinks and handles Windows case-insensitive path comparisons.
- Secret file permission checks detect unsafe Unix modes.
- Windows ACL inspection detects broad read principals through a test adapter.
- Timezone-aware day-window calculation.
- DST transition behavior.
- Google payload normalization.
- All-day, timed, crossing-midnight, and recurring events.
- Cancelled event exclusion.
- HTML-normalized tag filtering.
- Token-aware tag matching.
- Display title cleanup.
- Digest sorting and empty-day behavior.
- Discord formatting and message splitting.
- Mention safety.
- Markdown, mention, masked-link, and oversized-field neutralization.
- Unicode control and bidirectional character neutralization.
- URL policy for event links and locations.
- SQLite idempotency and stale lock handling.
- SQLite error sanitization and length caps.
- Scheduler duplicate-start guard.
- Dry-run avoids writing private event details to normal logs.
- Log sanitizer redacts token-like strings, OAuth client secrets, bearer tokens, URLs with query strings, and local secret paths.

Service tests:

- Successful daily digest posts once and records success.
- Existing successful digest skips Google fetch and Discord post.
- No tagged events skips or posts based on configuration.
- Google failure records failure and does not post.
- Discord failure records retryable or non-retryable failure.
- Split-message partial delivery records partial state.
- Manual trigger respects idempotency.
- `--force --confirm-force` is the only intentional duplicate path.
- Force and reconcile commands require explicit date/channel confirmation.
- Reconciliation records are append-only where possible.
- Partial delivery never triggers an automatic full repost.
- Retry logic respects Discord rate limit backoff.
- Retry duration remains below lock TTL.

Adapter tests:

- Google adapter sends expected `events.list` parameters.
- Google adapter executes synchronous calls through an executor boundary.
- Google OAuth credentials are limited to the expected scope.
- Discord publisher validates guild/channel/permissions.
- Discord publisher disables mentions by default.
- Discord publisher permits only the configured role when enabled.

Suggested local checks:

```text
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Incremental Delivery Plan

1. Project foundation
   - Move application code under `src/discordcalendarbot`.
   - Add package `__init__.py` files.
   - Add `uv` dependencies.
   - Add Ruff and pytest configuration.
   - Update `.gitignore` for secrets and local state.
   - Add initial security tests for ignore patterns and config validation.

2. Configuration and domain
   - Implement typed settings.
   - Add domain models.
   - Add timezone and date-window tests.
   - Add path validation, secret permission checks, and log redaction primitives.

3. Google Calendar read path
   - Implement OAuth bootstrap.
   - Implement token loading and refresh.
   - Implement event retrieval with executor isolation.
   - Implement mapper and local-day overlap filtering.
   - Add JSON fixture tests.

4. Tag filtering and digest formatting
   - Implement HTML-normalized tag matching.
   - Implement title cleanup.
   - Implement sorting and empty digest policy.
   - Implement Discord message formatting and splitting.
   - Implement the single Discord content sanitizer and precise URL policy.

5. SQLite idempotency
   - Implement schema initialization.
   - Implement atomic run claim.
   - Implement posted, skipped, failed, and partial states.
   - Add duplicate and stale-lock tests.
   - Add error sanitization, retention, and restrictive file permission handling.

6. Discord bot shell
   - Implement `discord.py` startup.
   - Validate guild and channel.
   - Implement mention-safe publisher.
   - Implement markdown neutralization and URL policy.
   - Add mocked Discord tests.

7. Scheduler integration
   - Add `AsyncIOScheduler`.
   - Add reconnect-safe startup guard.
   - Add 7:00 AM cron trigger.
   - Add misfire and catch-up behavior.

8. Operator commands
   - Add `google-auth-login`.
   - Add `dry-run`.
   - Add `send-digest`.
   - Add `--force --confirm-force` for intentional reposts.
   - Add reconciliation tooling for partial delivery.
   - Add operator audit metadata where available.

9. Documentation
   - Document Discord bot setup.
   - Document Google OAuth setup.
   - Document environment variables.
   - Document running the bot as a long-lived process on Windows and Linux.
   - Document filesystem permissions, deployment hardening, dry-run sensitivity, and token rotation.
   - Document data retention, backup encryption, privacy expectations for the target Discord channel, and calendar sharing assumptions.

## Future Extensions

The chosen architecture supports:

- Slash commands for manual digest and status.
- Discord command to add Google Calendar events.
- Reminder commands such as "remind me 30 minutes before".
- Role mentions for specific digest types.
- Multiple configured channels.
- Per-guild configuration stored in SQLite.
- More frequent polling for upcoming event reminders.

For event creation, add a write-capable Google Calendar adapter and request a broader OAuth scope only when that feature is implemented. Keep read-only scope for v1.

For "remind me before event" behavior, introduce a separate reminder scheduler/use case that reuses calendar retrieval, tag filtering, Discord publishing, and SQLite state. If reminders are configured through Discord commands, keep the commands thin and call the service layer.

## Key Tradeoffs

Benefits:

- Strong foundation for interactive Discord features.
- Clear service boundaries and testable business logic.
- No public webhook endpoint required.
- Minimal Discord intents for v1.
- Local SQLite keeps deployment simple.

Costs:

- More complex than a scheduled CLI for a single daily post.
- Requires a continuously running process.
- Requires process supervision on the deployment machine.
- Google API calls must be isolated from the async event loop.
- Local SQLite and OAuth token files must move with the bot if the deployment moves.
