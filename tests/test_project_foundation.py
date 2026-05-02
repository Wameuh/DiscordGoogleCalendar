"""Tests for the initial project foundation."""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

from discordcalendarbot import __version__
from discordcalendarbot.cli import main
from discordcalendarbot.config import SettingsValidationError, validate_required_environment


def test_package_version_matches_project_metadata() -> None:
    """Package version should match the installed project metadata."""
    assert __version__ == "0.1.1"
    assert importlib.metadata.version("discordcalendarbot") == "0.1.1"


def test_default_cli_command_exits_successfully() -> None:
    """The default CLI should be wired and return success."""
    assert main([]) == 0


def test_gitignore_contains_secret_and_state_patterns() -> None:
    """Local secret and state files should be ignored by git."""
    gitignore_lines = {
        line.strip()
        for line in Path(".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    expected_patterns = {
        ".env",
        ".env.*",
        "credentials.json",
        "token.json",
        "*.sqlite3",
        "*.sqlite3-*",
        "data/",
        ".state/",
    }

    assert expected_patterns <= gitignore_lines


def test_required_environment_validation_rejects_missing_values() -> None:
    """Initial config validation should reject missing required settings."""
    try:
        validate_required_environment({})
    except SettingsValidationError as error:
        message = str(error)
    else:
        message = ""

    assert "DISCORD_BOT_TOKEN" in message
    assert "SQLITE_PATH" in message


def test_required_environment_validation_accepts_present_values() -> None:
    """Initial config validation should accept non-blank required settings."""
    environment = {
        "DISCORD_BOT_TOKEN": "token",
        "DISCORD_GUILD_ID": "123",
        "DISCORD_CHANNEL_ID": "456",
        "GOOGLE_CREDENTIALS_PATH": "credentials.json",
        "GOOGLE_TOKEN_PATH": "token.json",
        "GOOGLE_CALENDAR_IDS": "primary",
        "EVENT_TAG": "#discord-daily",
        "BOT_TIMEZONE": "Europe/Kiev",
        "DAILY_DIGEST_TIME": "07:00",
        "SQLITE_PATH": "data/discordcalendarbot.sqlite3",
    }

    validate_required_environment(environment)
