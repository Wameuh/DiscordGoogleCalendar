"""Tests for the initial project foundation."""

from __future__ import annotations

import importlib.metadata
from datetime import time
from pathlib import Path
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from discordcalendarbot import __version__
from discordcalendarbot.app import RuntimeApplication, build_application
from discordcalendarbot.cli import build_parser, main
from discordcalendarbot.config import (
    BotSettings,
    EventFilterMode,
    SettingsValidationError,
    validate_required_environment,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def test_package_version_matches_project_metadata() -> None:
    """Package version should match the installed project metadata."""
    assert __version__ == "0.1.1"
    assert importlib.metadata.version("discordcalendarbot") == "0.1.1"


def test_default_cli_command_uses_runtime_handler() -> None:
    """The default CLI should be wired to the runtime handler."""
    args = build_parser().parse_args([])

    assert args.handler.__name__ == "handle_run"


def test_default_cli_command_starts_runtime_application(monkeypatch: MonkeyPatch) -> None:
    """The default CLI should load settings and run the long-lived application."""
    loaded_settings = object()
    calls: list[object] = []

    class FakeRuntimeApplication:
        async def run(self) -> None:
            calls.append("run")

    def fake_build_application(settings: object) -> FakeRuntimeApplication:
        calls.append(settings)
        return FakeRuntimeApplication()

    monkeypatch.setattr("discordcalendarbot.cli.load_operator_settings", lambda: loaded_settings)
    monkeypatch.setattr("discordcalendarbot.cli.build_application", fake_build_application)

    assert main([]) == 0
    assert calls == [loaded_settings, "run"]


def test_build_application_returns_runtime_when_settings_are_supplied(tmp_path: Path) -> None:
    """Composition root should build the runtime app from validated settings."""
    settings = BotSettings(
        discord_bot_token=f"token-{tmp_path.name}",
        discord_guild_id=123,
        discord_channel_id=456,
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        google_calendar_ids=("primary",),
        event_filter_mode=EventFilterMode.TAGGED,
        event_tag="#discord-daily",
        bot_timezone_name="Europe/Kiev",
        bot_timezone=ZoneInfo("Europe/Kiev"),
        daily_digest_time=time(hour=7),
        sqlite_path=tmp_path / "discordcalendarbot.sqlite3",
    )

    application = build_application(settings)

    assert isinstance(application, RuntimeApplication)
    assert application.settings is settings


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
