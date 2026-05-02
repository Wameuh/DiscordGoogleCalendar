"""Tests for local operator commands."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest

from discordcalendarbot.calendar.auth import (
    READONLY_CALENDAR_SCOPE,
    GoogleAuthError,
    OAuthTokenMetadata,
    run_oauth_login,
)
from discordcalendarbot.cli import build_parser, handle_check_discord
from discordcalendarbot.config import BotSettings, EventFilterMode
from discordcalendarbot.discord.bot import DiscordRuntimeError
from discordcalendarbot.discord.cli_publisher import DiscordCliPublisher, DiscordCliPublishError
from discordcalendarbot.discord.formatter import DiscordMessagePart
from discordcalendarbot.operator_commands import (
    DRY_RUN_FAILURE_EXIT_CODE,
    FORCE_NAMESPACE_PREFIX,
    DryRunPreview,
    FullDigestCheckResult,
    GoogleCalendarCheckResult,
    build_full_digest_check,
    check_google_calendar,
    daily_key_for_date,
    oauth_metadata_path,
    run_check_discord_command,
    run_check_full_digest_command,
    run_check_google_calendar_command,
    run_dry_run_command,
    run_google_auth_login_command,
    run_reconcile_digest_command,
    run_send_digest_command,
)
from discordcalendarbot.services.digest_service import DailyDigestResult, DigestServiceStatus
from discordcalendarbot.storage.repository import DigestRunStatus
from discordcalendarbot.storage.sqlite import SQLiteDigestRunRepository

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

GUILD_ID = 123_456
CHANNEL_ID = 234_567
EXPECTED_REFUSAL_EXIT = 2
EXPECTED_CHECK_EVENT_COUNT = 2
KYIV = ZoneInfo("Europe/Kiev")


class Buffer:
    """Small writable buffer for operator command output."""

    def __init__(self) -> None:
        """Initialize the buffer."""
        self.text = ""

    def write(self, text: str) -> int:
        """Append text and return its length like stdout."""
        self.text += text
        return len(text)


class FakeCredentials:
    """Fake OAuth credentials returned by the local browser flow."""

    def __init__(self) -> None:
        """Store fake granted scopes and account metadata."""
        self.scopes = [READONLY_CALENDAR_SCOPE]
        self.account_email = "operator@example.com"

    def to_json(self) -> str:
        """Return a fake authorized-user token JSON payload."""
        return '{"scopes": ["https://www.googleapis.com/auth/calendar.readonly"]}'


class FakeInstalledAppFlow:
    """Fake google-auth-oauthlib flow."""

    credentials_path: str | None = None
    scopes: list[str] | None = None

    @classmethod
    def from_client_secrets_file(
        cls,
        credentials_path: str,
        *,
        scopes: list[str],
    ) -> FakeInstalledAppFlow:
        """Capture OAuth flow construction."""
        cls.credentials_path = credentials_path
        cls.scopes = scopes
        return cls()

    def run_local_server(self, *, port: int) -> FakeCredentials:
        """Return fake credentials while proving a local server was requested."""
        assert port == 0
        return FakeCredentials()


class FakeSendService:
    """Fake digest service for send-digest command tests."""

    def __init__(self) -> None:
        """Initialize captured runs."""
        self.runs: list[tuple[date, str, str]] = []

    async def run_for_date(
        self,
        target_date: date,
        *,
        lock_owner: str = "scheduler",
        namespace: str = "daily",
    ) -> DailyDigestResult:
        """Capture the requested run and return a posted result."""
        self.runs.append((target_date, lock_owner, namespace))
        return DailyDigestResult(
            status=DigestServiceStatus.POSTED,
            run_key=namespace,
            target_date=target_date,
            event_count=1,
            message_ids=("111",),
        )


class FakeCheckCalendarClient:
    """Fake Google Calendar client for read-path check tests."""

    def __init__(self) -> None:
        """Initialize captured calls."""
        self.calls: list[tuple[str, str]] = []

    async def list_events_for_window(
        self,
        *,
        calendar_id: str,
        window: object,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        """Return tagged and untagged raw events per configured calendar."""
        _ = window
        self.calls.append((calendar_id, timezone_name))
        return [
            {
                "id": f"{calendar_id}-event",
                "summary": "Planning #discord-daily",
                "start": {"dateTime": "2026-05-02T08:00:00+03:00"},
                "end": {"dateTime": "2026-05-02T09:00:00+03:00"},
            },
            {
                "id": f"{calendar_id}-untagged-event",
                "summary": "Private planning",
                "start": {"dateTime": "2026-05-02T10:00:00+03:00"},
                "end": {"dateTime": "2026-05-02T11:00:00+03:00"},
            },
        ]


def make_dry_run_preview(
    *,
    status: DigestServiceStatus = DigestServiceStatus.POSTED,
    message_parts: tuple[DiscordMessagePart, ...] = (),
    failure_error: object | None = None,
    failure_kind: str | None = None,
) -> DryRunPreview:
    """Build a dry-run preview for operator command tests."""
    return DryRunPreview(
        result=DailyDigestResult(
            status=status,
            run_key="dry-run",
            target_date=date(2026, 5, 2),
            event_count=1 if message_parts else 0,
            reason=failure_kind,
        ),
        message_parts=message_parts,
        failure_error=failure_error,
        failure_kind=failure_kind,
    )


def make_settings(tmp_path: Path) -> BotSettings:
    """Build operator command test settings."""
    return BotSettings(
        discord_bot_token=f"token-{tmp_path.name}",
        discord_guild_id=GUILD_ID,
        discord_channel_id=CHANNEL_ID,
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        google_calendar_ids=("primary",),
        event_filter_mode=EventFilterMode.TAGGED,
        event_tag="#discord-daily",
        bot_timezone_name="Europe/Kiev",
        bot_timezone=KYIV,
        daily_digest_time=time(hour=7),
        sqlite_path=tmp_path / "discordcalendarbot.sqlite3",
    )


def test_parser_exposes_operator_subcommands() -> None:
    """CLI parser should expose the local operator commands."""
    parser = build_parser()

    assert parser.parse_args(["google-auth-login", "--confirm-write-token", "token.json"]).command
    dry_run = parser.parse_args(["dry-run", "--date", "2026-05-02", "--summary-only", "--redact"])
    send = parser.parse_args(
        [
            "send-digest",
            "--date",
            "2026-05-02",
            "--force",
            "--confirm-force",
            "2026-05-02",
            "--channel-id",
            str(CHANNEL_ID),
        ]
    )
    reconcile = parser.parse_args(
        [
            "reconcile-digest",
            "--date",
            "2026-05-02",
            "--message-id",
            "111",
            "--message-id",
            "222",
            "--partial",
            "--confirm-reconcile",
            "2026-05-02",
        ]
    )
    assert dry_run.command == "dry-run"
    assert dry_run.summary_only
    assert dry_run.redact
    check_google = parser.parse_args(["check-google-calendar", "--date", "2026-05-02"])
    assert check_google.command == "check-google-calendar"
    assert check_google.date == "2026-05-02"
    check_discord = parser.parse_args(["check-discord"])
    assert check_discord.command == "check-discord"
    check_full = parser.parse_args(["check-full-digest", "--date", "2026-05-02"])
    assert check_full.command == "check-full-digest"
    assert check_full.date == "2026-05-02"
    assert send.command == "send-digest"
    assert send.force
    assert send.confirm_force == "2026-05-02"
    assert send.channel_id == CHANNEL_ID
    assert reconcile.command == "reconcile-digest"
    assert reconcile.message_id == ["111", "222"]
    assert reconcile.partial
    assert reconcile.confirm_reconcile == "2026-05-02"


def test_run_oauth_login_writes_token_and_metadata(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """OAuth bootstrap should write the token and non-secret metadata sidecar."""
    token_path = tmp_path / "token.json"
    metadata_path = oauth_metadata_path(token_path)
    monkeypatch.setattr(
        "discordcalendarbot.calendar.auth.InstalledAppFlow",
        FakeInstalledAppFlow,
    )

    metadata = run_oauth_login(
        credentials_path=tmp_path / "credentials.json",
        token_path=token_path,
        metadata_path=metadata_path,
        now=datetime(2026, 5, 2, 7, tzinfo=timezone.utc),
    )

    assert token_path.exists()
    assert metadata_path.exists()
    assert metadata.account_email == "operator@example.com"
    assert FakeInstalledAppFlow.scopes == [READONLY_CALENDAR_SCOPE]


@pytest.mark.asyncio
async def test_google_auth_login_requires_confirmation(tmp_path: Path) -> None:
    """OAuth command should refuse writes without an explicit token filename confirmation."""
    settings = make_settings(tmp_path)
    output = Buffer()

    result = await run_google_auth_login_command(
        settings,
        force=False,
        confirm_write_token=None,
        output=output,
    )

    assert result.exit_code == EXPECTED_REFUSAL_EXIT
    assert "confirm-write-token" in result.message


@pytest.mark.asyncio
async def test_google_auth_login_prints_metadata(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """OAuth command should report safe metadata after writing tokens."""
    settings = make_settings(tmp_path)
    output = Buffer()

    def fake_login(**_kwargs: Any) -> OAuthTokenMetadata:
        """Return fake OAuth metadata."""
        return OAuthTokenMetadata(
            account_email="operator@example.com",
            granted_scopes=(READONLY_CALENDAR_SCOPE,),
            created_at=datetime(2026, 5, 2, 7, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("discordcalendarbot.operator_commands.run_oauth_login", fake_login)

    result = await run_google_auth_login_command(
        settings,
        force=False,
        confirm_write_token=settings.google_token_path.name,
        output=output,
    )

    assert result.exit_code == 0
    assert "operator@example.com" in output.text
    assert READONLY_CALENDAR_SCOPE in output.text


@pytest.mark.asyncio
async def test_dry_run_can_redact_message_content(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Dry-run should support safer redacted previews without writing state."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fake_render(
        _settings: BotSettings,
        *,
        target_date: date,
    ) -> DryRunPreview:
        """Return fake rendered message parts."""
        assert target_date == date(2026, 5, 2)
        return make_dry_run_preview(
            message_parts=(DiscordMessagePart(content="Header\n- Private event"),)
        )

    monkeypatch.setattr("discordcalendarbot.operator_commands.render_dry_run", fake_render)

    result = await run_dry_run_command(
        settings,
        target_date=date(2026, 5, 2),
        redact=True,
        summary_only=False,
        output=output,
    )

    assert result.exit_code == 0
    assert "Private event" not in output.text
    assert "[redacted event]" in output.text


@pytest.mark.asyncio
async def test_dry_run_summary_only_prints_counts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Dry-run summary mode should avoid printing rendered event content."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fake_render(
        _settings: BotSettings,
        *,
        target_date: date,
    ) -> DryRunPreview:
        """Return fake rendered message parts."""
        assert target_date == date(2026, 5, 2)
        return make_dry_run_preview(
            message_parts=(DiscordMessagePart(content="Header\n- Private event"),)
        )

    monkeypatch.setattr("discordcalendarbot.operator_commands.render_dry_run", fake_render)

    result = await run_dry_run_command(
        settings,
        target_date=date(2026, 5, 2),
        redact=False,
        summary_only=True,
        output=output,
    )

    assert result.exit_code == 0
    assert "1 Discord message part" in output.text
    assert "Private event" not in output.text
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_dry_run_summary_only_preserves_successful_empty_result(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Dry-run summary should keep zero message parts as success after a clean read."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fake_render(_settings: BotSettings, *, target_date: date) -> DryRunPreview:
        """Return a successful empty dry-run result."""
        assert target_date == date(2026, 5, 2)
        return make_dry_run_preview(
            status=DigestServiceStatus.SKIPPED_EMPTY,
            message_parts=(),
        )

    monkeypatch.setattr("discordcalendarbot.operator_commands.render_dry_run", fake_render)

    result = await run_dry_run_command(
        settings,
        target_date=date(2026, 5, 2),
        redact=False,
        summary_only=True,
        output=output,
    )

    assert result.exit_code == 0
    assert "0 Discord message part" in output.text
    assert "failed" not in output.text.lower()
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_dry_run_summary_only_reports_google_auth_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Dry-run summary mode should report auth failures instead of zero messages."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fail_render(_settings: BotSettings, *, target_date: date) -> DryRunPreview:
        """Raise before a service result exists, like credential loading can."""
        assert target_date == date(2026, 5, 2)
        raise GoogleAuthError("refresh_token=secret-value")

    monkeypatch.setattr("discordcalendarbot.operator_commands.render_dry_run", fail_render)

    result = await run_dry_run_command(
        settings,
        target_date=date(2026, 5, 2),
        redact=False,
        summary_only=True,
        output=output,
    )

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert "Google Calendar authentication failed" in output.text
    assert "0 Discord message part" not in output.text
    assert "secret-value" not in output.text


@pytest.mark.asyncio
async def test_dry_run_summary_only_reports_service_google_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Dry-run should report service failures captured by the dry-run repository."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fake_render(_settings: BotSettings, *, target_date: date) -> DryRunPreview:
        """Return a failed service result with safe diagnostics."""
        assert target_date == date(2026, 5, 2)
        return make_dry_run_preview(
            status=DigestServiceStatus.FAILED_NON_RETRYABLE,
            failure_kind="google_event_mapping",
        )

    monkeypatch.setattr("discordcalendarbot.operator_commands.render_dry_run", fake_render)

    result = await run_dry_run_command(
        settings,
        target_date=date(2026, 5, 2),
        redact=False,
        summary_only=True,
        output=output,
    )

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert "could not be normalized" in output.text
    assert "0 Discord message part" not in output.text


@pytest.mark.asyncio
async def test_check_google_calendar_reports_safe_counters(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Google check command should print counters without event details."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fake_check(_settings: BotSettings, *, target_date: date) -> GoogleCalendarCheckResult:
        """Return safe fake check counters."""
        assert target_date == date(2026, 5, 2)
        return GoogleCalendarCheckResult(
            calendar_count=2,
            raw_event_count=3,
            normalized_event_count=2,
            digest_event_count=1,
        )

    monkeypatch.setattr("discordcalendarbot.operator_commands.check_google_calendar", fake_check)

    result = await run_check_google_calendar_command(
        settings,
        target_date=date(2026, 5, 2),
        output=output,
    )

    assert result.exit_code == 0
    assert "Calendars checked: 2" in output.text
    assert "Raw events returned: 3" in output.text
    assert "Digest filter matches: 1" in output.text
    assert "#discord-daily" not in output.text
    assert "Planning" not in output.text
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_check_google_calendar_reports_safe_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Google check command should return non-zero with sanitized failures."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fail_check(_settings: BotSettings, *, target_date: date) -> GoogleCalendarCheckResult:
        """Raise a secret-bearing auth error."""
        assert target_date == date(2026, 5, 2)
        raise GoogleAuthError("refresh_token=secret-value")

    monkeypatch.setattr("discordcalendarbot.operator_commands.check_google_calendar", fail_check)

    result = await run_check_google_calendar_command(
        settings,
        target_date=date(2026, 5, 2),
        output=output,
    )

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert "Google Calendar authentication failed" in output.text
    assert "secret-value" not in output.text


@pytest.mark.asyncio
async def test_check_google_calendar_uses_window_mapping_and_filter(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Google check should use the calendar client, mapper, and configured filter."""
    settings = make_settings(tmp_path)
    fake_client = FakeCheckCalendarClient()

    async def fake_build_calendar_client(_settings: BotSettings) -> FakeCheckCalendarClient:
        """Return the fake check calendar client."""
        return fake_client

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_calendar_client",
        fake_build_calendar_client,
    )

    result = await check_google_calendar(settings, target_date=date(2026, 5, 2))

    assert result.calendar_count == 1
    assert result.raw_event_count == EXPECTED_CHECK_EVENT_COUNT
    assert result.normalized_event_count == EXPECTED_CHECK_EVENT_COUNT
    assert result.digest_event_count == 1
    assert fake_client.calls == [("primary", "Europe/Kiev")]
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_check_discord_reports_success_without_posting(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Discord check command should report validated target permissions."""
    settings = make_settings(tmp_path)
    output = Buffer()
    calls = 0

    async def fake_check_discord_target(_settings: BotSettings) -> object:
        """Capture Discord target validation without sending messages."""
        nonlocal calls
        calls += 1
        return object()

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.check_discord_target",
        fake_check_discord_target,
    )

    result = await run_check_discord_command(settings, output=output)

    assert result.exit_code == 0
    assert calls == 1
    assert "Discord check: ok" in output.text
    assert "Send Messages permission: yes" in output.text
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_check_discord_reports_safe_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Discord check command should report validation failures without secrets."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fail_check_discord_target(_settings: BotSettings) -> object:
        """Raise a Discord target validation error."""
        raise DiscordRuntimeError("Bot cannot send messages to the configured Discord channel")

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.check_discord_target",
        fail_check_discord_target,
    )

    result = await run_check_discord_command(settings, output=output)

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert "cannot send messages" in output.text
    assert settings.discord_bot_token not in output.text


@pytest.mark.asyncio
async def test_check_discord_failure_redacts_configured_ids(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Discord check command should not echo configured guild or channel IDs."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fail_check_discord_target(_settings: BotSettings) -> object:
        """Raise an error that includes raw configured identifiers."""
        raise DiscordRuntimeError(
            f"Configured Discord channel not found: {settings.discord_channel_id}"
        )

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.check_discord_target",
        fail_check_discord_target,
    )

    result = await run_check_discord_command(settings, output=output)

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert str(settings.discord_channel_id) not in output.text
    assert str(settings.discord_guild_id) not in output.text
    assert settings.discord_bot_token not in output.text


def test_check_discord_handler_uses_discord_only_settings(monkeypatch: MonkeyPatch) -> None:
    """CLI handler should avoid full settings loading for Discord-only checks."""
    discord_settings = object()
    calls: list[object] = []

    async def fake_run_check_discord_command(settings: object, *, output: object) -> object:
        """Record the Discord check command call."""
        _ = output
        calls.append(settings)
        return type("Result", (), {"exit_code": 0})()

    def load_discord_settings() -> object:
        """Return Discord-only settings for the handler."""
        return discord_settings

    def fail_full_settings_loader() -> object:
        """Fail if the handler accidentally loads full Google-backed settings."""
        raise AssertionError("load_operator_settings should not be called")

    monkeypatch.setattr("discordcalendarbot.cli.load_operator_settings", fail_full_settings_loader)
    monkeypatch.setattr(
        "discordcalendarbot.cli.load_discord_operator_settings", load_discord_settings
    )
    monkeypatch.setattr(
        "discordcalendarbot.cli.run_check_discord_command",
        fake_run_check_discord_command,
    )

    assert handle_check_discord(object()) == 0
    assert calls == [discord_settings]


@pytest.mark.asyncio
async def test_build_full_digest_check_reads_filters_and_formats_without_state(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Full digest check should read, filter, and format without SQLite or Discord publishing."""
    settings = make_settings(tmp_path)
    fake_client = FakeCheckCalendarClient()

    async def fake_build_calendar_client(_settings: BotSettings) -> FakeCheckCalendarClient:
        """Return the fake check calendar client."""
        return fake_client

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_calendar_client",
        fake_build_calendar_client,
    )

    result = await build_full_digest_check(settings, target_date=date(2026, 5, 2))

    assert result.calendar_count == 1
    assert result.raw_event_count == EXPECTED_CHECK_EVENT_COUNT
    assert result.normalized_event_count == EXPECTED_CHECK_EVENT_COUNT
    assert result.digest_event_count == 1
    assert result.message_part_count == 1
    assert result.should_post
    assert fake_client.calls == [("primary", "Europe/Kiev")]
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_check_full_digest_reports_safe_counters_and_permissions(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Full digest command should print only safe counters and permission confirmations."""
    settings = make_settings(tmp_path)
    output = Buffer()
    discord_checks = 0

    async def fake_build_full_digest_check(
        _settings: BotSettings,
        *,
        target_date: date,
    ) -> FullDigestCheckResult:
        """Return safe fake full digest counters."""
        assert target_date == date(2026, 5, 2)
        return FullDigestCheckResult(
            calendar_count=2,
            raw_event_count=3,
            normalized_event_count=2,
            digest_event_count=1,
            message_part_count=1,
            should_post=True,
        )

    async def fake_check_discord_target(_settings: object) -> object:
        """Record Discord validation without sending messages."""
        nonlocal discord_checks
        discord_checks += 1
        return object()

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_full_digest_check",
        fake_build_full_digest_check,
    )
    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.check_discord_target",
        fake_check_discord_target,
    )

    result = await run_check_full_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        output=output,
    )

    assert result.exit_code == 0
    assert discord_checks == 1
    assert "Full digest check for 2026-05-02: ok" in output.text
    assert "Raw events returned: 3" in output.text
    assert "Discord message parts formatted: 1" in output.text
    assert "Send Messages permission: yes" in output.text
    assert "Planning" not in output.text
    assert "#discord-daily" not in output.text
    assert "primary" not in output.text
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_check_full_digest_reports_safe_discord_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Full digest command should not echo configured IDs from Discord failures."""
    settings = make_settings(tmp_path)
    output = Buffer()

    async def fake_build_full_digest_check(
        _settings: BotSettings,
        *,
        target_date: date,
    ) -> FullDigestCheckResult:
        """Return safe fake full digest counters."""
        assert target_date == date(2026, 5, 2)
        return FullDigestCheckResult(
            calendar_count=1,
            raw_event_count=1,
            normalized_event_count=1,
            digest_event_count=1,
            message_part_count=1,
            should_post=True,
        )

    async def fail_check_discord_target(_settings: object) -> object:
        """Raise an error that includes raw configured identifiers."""
        raise DiscordRuntimeError(
            f"Configured Discord channel not found: {settings.discord_channel_id}"
        )

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_full_digest_check",
        fake_build_full_digest_check,
    )
    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.check_discord_target",
        fail_check_discord_target,
    )

    result = await run_check_full_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        output=output,
    )

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert "Discord channel could not be resolved" in output.text
    assert str(settings.discord_channel_id) not in output.text
    assert str(settings.discord_guild_id) not in output.text
    assert settings.discord_bot_token not in output.text


@pytest.mark.asyncio
async def test_check_full_digest_stops_before_discord_after_google_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Full digest command should not validate Discord after Google/read failures."""
    settings = make_settings(tmp_path)
    output = Buffer()
    discord_checks = 0

    async def fail_build_full_digest_check(
        _settings: BotSettings,
        *,
        target_date: date,
    ) -> FullDigestCheckResult:
        """Raise a secret-bearing Google auth error before Discord validation."""
        assert target_date == date(2026, 5, 2)
        raise GoogleAuthError("private diagnostic value")

    async def fake_check_discord_target(_settings: object) -> object:
        """Record unexpected Discord validation."""
        nonlocal discord_checks
        discord_checks += 1
        return object()

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_full_digest_check",
        fail_build_full_digest_check,
    )
    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.check_discord_target",
        fake_check_discord_target,
    )

    result = await run_check_full_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        output=output,
    )

    assert result.exit_code == DRY_RUN_FAILURE_EXIT_CODE
    assert discord_checks == 0
    assert "Google Calendar authentication failed" in output.text
    assert "private diagnostic value" not in output.text
    assert settings.discord_bot_token not in output.text
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_send_digest_non_force_uses_daily_namespace(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Non-force sends should reuse the normal daily idempotency namespace."""
    settings = make_settings(tmp_path)
    output = Buffer()
    fake_service = FakeSendService()

    async def fake_build_service(_settings: BotSettings) -> FakeSendService:
        """Return a fake service."""
        return fake_service

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_operator_digest_service",
        fake_build_service,
    )

    result = await run_send_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        force=False,
        channel_id=None,
        confirm_force=None,
        output=output,
    )

    assert result.exit_code == 0
    assert fake_service.runs == [(date(2026, 5, 2), "operator-send", "daily")]


@pytest.mark.asyncio
async def test_send_digest_force_requires_date_confirmation(tmp_path: Path) -> None:
    """Forced sends should refuse to run without exact date confirmation."""
    settings = make_settings(tmp_path)
    output = Buffer()

    result = await run_send_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        force=True,
        channel_id=CHANNEL_ID,
        confirm_force=None,
        output=output,
    )

    assert result.exit_code == EXPECTED_REFUSAL_EXIT
    assert "confirm-force" in result.message


@pytest.mark.asyncio
async def test_send_digest_force_requires_channel_confirmation(tmp_path: Path) -> None:
    """Forced sends should require naming the configured channel ID."""
    settings = make_settings(tmp_path)
    output = Buffer()

    result = await run_send_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        force=True,
        channel_id=None,
        confirm_force="2026-05-02",
        output=output,
    )

    assert result.exit_code == EXPECTED_REFUSAL_EXIT
    assert "channel-id" in result.message


@pytest.mark.asyncio
async def test_send_digest_force_uses_separate_namespace(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Forced sends should use a separate idempotency namespace from daily runs."""
    settings = make_settings(tmp_path)
    output = Buffer()
    fake_service = FakeSendService()

    async def fake_build_service(_settings: BotSettings) -> FakeSendService:
        """Return a fake service."""
        return fake_service

    async def fake_render(
        _settings: BotSettings,
        *,
        target_date: date,
    ) -> DryRunPreview:
        """Return fake preview content."""
        assert target_date == date(2026, 5, 2)
        return make_dry_run_preview(message_parts=(DiscordMessagePart(content="preview"),))

    monkeypatch.setattr(
        "discordcalendarbot.operator_commands.build_operator_digest_service",
        fake_build_service,
    )
    monkeypatch.setattr("discordcalendarbot.operator_commands.render_dry_run", fake_render)

    result = await run_send_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        force=True,
        channel_id=CHANNEL_ID,
        confirm_force="2026-05-02",
        output=output,
    )

    assert result.exit_code == 0
    assert fake_service.runs[0][1] == "operator-force"
    assert fake_service.runs[0][2].startswith(f"{FORCE_NAMESPACE_PREFIX}-2026-05-02-")
    assert "Force preview" in output.text


@pytest.mark.asyncio
async def test_reconcile_digest_marks_run_posted_without_google_fetch(tmp_path: Path) -> None:
    """Reconciliation should record known message IDs in SQLite only."""
    settings = make_settings(tmp_path)
    output = Buffer()

    result = await run_reconcile_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        message_ids=("111", "222"),
        partial=False,
        confirm_reconcile="2026-05-02",
        output=output,
    )
    repository = SQLiteDigestRunRepository(settings.sqlite_path)
    record = await repository.get_run(daily_key_for_date(settings, date(2026, 5, 2)).value)

    assert result.exit_code == 0
    assert record is not None
    assert record.status == DigestRunStatus.POSTED
    assert record.discord_message_ids == ("111", "222")
    assert "Reconciled" in output.text


@pytest.mark.asyncio
async def test_reconcile_digest_requires_confirmation(tmp_path: Path) -> None:
    """Reconciliation should require exact date confirmation."""
    settings = make_settings(tmp_path)
    output = Buffer()

    result = await run_reconcile_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        message_ids=("111",),
        partial=True,
        confirm_reconcile=None,
        output=output,
    )

    assert result.exit_code == EXPECTED_REFUSAL_EXIT
    assert "confirm-reconcile" in result.message
    assert not settings.sqlite_path.exists()


@pytest.mark.asyncio
async def test_reconcile_digest_can_record_partial_delivery(tmp_path: Path) -> None:
    """Reconciliation should support marking known partial Discord delivery IDs."""
    settings = make_settings(tmp_path)
    output = Buffer()

    result = await run_reconcile_digest_command(
        settings,
        target_date=date(2026, 5, 2),
        message_ids=("111",),
        partial=True,
        confirm_reconcile="2026-05-02",
        output=output,
    )
    repository = SQLiteDigestRunRepository(settings.sqlite_path)
    record = await repository.get_run(daily_key_for_date(settings, date(2026, 5, 2)).value)

    assert result.exit_code == 0
    assert record is not None
    assert record.status == DigestRunStatus.PARTIAL_POSTED
    assert record.partial_discord_message_ids == ("111",)


@pytest.mark.asyncio
async def test_discord_cli_publisher_propagates_startup_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """CLI publisher should not hang if Discord startup fails before readiness."""
    settings = make_settings(tmp_path)

    async def fail_startup(*_args: Any, **_kwargs: Any) -> None:
        """Fail before calling the scheduler-ready hook."""
        raise RuntimeError("invalid discord token")

    monkeypatch.setattr("discordcalendarbot.discord.cli_publisher.start_discord_bot", fail_startup)

    with pytest.raises(RuntimeError, match="invalid discord token"):
        await DiscordCliPublisher(settings).publish((DiscordMessagePart(content="preview"),))


@pytest.mark.asyncio
async def test_discord_cli_publisher_reports_clean_early_exit(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """CLI publisher should raise clearly if the bot exits before publishing."""
    settings = make_settings(tmp_path)

    async def exit_before_ready(*_args: Any, **_kwargs: Any) -> None:
        """Return without calling the scheduler-ready hook."""

    monkeypatch.setattr(
        "discordcalendarbot.discord.cli_publisher.start_discord_bot",
        exit_before_ready,
    )

    with pytest.raises(DiscordCliPublishError, match="exited before publishing"):
        await DiscordCliPublisher(settings).publish((DiscordMessagePart(content="preview"),))
