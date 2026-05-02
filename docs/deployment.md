# Deployment And Operations Guide

This guide covers v0.1.1 of Discord Calendar Bot. The bot is a long-running outbound-only process: it connects to Discord and Google Calendar, runs an internal APScheduler daily job, and stores idempotency state in SQLite.

## Setup Overview

1. Install Python and `uv`.
2. Create a Discord bot with only the permissions needed for the target channel.
3. Create Google OAuth credentials for an installed application.
4. Put `.env`, Google credentials, OAuth token, SQLite state, and logs in a private directory.
5. Run `google-auth-login` on a trusted machine.
6. Start the bot under a dedicated least-privilege account and supervisor.

The first version intentionally has no FastAPI app, inbound web server, Discord privileged message-content intent, Google write scope, or multi-guild configuration.

## Discord Setup

Create a bot application in the Discord developer portal and invite it to one server. Grant only:

- View Channel
- Send Messages

Do not enable the privileged Message Content intent. The bot validates one configured guild and one configured channel before starting the scheduler. If role mentions are enabled, configure only a non-managed, mentionable, non-privileged role.

## Google OAuth Setup

Create OAuth client credentials for a desktop/installed application and store the downloaded JSON at `GOOGLE_CREDENTIALS_PATH`. Then run:

```powershell
uv run python -m discordcalendarbot google-auth-login --confirm-write-token token.json
```

Use `--force` only when intentionally replacing an existing token. The OAuth flow requests only:

```text
https://www.googleapis.com/auth/calendar.readonly
```

The command writes `token.json` and a non-secret metadata sidecar. On Unix-like systems, the token file is restricted to `0600`.

## Environment Variables

Required:

```text
DISCORD_BOT_TOKEN=
DISCORD_GUILD_ID=
DISCORD_CHANNEL_ID=
GOOGLE_CREDENTIALS_PATH=
GOOGLE_TOKEN_PATH=
GOOGLE_CALENDAR_IDS=primary
EVENT_TAG=#discord-daily
EVENT_FILTER_MODE=tagged
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

Keep `.env` out of git and readable only by the service account.

`EVENT_FILTER_MODE` defaults to `tagged`, which posts only events containing `EVENT_TAG`. Set `EVENT_FILTER_MODE=all` to post every event from the configured calendars for the target day; in that mode `EVENT_TAG` may be omitted. This can copy private calendar details into Discord, so prefer a dedicated calendar or a tightly controlled Discord channel before enabling it.

The CLI uses `python-dotenv` to load a `.env` file from the current working directory before settings validation. Production supervisors may also inject these values directly into the process environment instead of relying on a `.env` file.

## Running The Bot

From the project directory:

```powershell
uv run python -m discordcalendarbot
```

The scheduler starts only after Discord readiness and target validation. Startup catch-up runs only after the digest time and before `CATCH_UP_CUTOFF_TIME`; after the cutoff, use an operator command.

## Operator Commands

Preview without posting:

```powershell
uv run python -m discordcalendarbot dry-run --date 2026-05-02 --redact
uv run python -m discordcalendarbot dry-run --date 2026-05-02 --summary-only
```

Verify only Google Calendar access without Discord or SQLite state:

```powershell
uv run python -m discordcalendarbot check-google-calendar --date 2026-05-02
```

Verify only Discord connectivity and target permissions without Google Calendar or SQLite state:

```powershell
uv run python -m discordcalendarbot check-discord
```

Verify the full read, filter, format, and Discord-permission path without sending a message or writing SQLite state:

```powershell
uv run python -m discordcalendarbot check-full-digest --date 2026-05-02
```

Send while respecting normal idempotency:

```powershell
uv run python -m discordcalendarbot send-digest --date 2026-05-02
```

Force an intentional duplicate only with date and channel confirmation:

```powershell
uv run python -m discordcalendarbot send-digest --date 2026-05-02 --force --confirm-force 2026-05-02 --channel-id 456
```

Reconcile known Discord message IDs after a partial delivery or manual recovery:

```powershell
uv run python -m discordcalendarbot reconcile-digest --date 2026-05-02 --message-id 111 --confirm-reconcile 2026-05-02
uv run python -m discordcalendarbot reconcile-digest --date 2026-05-02 --message-id 111 --partial --confirm-reconcile 2026-05-02
```

Dry-run output can contain private calendar titles. Use `--redact` or `--summary-only` in shared terminals, tickets, CI logs, or screen recordings.

If dry-run cannot read Google Calendar data, it exits non-zero and reports a safe operator message for authentication, access, timeout, network, or event-normalization failures. `Dry run for <date>: 0 Discord message part(s).` should mean the read path succeeded and no digest message would be produced.

`check-google-calendar` authenticates with Google, queries configured calendars for the local-day window, normalizes events, applies the configured digest filter, and prints only safe counters. It does not print event titles, descriptions, locations, links, raw calendar IDs, OAuth payloads, or Discord data.

`check-discord` connects with minimal guild intents, validates the configured guild and channel, confirms `View Channel` and `Send Messages`, then disconnects without sending a message.

`check-full-digest` authenticates with Google, reads configured calendars, applies the configured digest filter, formats Discord message payloads in memory, validates Discord target permissions, and prints only safe status, counters, and permission confirmations. It never calls Discord publishing and does not open or write SQLite state.

## Windows Deployment

Use a dedicated local or domain account that is not an administrator. Store secrets and state outside the source tree, for example:

```text
C:\DiscordCalendarBot\secrets\.env
C:\DiscordCalendarBot\secrets\credentials.json
C:\DiscordCalendarBot\secrets\token.json
C:\DiscordCalendarBot\state\discordcalendarbot.sqlite3
```

Restrict ACLs so only the service account and required administrators can read those files. Run the process with a service wrapper, Windows Task Scheduler startup task, or another supervisor that restarts the process with bounded restart behavior.

## Linux Deployment

Create a dedicated user such as `discordcalendarbot`. Store secrets and state outside the repository, for example:

```text
/etc/discordcalendarbot/.env
/etc/discordcalendarbot/credentials.json
/etc/discordcalendarbot/token.json
/var/lib/discordcalendarbot/discordcalendarbot.sqlite3
```

Recommended modes:

```bash
chmod 700 /etc/discordcalendarbot /var/lib/discordcalendarbot
chmod 600 /etc/discordcalendarbot/.env /etc/discordcalendarbot/credentials.json /etc/discordcalendarbot/token.json
```

Use systemd, Docker, or another supervisor. Keep host time synchronized with NTP because local dates and idempotency keys depend on `BOT_TIMEZONE`.

## Permissions And Secrets

- Do not commit `.env`, `credentials.json`, `token.json`, OAuth metadata sidecars, SQLite files, logs, scan outputs, local archives, downloaded binaries, cache folders, or local data directories.
- Before each commit, inspect `git status --short`, `git diff --cached --name-only`, and `git diff --cached` to verify that no secret, runtime artifact, or private calendar/Discord data is staged.
- Do not paste Discord tokens, OAuth payloads, rendered digests, or dry-run output into CI logs or shared issue trackers.
- Rotate the Discord bot token if it appears in logs, screenshots, shell history, or chat. Reset it in the Discord developer portal, update `DISCORD_BOT_TOKEN`, restart the service, and verify the bot reconnects only to the configured guild and channel.
- Revoke the Google OAuth token and rerun `google-auth-login` if `token.json` is exposed. Delete the exposed token, revoke the app grant from the Google account security page, run `uv run python -m discordcalendarbot google-auth-login --force --confirm-write-token token.json`, restrict the new token file permissions, and restart the service.
- Replace OAuth client credentials if `credentials.json` is exposed. Regenerate the desktop OAuth client in Google Cloud Console, update `GOOGLE_CREDENTIALS_PATH`, rerun the login flow, and remove old copies from backups, shell history, and deployment artifacts.
- Back up tokens and SQLite state only with encrypted backups. If encrypted backups are not available, exclude OAuth tokens and recreate them during restore.

## Retention And Privacy

SQLite cleanup policy is implemented at repository level:

- Posted and skipped runs: 90 days.
- Retryable and non-retryable failed runs: 180 days.
- Unresolved partial deliveries are preserved for manual reconciliation.

The digest posts title and time by default. Calendar editors can influence bot output by adding the configured tag, so restrict source calendar edit access or use a dedicated digest calendar.

Make sure the target Discord channel audience is appropriate for the calendar data copied into Discord. Discord retention, search, bots, and exports differ from Google Calendar.

## CI

GitHub Actions runs:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run pytest`
- `uv run --with pip-audit pip-audit --local`
- `gitleaks/gitleaks-action`

CI must never require real Discord or Google credentials. Tests use fakes and mocks for external services.
