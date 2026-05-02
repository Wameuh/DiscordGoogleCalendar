# Agent 5 - Documentation reviewer

Status: Changes requested
Reviewed TODO: TODO 9 - Documentation, Deployment, And CI
Review iteration: 1
Reviewed files:

- `README.md`
- `docs/deployment.md`
- `CyberSecurityAnalysis.md`
- `ARCHITECTURE.md`
- `.github/workflows/ci.yml`
- `src/discordcalendarbot/cli.py`
- `src/discordcalendarbot/operator_commands.py`
- `src/discordcalendarbot/config.py`

## Findings

- Severity: High
  File: `docs/deployment.md:81`
  Issue: The deployment guide documents `uv run python -m discordcalendarbot` as the command to run the long-lived bot, and the README describes the bot as a long-lived process with `discord.py` and a scheduler. The current default CLI handler only calls `build_application()` with no settings and returns `0`, so the documented command exits without loading configuration, connecting to Discord, or starting the scheduler.
  Impact: Operators following the deployment guide will believe the service is running when it has not started, which can lead to missed daily digests and misleading Windows/Linux supervisor setup.
  Required change: Align the documented run command with the implemented startup behavior, or wire the default CLI path to load settings and run `RuntimeApplication.run()` before approving deployment documentation.

- Severity: Medium
  File: `docs/deployment.md:10`
  Issue: The guide says to place `.env` in a private secrets directory and later shows external paths such as `C:\DiscordCalendarBot\secrets\.env` and `/etc/discordcalendarbot/.env`, but it does not document how those variables are loaded by the process or service manager. The local operator loader calls `load_dotenv()` without an explicit path, which only covers the default working-directory `.env` behavior.
  Impact: Windows Task Scheduler, systemd, Docker, or service-wrapper deployments may start without required environment variables even though the operator followed the documented private-directory layout.
  Required change: Document the supported environment-loading model for Windows and Linux, such as service-manager environment entries, an explicit env file loaded by the supervisor, or a working-directory `.env` location that the application actually reads.

- Severity: Low
  File: `README.md:74`
  Issue: The README optional settings list omits `EMPTY_DIGEST_TEXT`, while `docs/deployment.md`, `ARCHITECTURE.md`, and `src/discordcalendarbot/config.py` document and implement it.
  Impact: The README's quick configuration summary is incomplete and inconsistent with the detailed deployment guide.
  Required change: Add `EMPTY_DIGEST_TEXT` to the README optional settings list.

- Severity: Low
  File: `CyberSecurityAnalysis.md:313`
  Issue: The security analysis still records "No Explicit Secret Rotation Schedule" and recommends documenting how and when to rotate Discord and Google tokens. The deployment guide only documents exposure-triggered rotation/revocation, not a normal rotation cadence or step-by-step rotation procedure.
  Impact: TODO 9 explicitly includes token rotation documentation, but the documentation set still leaves the rotation schedule and operator procedure ambiguous.
  Required change: Add concise rotation guidance to the deployment documentation, or explicitly state that rotation is exposure-driven for v0.1.1 and keep the security analysis item as an accepted residual risk.

## Approval Notes

The documentation covers the major requested areas: setup, required and optional environment variables, local commands, Windows/Linux deployment, least-privilege permissions, dry-run sensitivity, encrypted backups, retention, privacy expectations, and CI gates. CI documentation matches `.github/workflows/ci.yml` for Ruff linting, Ruff format checks, pytest, `pip-audit`, and Gitleaks.

Approval is blocked by the documented startup command not matching the current CLI behavior and by the smaller documentation consistency gaps above.
