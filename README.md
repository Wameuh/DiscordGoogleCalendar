# Discord Calendar Bot

This repository contains the implementation scaffold for a Discord bot that will connect to one or more Google Calendars and post tagged daily event digests to a configured Discord channel.

The planned bot is designed to run as a long-lived Python process on both Windows and Linux. It uses outbound connections only for the first version: Discord Gateway/API plus Google Calendar API. No public inbound web server is required.

## Architecture

The selected architecture is documented in [ARCHITECTURE.md](ARCHITECTURE.md).

In short, the v0.1.1 target architecture is:

- The bot runs with `discord.py`.
- An internal scheduler posts the daily digest at 7:00 AM in the configured timezone.
- Google Calendar is accessed with OAuth read-only credentials for version 1.
- SQLite stores digest run state so the bot can avoid duplicate posts.
- Local operator commands support OAuth bootstrap, dry runs, and manual recovery.

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

## Security Notes

The bot handles sensitive data: Discord bot tokens, Google OAuth credentials, Google refresh tokens, private calendar event content, Discord channel metadata, logs, and SQLite state.

Before using real credentials:

- Keep `.env`, `credentials.json`, `token.json`, SQLite files, and local data directories out of git.
- Restrict secret file permissions. On Linux, prefer `0600` for secret files and `0700` for secret directories. On Windows, make them readable only by the service account or current user.
- Treat calendar event text as untrusted input before posting it to Discord.
- Keep Discord mentions disabled by default.
- Do not run dry runs with real calendar data in shared terminals or CI logs.
- Commit and review `uv.lock` once dependencies are added.

See [CyberSecurityAnalysis.md](CyberSecurityAnalysis.md) for the architecture-level security review and [ARCHITECTURE.md](ARCHITECTURE.md) for the security controls folded into the design.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
