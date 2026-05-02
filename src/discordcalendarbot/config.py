"""Typed environment-backed configuration."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import time
from enum import StrEnum
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REQUIRED_ENVIRONMENT_VARIABLES: tuple[str, ...] = (
    "DISCORD_BOT_TOKEN",
    "DISCORD_GUILD_ID",
    "DISCORD_CHANNEL_ID",
    "GOOGLE_CREDENTIALS_PATH",
    "GOOGLE_TOKEN_PATH",
    "GOOGLE_CALENDAR_IDS",
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


GitIgnoreChecker = Callable[[Path], bool]

VALID_TAG_FIELDS: frozenset[str] = frozenset({"summary", "description", "location"})
DISCORD_MAX_MESSAGE_CHARS = 2_000
EXPECTED_TIME_PARTS = 2


class EventFilterMode(StrEnum):
    """Supported calendar event filtering modes."""

    TAGGED = "tagged"
    ALL = "all"


@dataclass(frozen=True)
class BotSettings:
    """Validated runtime settings for the Discord Calendar Bot."""

    discord_bot_token: str
    discord_guild_id: int
    discord_channel_id: int
    google_credentials_path: Path
    google_token_path: Path
    google_calendar_ids: tuple[str, ...]
    event_filter_mode: EventFilterMode
    event_tag: str | None
    bot_timezone_name: str
    bot_timezone: ZoneInfo
    daily_digest_time: time
    sqlite_path: Path
    event_tag_fields: tuple[str, ...] = ("summary", "description")
    post_empty_digest: bool = False
    empty_digest_text: str = "No tagged events today."
    enable_role_mention: bool = False
    discord_role_mention_id: int | None = None
    catch_up_cutoff_time: time = time(hour=10)
    google_request_timeout_seconds: int = 20
    discord_publish_timeout_seconds: int = 20
    max_discord_message_chars: int = 1_900
    scheduler_misfire_grace_seconds: int = 900
    run_lock_ttl_seconds: int = 900
    log_level: str = "INFO"


@dataclass(frozen=True)
class DiscordCheckSettings:
    """Validated Discord-only settings for connectivity checks."""

    discord_bot_token: str
    discord_guild_id: int
    discord_channel_id: int
    discord_publish_timeout_seconds: int = 20
    enable_role_mention: bool = False
    discord_role_mention_id: int | None = None


def load_settings(
    environment: Mapping[str, str],
    *,
    project_root: Path | None = None,
    ignore_checker: GitIgnoreChecker | None = None,
) -> BotSettings:
    """Load and validate settings from environment-style values."""
    validate_required_environment(environment)
    root = (project_root or Path.cwd()).resolve()
    checker = ignore_checker or GitIgnoreCheckerForRoot(root)

    timezone_name = environment["BOT_TIMEZONE"].strip()
    timezone = parse_timezone(timezone_name)
    event_filter_mode = parse_event_filter_mode(environment.get("EVENT_FILTER_MODE", "tagged"))
    event_tag = parse_event_tag(environment, event_filter_mode)
    role_enabled = parse_bool(environment.get("ENABLE_ROLE_MENTION", "false"))
    role_id = parse_optional_int(environment.get("DISCORD_ROLE_MENTION_ID"))
    if role_enabled and role_id is None:
        raise SettingsValidationError(
            "DISCORD_ROLE_MENTION_ID is required when ENABLE_ROLE_MENTION=true"
        )

    return BotSettings(
        discord_bot_token=require_non_blank(environment, "DISCORD_BOT_TOKEN"),
        discord_guild_id=parse_positive_int(environment["DISCORD_GUILD_ID"], "DISCORD_GUILD_ID"),
        discord_channel_id=parse_positive_int(
            environment["DISCORD_CHANNEL_ID"],
            "DISCORD_CHANNEL_ID",
        ),
        google_credentials_path=resolve_configured_path(
            environment["GOOGLE_CREDENTIALS_PATH"],
            project_root=root,
            ignore_checker=checker,
            setting_name="GOOGLE_CREDENTIALS_PATH",
        ),
        google_token_path=resolve_configured_path(
            environment["GOOGLE_TOKEN_PATH"],
            project_root=root,
            ignore_checker=checker,
            setting_name="GOOGLE_TOKEN_PATH",
        ),
        google_calendar_ids=parse_csv(environment["GOOGLE_CALENDAR_IDS"], "GOOGLE_CALENDAR_IDS"),
        event_filter_mode=event_filter_mode,
        event_tag=event_tag,
        bot_timezone_name=timezone_name,
        bot_timezone=timezone,
        daily_digest_time=parse_hhmm(environment["DAILY_DIGEST_TIME"], "DAILY_DIGEST_TIME"),
        sqlite_path=resolve_configured_path(
            environment["SQLITE_PATH"],
            project_root=root,
            ignore_checker=checker,
            setting_name="SQLITE_PATH",
        ),
        event_tag_fields=parse_tag_fields(
            environment.get("EVENT_TAG_FIELDS", "summary,description")
        ),
        post_empty_digest=parse_bool(environment.get("POST_EMPTY_DIGEST", "false")),
        empty_digest_text=environment.get("EMPTY_DIGEST_TEXT", "No tagged events today.").strip(),
        enable_role_mention=role_enabled,
        discord_role_mention_id=role_id,
        catch_up_cutoff_time=parse_hhmm(
            environment.get("CATCH_UP_CUTOFF_TIME", "10:00"),
            "CATCH_UP_CUTOFF_TIME",
        ),
        google_request_timeout_seconds=parse_int_in_range(
            environment.get("GOOGLE_REQUEST_TIMEOUT_SECONDS", "20"),
            "GOOGLE_REQUEST_TIMEOUT_SECONDS",
            minimum=1,
            maximum=120,
        ),
        discord_publish_timeout_seconds=parse_int_in_range(
            environment.get("DISCORD_PUBLISH_TIMEOUT_SECONDS", "20"),
            "DISCORD_PUBLISH_TIMEOUT_SECONDS",
            minimum=1,
            maximum=120,
        ),
        max_discord_message_chars=parse_int_in_range(
            environment.get("MAX_DISCORD_MESSAGE_CHARS", "1900"),
            "MAX_DISCORD_MESSAGE_CHARS",
            minimum=1,
            maximum=DISCORD_MAX_MESSAGE_CHARS,
        ),
        scheduler_misfire_grace_seconds=parse_int_in_range(
            environment.get("SCHEDULER_MISFIRE_GRACE_SECONDS", "900"),
            "SCHEDULER_MISFIRE_GRACE_SECONDS",
            minimum=1,
            maximum=86_400,
        ),
        run_lock_ttl_seconds=parse_int_in_range(
            environment.get("RUN_LOCK_TTL_SECONDS", "900"),
            "RUN_LOCK_TTL_SECONDS",
            minimum=60,
            maximum=86_400,
        ),
        log_level=environment.get("LOG_LEVEL", "INFO").strip().upper(),
    )


def load_discord_check_settings(environment: Mapping[str, str]) -> DiscordCheckSettings:
    """Load and validate only the Discord settings needed for target checks."""
    missing = tuple(
        variable
        for variable in ("DISCORD_BOT_TOKEN", "DISCORD_GUILD_ID", "DISCORD_CHANNEL_ID")
        if not environment.get(variable, "").strip()
    )
    if missing:
        names = ", ".join(missing)
        raise SettingsValidationError(f"Missing required Discord environment variables: {names}")
    role_enabled = parse_bool(environment.get("ENABLE_ROLE_MENTION", "false"))
    role_id = parse_optional_int(environment.get("DISCORD_ROLE_MENTION_ID"))
    if role_enabled and role_id is None:
        raise SettingsValidationError(
            "DISCORD_ROLE_MENTION_ID is required when ENABLE_ROLE_MENTION=true"
        )
    return DiscordCheckSettings(
        discord_bot_token=require_non_blank(environment, "DISCORD_BOT_TOKEN"),
        discord_guild_id=parse_positive_int(environment["DISCORD_GUILD_ID"], "DISCORD_GUILD_ID"),
        discord_channel_id=parse_positive_int(
            environment["DISCORD_CHANNEL_ID"],
            "DISCORD_CHANNEL_ID",
        ),
        discord_publish_timeout_seconds=parse_int_in_range(
            environment.get("DISCORD_PUBLISH_TIMEOUT_SECONDS", "20"),
            "DISCORD_PUBLISH_TIMEOUT_SECONDS",
            minimum=1,
            maximum=120,
        ),
        enable_role_mention=role_enabled,
        discord_role_mention_id=role_id,
    )


class GitIgnoreCheckerForRoot:
    """Check whether paths are ignored by git for a project root."""

    def __init__(self, project_root: Path) -> None:
        """Store the project root used for git ignore checks."""
        self._project_root = project_root

    def __call__(self, path: Path) -> bool:
        """Return whether git reports the path as ignored."""
        git_executable = shutil.which("git")
        if git_executable is None:
            return False
        completed = subprocess.run(  # noqa: S603
            [git_executable, "check-ignore", "--quiet", str(path)],
            cwd=self._project_root,
            check=False,
            shell=False,
        )
        return completed.returncode == 0


def require_non_blank(environment: Mapping[str, str], variable: str) -> str:
    """Return a stripped non-blank environment value."""
    value = environment.get(variable, "").strip()
    if not value:
        raise SettingsValidationError(f"{variable} must not be blank")
    return value


def parse_positive_int(value: str, setting_name: str) -> int:
    """Parse a positive integer setting."""
    parsed = parse_int_in_range(value, setting_name, minimum=1, maximum=2**63 - 1)
    return parsed


def parse_optional_int(value: str | None) -> int | None:
    """Parse an optional positive integer setting."""
    if value is None or not value.strip():
        return None
    return parse_positive_int(value, "DISCORD_ROLE_MENTION_ID")


def parse_int_in_range(value: str, setting_name: str, *, minimum: int, maximum: int) -> int:
    """Parse an integer setting and enforce inclusive bounds."""
    try:
        parsed = int(value)
    except ValueError as error:
        raise SettingsValidationError(f"{setting_name} must be an integer") from error
    if parsed < minimum or parsed > maximum:
        raise SettingsValidationError(
            f"{setting_name} must be between {minimum} and {maximum}, got {parsed}"
        )
    return parsed


def parse_bool(value: str) -> bool:
    """Parse a strict boolean environment value."""
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SettingsValidationError(f"Expected a boolean value, got {value!r}")


def parse_csv(value: str, setting_name: str) -> tuple[str, ...]:
    """Parse a comma-separated setting into non-blank values."""
    parsed = tuple(item.strip() for item in value.split(",") if item.strip())
    if not parsed:
        raise SettingsValidationError(f"{setting_name} must contain at least one value")
    return parsed


def parse_tag_fields(value: str) -> tuple[str, ...]:
    """Parse and validate tag matching fields."""
    fields = parse_csv(value, "EVENT_TAG_FIELDS")
    invalid = sorted(set(fields) - VALID_TAG_FIELDS)
    if invalid:
        raise SettingsValidationError(f"EVENT_TAG_FIELDS contains unsupported fields: {invalid}")
    return fields


def parse_event_filter_mode(value: str) -> EventFilterMode:
    """Parse and validate the calendar event filter mode."""
    normalized = value.strip().lower()
    try:
        return EventFilterMode(normalized)
    except ValueError as error:
        supported = ", ".join(mode.value for mode in EventFilterMode)
        raise SettingsValidationError(f"EVENT_FILTER_MODE must be one of: {supported}") from error


def parse_event_tag(
    environment: Mapping[str, str],
    event_filter_mode: EventFilterMode,
) -> str | None:
    """Parse the event tag according to the selected filter mode."""
    value = environment.get("EVENT_TAG", "").strip()
    if event_filter_mode == EventFilterMode.TAGGED and not value:
        raise SettingsValidationError("EVENT_TAG is required when EVENT_FILTER_MODE=tagged")
    return value or None


def parse_hhmm(value: str, setting_name: str) -> time:
    """Parse a HH:MM wall-clock time."""
    parts = value.strip().split(":")
    if len(parts) != EXPECTED_TIME_PARTS:
        raise SettingsValidationError(f"{setting_name} must use HH:MM format")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
        return time(hour=hour, minute=minute)
    except ValueError as error:
        raise SettingsValidationError(f"{setting_name} must use HH:MM format") from error


def parse_timezone(value: str) -> ZoneInfo:
    """Parse a zoneinfo timezone name."""
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise SettingsValidationError(f"Invalid timezone: {value}") from error


def resolve_configured_path(
    value: str,
    *,
    project_root: Path,
    ignore_checker: GitIgnoreChecker,
    setting_name: str,
) -> Path:
    """Resolve and validate a configured filesystem path."""
    raw_path = Path(value.strip())
    if not raw_path:
        raise SettingsValidationError(f"{setting_name} must not be blank")
    resolved = (project_root / raw_path if not raw_path.is_absolute() else raw_path).resolve()
    if is_path_relative_to(resolved, project_root) and not ignore_checker(resolved):
        raise SettingsValidationError(
            f"{setting_name} points inside the project tree but is not ignored by git: {resolved}"
        )
    return resolved


def is_path_relative_to(path: Path, parent: Path, *, case_sensitive: bool | None = None) -> bool:
    """Return whether path is inside parent with platform-aware casing."""
    path_text = os.path.normcase(str(path.resolve()))
    parent_text = os.path.normcase(str(parent.resolve()))
    if case_sensitive is True:
        path_text = str(path.resolve())
        parent_text = str(parent.resolve())
    if case_sensitive is False:
        path_text = str(path.resolve()).lower()
        parent_text = str(parent.resolve()).lower()
    try:
        Path(path_text).relative_to(Path(parent_text))
    except ValueError:
        return False
    return True
