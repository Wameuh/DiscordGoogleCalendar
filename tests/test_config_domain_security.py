"""Tests for configuration, domain, and security primitives."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from discordcalendarbot.config import (
    EventFilterMode,
    SettingsValidationError,
    is_path_relative_to,
    load_settings,
)
from discordcalendarbot.domain.digest import build_local_day_window, event_overlaps_window
from discordcalendarbot.domain.events import CalendarEvent, EventTime
from discordcalendarbot.security.filesystem_permissions import (
    WindowsAce,
    check_unix_secret_mode,
    check_windows_secret_acl,
)
from discordcalendarbot.security.log_sanitizer import LogSanitizer

EXPECTED_GUILD_ID = 123
EXPECTED_CHANNEL_ID = 456
EXPECTED_DIGEST_HOUR = 7
EXPECTED_MESSAGE_LIMIT = 1_900


def valid_environment() -> dict[str, str]:
    """Return a complete valid settings environment."""
    return {
        "DISCORD_BOT_TOKEN": "token",
        "DISCORD_GUILD_ID": "123",
        "DISCORD_CHANNEL_ID": "456",
        "GOOGLE_CREDENTIALS_PATH": "credentials.json",
        "GOOGLE_TOKEN_PATH": "token.json",
        "GOOGLE_CALENDAR_IDS": "primary,team@example.com",
        "EVENT_TAG": "#discord-daily",
        "BOT_TIMEZONE": "Europe/Kiev",
        "DAILY_DIGEST_TIME": "07:00",
        "SQLITE_PATH": "data/discordcalendarbot.sqlite3",
    }


def ignored_path(_path: Path) -> bool:
    """Treat configured paths as ignored for focused settings tests."""
    return True


def test_load_settings_accepts_valid_environment(tmp_path: Path) -> None:
    """Settings should parse valid required and optional values."""
    settings = load_settings(
        valid_environment(),
        project_root=tmp_path,
        ignore_checker=ignored_path,
    )

    assert settings.discord_guild_id == EXPECTED_GUILD_ID
    assert settings.discord_channel_id == EXPECTED_CHANNEL_ID
    assert settings.google_calendar_ids == ("primary", "team@example.com")
    assert settings.event_filter_mode == EventFilterMode.TAGGED
    assert settings.bot_timezone_name == "Europe/Kiev"
    assert settings.daily_digest_time.hour == EXPECTED_DIGEST_HOUR
    assert settings.max_discord_message_chars == EXPECTED_MESSAGE_LIMIT


@pytest.mark.parametrize(
    ("key", "value", "expected"),
    [
        ("BOT_TIMEZONE", "Mars/Base", "Invalid timezone"),
        ("DAILY_DIGEST_TIME", "7am", "DAILY_DIGEST_TIME must use HH:MM format"),
        ("MAX_DISCORD_MESSAGE_CHARS", "2001", "MAX_DISCORD_MESSAGE_CHARS"),
        ("EVENT_TAG_FIELDS", "summary,attendees", "EVENT_TAG_FIELDS"),
        ("EVENT_FILTER_MODE", "private", "EVENT_FILTER_MODE"),
    ],
)
def test_load_settings_rejects_invalid_values(
    tmp_path: Path,
    key: str,
    value: str,
    expected: str,
) -> None:
    """Settings should reject invalid timezones, times, limits, and fields."""
    environment = valid_environment()
    environment[key] = value

    with pytest.raises(SettingsValidationError, match=expected):
        load_settings(environment, project_root=tmp_path, ignore_checker=ignored_path)


def test_load_settings_rejects_role_mentions_without_role_id(tmp_path: Path) -> None:
    """Role mentions should require an explicit configured role ID."""
    environment = valid_environment()
    environment["ENABLE_ROLE_MENTION"] = "true"

    with pytest.raises(SettingsValidationError, match="DISCORD_ROLE_MENTION_ID"):
        load_settings(environment, project_root=tmp_path, ignore_checker=ignored_path)


def test_load_settings_all_filter_mode_allows_missing_event_tag(tmp_path: Path) -> None:
    """All-events filter mode should not require the visible event tag."""
    environment = valid_environment()
    environment["EVENT_FILTER_MODE"] = "all"
    environment.pop("EVENT_TAG")

    settings = load_settings(environment, project_root=tmp_path, ignore_checker=ignored_path)

    assert settings.event_filter_mode == EventFilterMode.ALL
    assert settings.event_tag is None


def test_load_settings_tagged_filter_mode_requires_event_tag(tmp_path: Path) -> None:
    """Tagged filter mode should require an explicit visible event tag."""
    environment = valid_environment()
    environment["EVENT_FILTER_MODE"] = "tagged"
    environment["EVENT_TAG"] = " "

    with pytest.raises(SettingsValidationError, match="EVENT_TAG is required"):
        load_settings(environment, project_root=tmp_path, ignore_checker=ignored_path)


def test_load_settings_rejects_unignored_secret_paths_inside_project(tmp_path: Path) -> None:
    """Secret and state paths inside the project must be ignored by git."""
    with pytest.raises(SettingsValidationError, match="GOOGLE_CREDENTIALS_PATH"):
        load_settings(
            valid_environment(),
            project_root=tmp_path,
            ignore_checker=lambda _path: False,
        )


def test_path_containment_can_compare_windows_paths_case_insensitively(tmp_path: Path) -> None:
    """Path containment should support case-insensitive comparison for Windows semantics."""
    parent = tmp_path / "Project"
    child = parent / "Data" / "token.json"
    parent.mkdir()

    assert is_path_relative_to(child, parent, case_sensitive=False)


def test_local_day_window_uses_configured_timezone_on_dst_day() -> None:
    """Local day windows should stay timezone-aware on DST transition days."""
    timezone = ZoneInfo("Europe/Kiev")
    window = build_local_day_window(date(2026, 3, 29), timezone)

    assert window.start.tzinfo == timezone
    assert window.end.tzinfo == timezone
    assert window.end.date() == date(2026, 3, 30)


def test_event_overlap_includes_crossing_midnight_event() -> None:
    """Events that cross midnight should overlap the target local day."""
    timezone = ZoneInfo("Europe/Kiev")
    window = build_local_day_window(date(2026, 5, 2), timezone)
    event = CalendarEvent(
        calendar_id="primary",
        event_id="event-1",
        title="Night shift",
        time=EventTime(
            start=datetime(2026, 5, 1, 23, 30, tzinfo=timezone),
            end=datetime(2026, 5, 2, 1, 0, tzinfo=timezone),
        ),
    )

    assert event_overlaps_window(event, window)


def test_event_overlap_excludes_event_after_window() -> None:
    """Events after the target day should not overlap the digest window."""
    timezone = ZoneInfo("Europe/Kiev")
    window = build_local_day_window(date(2026, 5, 2), timezone)
    event = CalendarEvent(
        calendar_id="primary",
        event_id="event-2",
        title="Tomorrow",
        time=EventTime(
            start=window.end + timedelta(hours=1),
            end=window.end + timedelta(hours=2),
        ),
    )

    assert not event_overlaps_window(event, window)


def test_unix_secret_mode_flags_group_or_world_readable_file(tmp_path: Path) -> None:
    """Unix-like secret files should not be group or world readable."""
    stat_mode_with_file_type_bits = 0o100644

    findings = check_unix_secret_mode(
        tmp_path / "token.json",
        stat_mode_with_file_type_bits,
        is_directory=False,
    )

    assert findings
    assert "broader than 0600" in findings[0].message


def test_windows_acl_flags_broad_read_principals(tmp_path: Path) -> None:
    """Windows ACL checks should flag broad read principals through adapters."""
    findings = check_windows_secret_acl(
        tmp_path / "token.json",
        (
            WindowsAce(principal="users", rights=frozenset({"Read"})),
            WindowsAce(principal="CurrentUser", rights=frozenset({"FullControl"})),
        ),
    )

    assert findings
    assert "users" in findings[0].message


def test_log_sanitizer_redacts_tokens_urls_and_secret_paths(tmp_path: Path) -> None:
    """Log sanitizer should redact token-like strings, URL queries, and secret paths."""
    secret_path = tmp_path / "token.json"
    sanitizer = LogSanitizer(secret_paths=(secret_path,), max_length=500)

    sanitized = sanitizer.sanitize(
        f"Bearer abc.def.ghi at https://example.com/path?token=secret in {secret_path}"
    )

    assert "Bearer abc.def.ghi" not in sanitized
    assert "token=secret" not in sanitized
    assert str(secret_path) not in sanitized
    assert "[REDACTED_PATH]" in sanitized


def test_log_sanitizer_redacts_oauth_token_keys() -> None:
    """OAuth access and refresh token values should be redacted by key name."""
    sanitizer = LogSanitizer(max_length=500)

    sanitized = sanitizer.sanitize(
        "refresh_token=refresh-secret access_token='access-secret' "
        "id_token: id-secret token=generic-secret"
    )

    assert "refresh-secret" not in sanitized
    assert "access-secret" not in sanitized
    assert "id-secret" not in sanitized
    assert "generic-secret" not in sanitized
