"""Digest run repository protocols and value objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Protocol


class DigestRunStatus(str, Enum):
    """Known digest run states."""

    POSTING = "posting"
    POSTED = "posted"
    SKIPPED_EMPTY = "skipped_empty"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NON_RETRYABLE = "failed_non_retryable"
    PARTIAL_POSTED = "partial_posted"


@dataclass(frozen=True)
class DigestRunKey:
    """Stable idempotency key inputs for one daily digest."""

    target_date: date
    timezone: str
    guild_id: str
    channel_id: str
    calendar_ids_hash: str
    event_tag_hash: str

    @property
    def value(self) -> str:
        """Return the storage key."""
        return (
            f"daily:{self.target_date.isoformat()}:{self.timezone}:{self.guild_id}:"
            f"{self.channel_id}:{self.calendar_ids_hash}:{self.event_tag_hash}"
        )


@dataclass(frozen=True)
class DigestRunRecord:
    """Stored digest run state."""

    run_key: str
    target_date: date
    timezone: str
    guild_id: str
    channel_id: str
    calendar_ids_hash: str
    event_tag_hash: str
    status: DigestRunStatus
    attempt_count: int
    discord_message_ids: tuple[str, ...]
    partial_discord_message_ids: tuple[str, ...]
    lock_owner: str | None
    locked_at: datetime | None
    lock_expires_at: datetime | None
    last_error: str | None
    last_error_kind: str | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class ClaimResult:
    """Result of attempting to claim a digest run."""

    claimed: bool
    record: DigestRunRecord | None = None
    reason: str | None = None


class DigestRunRepository(Protocol):
    """Repository boundary for digest idempotency state."""

    async def initialize(self) -> None:
        """Initialize storage schema."""

    async def claim_run(
        self,
        key: DigestRunKey,
        *,
        lock_owner: str,
        now: datetime,
        lock_ttl_seconds: int,
    ) -> ClaimResult:
        """Atomically claim a digest run for posting."""

    async def get_run(self, run_key: str) -> DigestRunRecord | None:
        """Return a digest run by key."""

    async def mark_posted(
        self,
        run_key: str,
        *,
        message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Mark a digest as successfully posted."""

    async def mark_skipped_empty(self, run_key: str, *, now: datetime) -> None:
        """Mark a digest run as skipped because it had no tagged events."""

    async def mark_failed(
        self,
        run_key: str,
        *,
        retryable: bool,
        error: object,
        error_kind: str,
        now: datetime,
    ) -> None:
        """Mark a digest run as failed with sanitized error context."""

    async def record_partial_delivery(
        self,
        run_key: str,
        *,
        partial_message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Record known Discord message IDs for a partial delivery."""

    async def cleanup_old_runs(self, *, now: datetime) -> int:
        """Clean up old resolved run records."""
