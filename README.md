# Discord Calendar Bot

This repository contains a Discord bot that connects to one or more Google Calendars and posts tagged daily event digests to a configured Discord channel.

The bot is designed to run as a long-lived Python process on both Windows and Linux. It uses outbound connections only for the first version: Discord Gateway/API plus Google Calendar API. No public inbound web server is required.

## Architecture

The selected architecture is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

In short, v0.1.1 provides:

- The bot runs with `discord.py`.
- An internal scheduler posts the daily digest at 7:00 AM in the configured timezone.
- Google Calendar is accessed with OAuth read-only credentials for version 1.
- SQLite stores digest run state so the bot can avoid duplicate posts.
- Local operator commands support OAuth bootstrap, dry runs, and manual recovery.

Detailed setup and operations guidance is in [docs/deployment.md](docs/deployment.md).

## Supported Platforms

The project should work on:

- Windows 10/11 or Windows Server.
- Linux distributions that support Python and `uv`.

Platform expectations:

- Use `uv` for dependency and command execution on both platforms.
- Use environment variables or a local `.env` file for configuration.
- Run the bot under a dedicated least-privilege user or service account.
- Store OAuth tokens, `.env`, and SQLite state in a private directory.
- Use a process supervisor appropriate to the host, such as Windows Task Scheduler/service wrappers, systemd, Docker, or another managed service.

## Project Tooling

This project uses [uv](https://docs.astral.sh/uv/getting-started/installation/) to manage Python, dependencies, and project commands.

Install uv from the official documentation:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

On Linux, install `uv` from the same official documentation and run project commands with `uv run`.

Current foundation checks:

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

## Configuration

The implementation includes typed settings, Google Calendar read adapters, Discord formatting and publishing, SQLite idempotency, local operator commands, and the daily digest service/scheduler wiring. These environment variables are required:

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

The bot and local operator commands load a `.env` file from the current working directory with `python-dotenv` before reading environment variables. Deployment supervisors can also inject the same values directly through the process environment.

Optional settings include `EVENT_FILTER_MODE`, `EVENT_TAG_FIELDS`, `POST_EMPTY_DIGEST`, `EMPTY_DIGEST_TEXT`, `ENABLE_ROLE_MENTION`, `DISCORD_ROLE_MENTION_ID`, `CATCH_UP_CUTOFF_TIME`, `GOOGLE_REQUEST_TIMEOUT_SECONDS`, `DISCORD_PUBLISH_TIMEOUT_SECONDS`, `MAX_DISCORD_MESSAGE_CHARS`, `SCHEDULER_MISFIRE_GRACE_SECONDS`, `RUN_LOCK_TTL_SECONDS`, and `LOG_LEVEL`.

`EVENT_FILTER_MODE` defaults to `tagged`, which keeps the original behavior and posts only events matching `EVENT_TAG`. Set `EVENT_FILTER_MODE=all` to include every event returned by `GOOGLE_CALENDAR_IDS` for the target day; in that mode `EVENT_TAG` may be omitted. The `all` mode can expose private calendar content to Discord, so use it only with calendars and channels whose audience is appropriate.

Validation covers required values, positive Discord IDs, timezone names, `HH:MM` time values, comma-separated calendar IDs and tag fields, role mention configuration, bounded timeout/message settings, resolved paths, and whether in-repository secret/state paths are ignored by git.

## Local Operator Commands

The v0.1.1 command surface includes local host-authenticated commands:

```powershell
uv run python -m discordcalendarbot google-auth-login --confirm-write-token token.json
uv run python -m discordcalendarbot dry-run --date 2026-05-02 --redact
uv run python -m discordcalendarbot check-google-calendar --date 2026-05-02
uv run python -m discordcalendarbot check-discord
uv run python -m discordcalendarbot send-digest --date 2026-05-02
uv run python -m discordcalendarbot send-digest --date 2026-05-02 --force --confirm-force 2026-05-02 --channel-id 456
uv run python -m discordcalendarbot reconcile-digest --date 2026-05-02 --message-id 111 --confirm-reconcile 2026-05-02
```

`google-auth-login` writes the token only when `--confirm-write-token` matches the configured token filename. Forced sends require both the target date confirmation and the configured Discord channel ID. Dry-run output can contain private calendar details unless `--redact` or `--summary-only` is used.

`dry-run --summary-only` reports Google Calendar authentication, access, timeout, and mapping failures as command failures instead of showing `0 Discord message part(s)`. A zero-message summary means the calendar read and filtering completed successfully but produced no Discord output.

`check-google-calendar` verifies the Google Calendar read path without opening Discord or writing SQLite state. It prints only safe counters for configured calendars, raw events, normalized events, and digest filter matches.

`check-discord` verifies the bot token can connect to Discord, resolve the configured guild and channel, and confirm `View Channel` plus `Send Messages` permissions. It does not load Google settings, open Google Calendar clients, write SQLite state, or send a Discord message.

## Security Notes

The bot handles sensitive data: Discord bot tokens, Google OAuth credentials, Google refresh tokens, private calendar event content, Discord channel metadata, logs, and SQLite state.

Before using real credentials:

- Keep `.env`, `credentials.json`, `token.json`, SQLite files, and local data directories out of git.
- Keep OAuth metadata sidecars, local archives, downloaded binaries, cache folders, logs, and scan output artifacts out of git.
- Restrict secret file permissions. On Linux, prefer `0600` for secret files and `0700` for secret directories. On Windows, make them readable only by the service account or current user.
- Treat calendar event text as untrusted input before posting it to Discord.
- Keep Discord mentions disabled by default.
- Do not run dry runs with real calendar data in shared terminals or CI logs.
- Use encrypted backups for tokens, SQLite state, and logs. If encrypted backups are not available, exclude OAuth tokens and recreate them with `google-auth-login`.
- After exposure, rotate the Discord bot token in the Discord developer portal, delete and recreate Google OAuth tokens with `google-auth-login`, and replace exposed OAuth client credentials from Google Cloud Console.

See [docs/deployment.md](docs/deployment.md), [CyberSecurityAnalysis.md](CyberSecurityAnalysis.md), and [ARCHITECTURE.md](ARCHITECTURE.md) for operational and security guidance.

## Continuous Integration

CI runs Ruff linting, Ruff format checks, pytest, dependency vulnerability auditing, and secret scanning. The same local checks are:

```powershell
$env:UV_CACHE_DIR='.uv-cache'
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Before every commit, inspect `git status --short`, `git diff --cached --name-only`, and `git diff --cached` to verify that no `.env`, OAuth token, credential file, SQLite state, local archive, downloaded binary, cache, log, scan artifact, or private calendar/Discord data is staged.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
