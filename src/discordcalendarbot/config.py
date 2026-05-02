"""Configuration primitives for environment-backed settings."""

from __future__ import annotations

from collections.abc import Mapping

REQUIRED_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_GUILD_ID",
    "DISCORD_CHANNEL_ID",
    "GOOGLE_CREDENTIALS_PATH",
    "GOOGLE_TOKEN_PATH",
    "GOOGLE_CALENDAR_IDS",
    "EVENT_TAG",
    "BOT_TIMEZONE",
    "DAILY_DIGEST_TIME",
    "SQLITE_PATH",
)


class SettingsValidationError(ValueError):
    """Raised when environment-backed settings are incomplete or invalid."""


def missing_required_environment(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Return required environment variable names that are missing or blank."""
    return tuple(
        variable
        for variable in REQUIRED_ENVIRONMENT_VARIABLES
        if not environment.get(variable, "").strip()
    )


def validate_required_environment(environment: Mapping[str, str]) -> None:
    """Validate that the minimum required settings are present."""
    missing = missing_required_environment(environment)
    if missing:
        names = ", ".join(missing)
        raise SettingsValidationError(f"Missing required environment variables: {names}")
