# Deployment And Operations Guide

This guide covers v0.1.1 of Discord Calendar Bot. The bot is a long-running outbound-only process: it connects to Discord and Google Calendar, runs an internal APScheduler daily job, and stores idempotency state in SQLite.

## Setup Overview

1. Install `uv`, then use `uv` to install Python 3.12 and project dependencies.
2. Create a Discord bot with only the permissions needed for the target channel.
3. Create Google OAuth credentials for an installed application.
4. Put `.env`, Google credentials, OAuth token, SQLite state, and logs in a private directory.
5. Run `google-auth-login` on a trusted machine.
6. Start the bot under a dedicated least-privilege account and supervisor.

The first version intentionally has no FastAPI app, inbound web server, Discord privileged message-content intent, Google write scope, or multi-guild configuration.

Python 3.12 is the supported runtime. The repository pins the runtime in `.python-version`, and CI reads that file when setting up Python. On Linux servers, prefer the `uv` installer and `uv python install` instead of installing Python through the system package manager:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv sync --locked
```

The project includes Python timezone data as a dependency, so `uv sync --locked` installs what `ZoneInfo` needs to resolve `BOT_TIMEZONE`.

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
BOT_TIMEZONE=Europe/Kyiv
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
LOG_FILE_PATH=
LOG_MAX_BYTES=1048576
LOG_BACKUP_COUNT=2
```

Keep `.env` out of git and readable only by the service account.

`EVENT_FILTER_MODE` defaults to `tagged`, which posts only events containing `EVENT_TAG`. Set `EVENT_FILTER_MODE=all` to post every event from the configured calendars for the target day; in that mode `EVENT_TAG` may be omitted. This can copy private calendar details into Discord, so prefer a dedicated calendar or a tightly controlled Discord channel before enabling it.

The CLI uses `python-dotenv` to load a `.env` file from the current working directory before settings validation. Production supervisors may also inject these values directly into the process environment instead of relying on a `.env` file.

## Logging

The bot always writes console logs. Foreground runs show those logs in the terminal, and the Linux `systemd` example captures the same stream in the journal. Inspect journal logs without printing environment files or secret files:

```bash
sudo journalctl -u discordcalendarbot -n 100 --no-pager
sudo journalctl -u discordcalendarbot -f
```

Set `LOG_FILE_PATH` to enable local rotating file logs. Recommended paths are:

```text
/var/log/discordcalendarbot/bot.log
C:\DiscordCalendarBot\logs\bot.log
```

The default rotation policy is:

```text
LOG_MAX_BYTES=1048576
LOG_BACKUP_COUNT=2
```

This keeps one active log file plus two rotated backups, for three files total. The application creates the log directory when needed and restricts Unix-like permissions where practical. Logs are sanitized for common token, OAuth, URL query, and secret-path leaks, but they remain operational records and must be protected. Include logs in backups only when the backups are encrypted and access-controlled.

## Running The Bot

From the project directory:

```bash
uv run python -m discordcalendarbot
```

This foreground command is useful for manual validation, but production should use a supervisor so the bot survives SSH disconnects, reboots, and transient failures. The scheduler starts only after Discord readiness and target validation. Startup catch-up runs only after the digest time and before `CATCH_UP_CUTOFF_TIME`; after the cutoff, use an operator command.

For Linux servers using systemd, create `/etc/systemd/system/discordcalendarbot.service` and adjust `User`, `WorkingDirectory`, and the absolute path to `uv`:

```ini
[Unit]
Description=Discord Calendar Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=discordcalendarbot
WorkingDirectory=/opt/discordcalendarbot
ExecStart=/usr/local/bin/uv run python -m discordcalendarbot
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable and inspect it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now discordcalendarbot
sudo systemctl status discordcalendarbot
journalctl -u discordcalendarbot -f
```

The app loads `.env` from `WorkingDirectory`. Keep secrets and SQLite paths readable by the service user. If `BOT_TIMEZONE` cannot be resolved, run `uv sync --locked` again to make sure the Python `tzdata` dependency is installed.

### Reload Environment Changes

The bot reads `.env` only when the process starts. After changing values in `.env`, restart the systemd service so the running process picks up the new configuration:

```bash
sudo systemctl restart discordcalendarbot
sudo systemctl status discordcalendarbot --no-pager
```

Inspect recent logs without printing environment values or secret files:

```bash
sudo journalctl -u discordcalendarbot -n 100 --no-pager
sudo journalctl -u discordcalendarbot -f
```

Run `daemon-reload` only when the systemd unit file changed, not for a `.env`-only update:

```bash
sudo systemctl daemon-reload
sudo systemctl restart discordcalendarbot
```

If the restart does not use the expected values, inspect the active unit and confirm whether the service loads `.env` from `WorkingDirectory` or uses an explicit `EnvironmentFile`:

```bash
sudo systemctl cat discordcalendarbot
```

## Safe Update Procedure

Treat application code and private runtime data as separate assets. Update the versioned repository with git, and preserve runtime data in its existing protected locations. Do not replace the whole project directory with a fresh checkout, and do not copy a clean checkout over a directory that contains live `.env`, OAuth, SQLite, log, backup, `data/`, or `.state/` files.

Runtime data that must be preserved includes:

- `.env` and `.env.*`
- `credentials.json`
- `token.json` and `token.json.metadata.json`
- SQLite files such as `*.sqlite3`, `*.sqlite3-wal`, and `*.sqlite3-shm`
- log files and rotated log files
- encrypted backups
- local `data/`, `.state/`, secrets, state, and logs directories

### Pre-Update Checklist

Run this checklist before changing code:

- Inspect repository state with `git status --short`.
- Record the current commit with `git rev-parse --short HEAD`.
- Confirm the service state with `systemctl status discordcalendarbot` on Linux or the Windows service wrapper, Task Scheduler task, or supervisor status on Windows.
- Verify that runtime paths are outside the repository or ignored by git.
- Confirm that a recent backup exists for private runtime data.
- Do not print, commit, archive into the repository, paste, or upload the contents of `.env`, OAuth JSON files, SQLite state, logs, rendered digests, or private calendar data.

### Backup Runtime Data

Before updating, create a backup of only the private runtime data needed for recovery. Backups containing Discord tokens, Google OAuth credentials, refresh tokens, SQLite state, logs, or private calendar output must be encrypted and access-controlled. If encrypted backups are not available, exclude OAuth tokens and recreate them with `google-auth-login` during restore.

### Linux Update With Systemd

Use git to update code in place while keeping runtime files untouched:

```bash
cd /opt/discordcalendarbot
git status --short
git rev-parse --short HEAD
sudo systemctl stop discordcalendarbot
# Create an encrypted backup of /etc/discordcalendarbot, /var/lib/discordcalendarbot,
# and /var/log/discordcalendarbot before continuing.
git fetch --all --prune
git switch main
git pull --ff-only
uv sync --locked
uv run python -m discordcalendarbot check-google-calendar --date YYYY-MM-DD
uv run python -m discordcalendarbot check-discord
uv run python -m discordcalendarbot check-full-digest --date YYYY-MM-DD
sudo systemctl start discordcalendarbot
sudo systemctl status discordcalendarbot --no-pager
sudo journalctl -u discordcalendarbot -n 100 --no-pager
```

Use the target local date for `YYYY-MM-DD`. The check commands print safe counters and status messages; they must not print private event content, OAuth payloads, or Discord tokens.

### Windows Update

Use the same separation on Windows: stop the supervisor, back up runtime data, update code with git, then restart the supervisor.

```powershell
cd C:\DiscordCalendarBot\app
git status --short
git rev-parse --short HEAD
# Stop the Windows service wrapper, scheduled startup task, or supervisor here.
# Create a protected encrypted backup of C:\DiscordCalendarBot\secrets,
# C:\DiscordCalendarBot\state, and C:\DiscordCalendarBot\logs before continuing.
git fetch --all --prune
git switch main
git pull --ff-only
uv sync --locked
uv run python -m discordcalendarbot check-google-calendar --date YYYY-MM-DD
uv run python -m discordcalendarbot check-discord
uv run python -m discordcalendarbot check-full-digest --date YYYY-MM-DD
# Restart the Windows service wrapper, scheduled startup task, or supervisor here.
```

After restart, inspect the configured log file, supervisor output, or Windows event logs without printing secret files or private digest content.

### Rollback

If an update fails, stop the running service first, then return to the recorded commit before restoring runtime data.

Linux rollback:

```bash
sudo systemctl stop discordcalendarbot
git switch --detach <previous-commit>
uv sync --locked
sudo systemctl start discordcalendarbot
sudo systemctl status discordcalendarbot --no-pager
sudo journalctl -u discordcalendarbot -n 100 --no-pager
```

Windows rollback:

```powershell
# Stop the Windows service wrapper, scheduled startup task, or supervisor first.
git switch --detach <previous-commit>
uv sync --locked
# Restart the Windows service wrapper, scheduled startup task, or supervisor.
# Inspect the configured log file, supervisor output, or Windows event logs.
```

Restore runtime data from the encrypted backup only when the update changed or damaged local state. Prefer restoring the smallest necessary file set, such as SQLite state, instead of replacing the whole runtime directory.

### Update Mistakes To Avoid

- Do not run broad cleanup such as `git clean -fdx` unless the ignored-file list has been reviewed and runtime data is backed up.
- Do not delete ignored files just because they are absent from git.
- Do not copy a fresh checkout over an existing deployment directory.
- Do not stage or commit `.env`, credentials, tokens, SQLite databases, logs, backups, archives, cache folders, rendered digests, or private calendar/Discord data.
- Do not run diagnostic commands that print secret files, OAuth payloads, raw calendar events, rendered private digests, or full logs into shared terminals, CI, issue trackers, or chat.

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

`check-google-calendar` authenticates with Google, queries configured calendars for the local-day window, normalizes events, applies the configured digest filter, deduplicates matching digest events across calendars, and prints only safe counters. It does not print event titles, descriptions, locations, links, raw calendar IDs, OAuth payloads, or Discord data.

`check-discord` connects with minimal guild intents, validates the configured guild and channel, confirms `View Channel` and `Send Messages`, then disconnects without sending a message.

`check-full-digest` authenticates with Google, reads configured calendars, applies the configured digest filter, deduplicates matching digest events across calendars, formats Discord message payloads in memory, validates Discord target permissions, and prints only safe status, counters, and permission confirmations. It never calls Discord publishing and does not open or write SQLite state.

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
