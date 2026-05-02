"""Local operator command implementations."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Protocol

from dotenv import load_dotenv
from google.auth.transport.requests import Request

from discordcalendarbot.calendar.auth import (
    load_authorized_credentials,
    refresh_credentials_if_needed,
    run_oauth_login,
)
from discordcalendarbot.calendar.client import GoogleCalendarClient, build_calendar_service
from discordcalendarbot.calendar.tag_filter import TagFilter
from discordcalendarbot.config import BotSettings, load_settings
from discordcalendarbot.discord.cli_publisher import DiscordCliPublisher
from discordcalendarbot.discord.formatter import DigestFormatter, DiscordMessagePart
from discordcalendarbot.discord.publisher import DiscordPublishResult
from discordcalendarbot.discord.sanitizer import DiscordContentSanitizer
from discordcalendarbot.services.digest_service import (
    DailyDigestResult,
    DailyDigestService,
    build_digest_run_key,
)
from discordcalendarbot.storage.repository import ClaimResult, DigestRunKey, DigestRunRepository
from discordcalendarbot.storage.sqlite import SQLiteDigestRunRepository

FORCE_NAMESPACE_PREFIX = "force"
RECONCILE_LOCK_OWNER = "operator-reconcile"


class Output(Protocol):
    """Small text output boundary for operator commands."""

    def write(self, text: str) -> object:
        """Write text to the operator."""


@dataclass(frozen=True)
class OperatorCommandResult:
    """Local operator command result."""

    exit_code: int
    message: str = ""


class PreviewPublisher:
    """Capture formatted Discord messages without posting them."""

    def __init__(self) -> None:
        """Initialize captured message parts."""
        self.message_parts: tuple[DiscordMessagePart, ...] = ()

    async def publish(self, message_parts: tuple[DiscordMessagePart, ...]) -> DiscordPublishResult:
        """Capture a dry-run publish request."""
        self.message_parts = message_parts
        return DiscordPublishResult(message_ids=())


class DryRunRepository(DigestRunRepository):
    """No-op repository that lets dry-runs render without writing SQLite state."""

    async def initialize(self) -> None:
        """Dry-run storage does not need initialization."""

    async def claim_run(
        self,
        key: DigestRunKey,
        *,
        lock_owner: str,
        now: datetime,
        lock_ttl_seconds: int,
    ) -> ClaimResult:
        """Always allow the dry-run to proceed without storing a lock."""
        _ = (lock_owner, now, lock_ttl_seconds)
        return ClaimResult(claimed=True, record=None, reason=key.value)

    async def get_run(self, run_key: str) -> None:
        """Dry-runs never read stored run state."""
        _ = run_key

    async def mark_posted(
        self,
        run_key: str,
        *,
        message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Dry-runs never mark a digest as posted."""
        _ = (run_key, message_ids, now)

    async def mark_skipped_empty(self, run_key: str, *, now: datetime) -> None:
        """Dry-runs never persist empty skips."""
        _ = (run_key, now)

    async def mark_failed(
        self,
        run_key: str,
        *,
        retryable: bool,
        error: object,
        error_kind: str,
        now: datetime,
    ) -> None:
        """Dry-runs never persist failures."""
        _ = (run_key, retryable, error, error_kind, now)

    async def record_partial_delivery(
        self,
        run_key: str,
        *,
        partial_message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Dry-runs never persist partial delivery."""
        _ = (run_key, partial_message_ids, now)

    async def cleanup_old_runs(self, *, now: datetime) -> int:
        """Dry-runs never clean persisted state."""
        _ = now
        return 0


def load_operator_settings(*, project_root: Path | None = None) -> BotSettings:
    """Load .env and environment-backed settings for local operator commands."""
    load_dotenv()
    return load_settings(os.environ, project_root=project_root)


def parse_target_date(value: str) -> date:
    """Parse an operator-supplied ISO date."""
    return date.fromisoformat(value)


async def run_google_auth_login_command(
    settings: BotSettings,
    *,
    force: bool,
    confirm_write_token: str | None,
    output: Output,
) -> OperatorCommandResult:
    """Run explicit OAuth bootstrap for local operators."""
    if confirm_write_token != settings.google_token_path.name:
        return OperatorCommandResult(
            2,
            "Refusing to write token; pass "
            f"--confirm-write-token {settings.google_token_path.name}",
        )
    metadata = run_oauth_login(
        credentials_path=settings.google_credentials_path,
        token_path=settings.google_token_path,
        metadata_path=oauth_metadata_path(settings.google_token_path),
        now=datetime.now(tz=timezone.utc),
        force=force,
    )
    output.write(
        "\n".join(
            (
                "Google OAuth token written.",
                f"Token path: {settings.google_token_path}",
                f"Metadata path: {oauth_metadata_path(settings.google_token_path)}",
                f"Granted scopes: {', '.join(metadata.granted_scopes)}",
                f"Account email: {metadata.account_email or 'unknown'}",
            )
        )
        + "\n"
    )
    return OperatorCommandResult(0, "oauth_login_complete")


async def run_dry_run_command(
    settings: BotSettings,
    *,
    target_date: date,
    redact: bool,
    summary_only: bool,
    output: Output,
) -> OperatorCommandResult:
    """Render a digest preview without writing SQLite state or posting to Discord."""
    message_parts = await render_dry_run(settings, target_date=target_date)
    if summary_only:
        output.write(
            f"Dry run for {target_date.isoformat()}: "
            f"{len(message_parts)} Discord message part(s).\n"
        )
        return OperatorCommandResult(0, "dry_run_summary")
    for index, part in enumerate(message_parts, start=1):
        content = redact_message(part.content) if redact else part.content
        output.write(f"--- message {index}/{len(message_parts)} ---\n{content}\n")
    return OperatorCommandResult(0, "dry_run_complete")


async def run_send_digest_command(
    settings: BotSettings,
    *,
    target_date: date,
    force: bool,
    channel_id: int | None,
    confirm_force: str | None,
    output: Output,
) -> OperatorCommandResult:
    """Send a digest through the same service used by the scheduler."""
    if force and confirm_force != target_date.isoformat():
        return OperatorCommandResult(
            2,
            f"Refusing force send; pass --confirm-force {target_date.isoformat()}",
        )
    if force and channel_id != settings.discord_channel_id:
        return OperatorCommandResult(
            2,
            f"Refusing force send; pass --channel-id {settings.discord_channel_id}",
        )
    if force:
        preview = await render_dry_run(settings, target_date=target_date)
        output.write(
            f"Force preview for {target_date.isoformat()}: "
            f"{len(preview)} Discord message part(s).\n"
        )
    service = await build_operator_digest_service(settings)
    namespace = (
        f"{FORCE_NAMESPACE_PREFIX}-{target_date.isoformat()}-{uuid.uuid4().hex}"
        if force
        else "daily"
    )
    result = await service.run_for_date(
        target_date,
        lock_owner="operator-force" if force else "operator-send",
        namespace=namespace,
    )
    output.write(format_send_result(result) + "\n")
    return OperatorCommandResult(0, result.status.value)


async def run_reconcile_digest_command(
    settings: BotSettings,
    *,
    target_date: date,
    message_ids: tuple[str, ...],
    partial: bool,
    confirm_reconcile: str | None,
    output: Output,
) -> OperatorCommandResult:
    """Record known Discord message IDs without fetching Google Calendar data."""
    if confirm_reconcile != target_date.isoformat():
        return OperatorCommandResult(
            2,
            f"Refusing reconciliation; pass --confirm-reconcile {target_date.isoformat()}",
        )
    repository = SQLiteDigestRunRepository(settings.sqlite_path)
    await repository.initialize()
    key = daily_key_for_date(settings, target_date)
    now = datetime.now(tz=settings.bot_timezone)
    claim = await repository.claim_run(
        key,
        lock_owner=RECONCILE_LOCK_OWNER,
        now=now,
        lock_ttl_seconds=settings.run_lock_ttl_seconds,
    )
    if not claim.claimed and claim.reason not in {"locked"}:
        return OperatorCommandResult(
            2,
            f"Refusing reconciliation for existing state: {claim.reason}",
        )
    if not claim.claimed:
        return OperatorCommandResult(2, "Refusing reconciliation while digest run is locked")
    if partial:
        await repository.record_partial_delivery(
            key.value,
            partial_message_ids=message_ids,
            now=now,
        )
        status = "partial"
    else:
        await repository.mark_posted(key.value, message_ids=message_ids, now=now)
        status = "posted"
    output.write(f"Reconciled {target_date.isoformat()} as {status}: {', '.join(message_ids)}\n")
    return OperatorCommandResult(0, f"reconciled_{status}")


async def render_dry_run(
    settings: BotSettings,
    *,
    target_date: date,
) -> tuple[DiscordMessagePart, ...]:
    """Render the Discord messages that would be sent for a target date."""
    publisher = PreviewPublisher()
    service = await build_operator_digest_service(
        settings,
        repository=DryRunRepository(),
        publisher=publisher,
    )
    await service.run_for_date(target_date, lock_owner="operator-dry-run", namespace="dry-run")
    return publisher.message_parts


async def build_calendar_client(settings: BotSettings) -> GoogleCalendarClient:
    """Build an authenticated Google Calendar client for operator commands."""
    credentials = refresh_credentials_if_needed(
        load_authorized_credentials(settings.google_token_path),
        request=Request(),
    )
    return GoogleCalendarClient(
        build_calendar_service(
            credentials,
            request_timeout_seconds=settings.google_request_timeout_seconds,
        ),
        request_timeout_seconds=settings.google_request_timeout_seconds,
    )


async def build_operator_digest_service(
    settings: BotSettings,
    *,
    repository: DigestRunRepository | None = None,
    publisher: object | None = None,
) -> DailyDigestService:
    """Build the digest service for local send commands."""
    digest_repository = repository or SQLiteDigestRunRepository(settings.sqlite_path)
    await digest_repository.initialize()
    return DailyDigestService(
        settings,
        calendar_client=await build_calendar_client(settings),
        repository=digest_repository,
        publisher=publisher or DiscordCliPublisher(settings),
        formatter=DigestFormatter(
            sanitizer=DiscordContentSanitizer(),
            max_chars=settings.max_discord_message_chars,
        ),
        tag_filter=TagFilter(settings.event_tag, settings.event_tag_fields),
    )


def daily_key_for_date(settings: BotSettings, target_date: date) -> DigestRunKey:
    """Build the normal daily digest key for operator reconciliation."""
    return build_digest_run_key(settings, target_date)


def oauth_metadata_path(token_path: Path) -> Path:
    """Return the non-secret OAuth metadata path for a token file."""
    return token_path.with_name(f"{token_path.name}.metadata.json")


def redact_message(content: str) -> str:
    """Return a safer dry-run message preview."""
    redacted_lines = [
        "- [redacted event]" if line.startswith("- ") else line for line in content.splitlines()
    ]
    return "\n".join(redacted_lines)


def format_send_result(result: DailyDigestResult) -> str:
    """Format send-digest result for local operators."""
    return (
        f"Digest {result.status.value} for {result.target_date.isoformat()} "
        f"events={result.event_count} messages={len(result.message_ids)}"
    )
