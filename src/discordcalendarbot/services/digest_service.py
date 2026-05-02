"""Daily digest service orchestration."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Protocol

from discordcalendarbot.calendar.auth import GoogleAuthError
from discordcalendarbot.calendar.mapper import GoogleEventMappingError, normalize_google_events
from discordcalendarbot.config import BotSettings, EventFilterMode
from discordcalendarbot.discord.formatter import DiscordMessagePart
from discordcalendarbot.discord.publisher import DiscordPublishError, DiscordPublishResult
from discordcalendarbot.domain.digest import (
    LocalDayWindow,
    build_daily_digest,
    build_local_day_window,
)
from discordcalendarbot.domain.events import CalendarEvent
from discordcalendarbot.storage.repository import DigestRunKey, DigestRunRepository

logger = logging.getLogger(__name__)

RETRY_LOCK_MARGIN_SECONDS = 30
DEFAULT_RETRY_ATTEMPTS = 3
HTTP_TOO_MANY_REQUESTS = 429
HTTP_SERVER_ERROR_MIN = 500
HTTP_SERVER_ERROR_MAX = 599


class RetryBudgetExceededError(TimeoutError):
    """Raised when a digest run has no retry budget left inside its lock TTL."""


ERROR_KIND_BY_TYPE = (
    (RetryBudgetExceededError, "RetryBudgetExceededError"),
    (DiscordPublishError, "discord"),
    (GoogleAuthError, "google_auth"),
    (GoogleEventMappingError, "google_event_mapping"),
    (TimeoutError, "timeout"),
    (ConnectionError, "network"),
)


class DigestServiceStatus(str, Enum):
    """High-level service result states."""

    POSTED = "posted"
    SKIPPED_EMPTY = "skipped_empty"
    SKIPPED_IDEMPOTENT = "skipped_idempotent"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_NON_RETRYABLE = "failed_non_retryable"
    PARTIAL_POSTED = "partial_posted"


@dataclass(frozen=True)
class DailyDigestResult:
    """Result of a daily digest service execution."""

    status: DigestServiceStatus
    run_key: str
    target_date: date
    event_count: int = 0
    message_ids: tuple[str, ...] = ()
    reason: str | None = None


class CalendarEventClient(Protocol):
    """Calendar read boundary used by the digest service."""

    async def list_events_for_window(
        self,
        *,
        calendar_id: str,
        window: LocalDayWindow,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        """Return raw Google Calendar event payloads for a local-day window."""


class DigestPublisher(Protocol):
    """Discord publishing boundary used by the digest service."""

    async def publish(self, message_parts: Sequence[DiscordMessagePart]) -> DiscordPublishResult:
        """Publish formatted digest message parts."""


class DigestEventFilter(Protocol):
    """Event filtering boundary used by the digest service."""

    def matches(self, event: CalendarEvent) -> bool:
        """Return whether an event should be included in the digest."""

    def clean_title(self, title: str) -> str:
        """Return the display title for a tagged event."""


class DigestMessageFormatter(Protocol):
    """Digest formatting boundary used by the digest service."""

    def format_digest(
        self,
        digest: Any,
        timezone: Any,
    ) -> tuple[DiscordMessagePart, ...]:
        """Render a digest into Discord message parts."""


class Clock(Protocol):
    """Clock boundary for scheduler and service tests."""

    def now(self) -> datetime:
        """Return the current timezone-aware datetime."""


@dataclass(frozen=True)
class SystemClock:
    """Clock using the configured bot timezone."""

    settings: BotSettings

    def now(self) -> datetime:
        """Return the current datetime in the bot timezone."""
        return datetime.now(tz=self.settings.bot_timezone)


Sleep = Callable[[float], Awaitable[None]]
AsyncOperation = Callable[[], Awaitable[Any]]
RetryPredicate = Callable[[BaseException], bool]


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential retry policy for transient digest failures."""

    max_attempts: int = DEFAULT_RETRY_ATTEMPTS
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 10.0
    jitter_ratio: float = 0.1
    sleep: Sleep = asyncio.sleep
    monotonic: Callable[[], float] = time.monotonic
    random: Callable[[], float] = random.random

    async def run(
        self,
        operation: AsyncOperation,
        *,
        is_retryable: RetryPredicate,
        deadline: float,
    ) -> Any:
        """Run an async operation with bounded transient retries."""
        attempt = 1
        while True:
            if self.monotonic() >= deadline:
                raise RetryBudgetExceededError("Digest retry budget exceeded")
            try:
                return await operation()
            except Exception as error:
                delay = self.delay_for_attempt(error, attempt)
                if not self.should_retry(
                    delay,
                    attempt=attempt,
                    deadline=deadline,
                ) or not is_retryable(error):
                    raise
                await self.sleep(min(delay, max(0.0, deadline - self.monotonic())))
                attempt += 1

    def should_retry(
        self,
        delay: float,
        *,
        attempt: int,
        deadline: float,
    ) -> bool:
        """Return whether another retry fits within configured bounds."""
        if attempt >= self.max_attempts:
            return False
        return self.monotonic() + delay < deadline

    def delay_for_attempt(self, error: BaseException, attempt: int) -> float:
        """Return exponential delay, respecting Retry-After-style attributes."""
        retry_after = getattr(error, "retry_after", None)
        if retry_after is None and error.__cause__ is not None:
            retry_after = getattr(error.__cause__, "retry_after", None)
        if isinstance(retry_after, int | float):
            return float(retry_after)
        delay = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** (attempt - 1)))
        if self.jitter_ratio <= 0:
            return delay
        jitter = delay * self.jitter_ratio * self.random()
        return min(self.max_delay_seconds, delay + jitter)


class DailyDigestService:
    """Coordinate idempotency, calendar reads, formatting, publishing, and persistence."""

    def __init__(
        self,
        settings: BotSettings,
        *,
        calendar_client: CalendarEventClient,
        repository: DigestRunRepository,
        publisher: DigestPublisher,
        formatter: DigestMessageFormatter,
        tag_filter: DigestEventFilter,
        clock: Clock | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        """Store service dependencies."""
        self._settings = settings
        self._calendar_client = calendar_client
        self._repository = repository
        self._publisher = publisher
        self._formatter = formatter
        self._tag_filter = tag_filter
        self._clock = clock or SystemClock(settings)
        self._retry_policy = retry_policy or RetryPolicy()

    async def run_for_date(
        self,
        target_date: date,
        *,
        lock_owner: str = "scheduler",
        namespace: str = "daily",
    ) -> DailyDigestResult:
        """Run one idempotent daily digest for the target local date."""
        key = build_digest_run_key(self._settings, target_date, namespace=namespace)
        retry_deadline = self._retry_deadline()
        claim = await self._repository.claim_run(
            key,
            lock_owner=lock_owner,
            now=self._clock.now(),
            lock_ttl_seconds=self._settings.run_lock_ttl_seconds,
        )
        if not claim.claimed:
            return DailyDigestResult(
                status=DigestServiceStatus.SKIPPED_IDEMPOTENT,
                run_key=key.value,
                target_date=target_date,
                reason=claim.reason,
            )

        try:
            return await self._run_claimed_digest(key, target_date, retry_deadline=retry_deadline)
        except Exception as error:
            retryable = is_retryable_error(error)
            await self._repository.mark_failed(
                key.value,
                retryable=retryable,
                error=error,
                error_kind=error_kind(error),
                now=self._clock.now(),
            )
            return DailyDigestResult(
                status=(
                    DigestServiceStatus.FAILED_RETRYABLE
                    if retryable
                    else DigestServiceStatus.FAILED_NON_RETRYABLE
                ),
                run_key=key.value,
                target_date=target_date,
                reason=error_kind(error),
            )

    async def _run_claimed_digest(
        self,
        key: DigestRunKey,
        target_date: date,
        *,
        retry_deadline: float,
    ) -> DailyDigestResult:
        """Execute a digest after the run has been claimed."""
        window = build_local_day_window(target_date, self._settings.bot_timezone)
        events = await self._fetch_events(window, retry_deadline=retry_deadline)
        digest_events = self._filter_digest_events(events)
        digest = build_daily_digest(
            target_date=target_date,
            timezone_name=self._settings.bot_timezone_name,
            timezone=self._settings.bot_timezone,
            events=digest_events,
            post_empty_digest=self._settings.post_empty_digest,
            empty_digest_text=self._settings.empty_digest_text,
        )
        if not digest.should_post:
            await self._repository.mark_skipped_empty(key.value, now=self._clock.now())
            return DailyDigestResult(
                status=DigestServiceStatus.SKIPPED_EMPTY,
                run_key=key.value,
                target_date=target_date,
            )

        message_parts = self._formatter.format_digest(digest, self._settings.bot_timezone)
        try:
            publish_result = await self._publish_with_retry(
                message_parts,
                retry_deadline=retry_deadline,
            )
        except DiscordPublishError as error:
            if error.accepted_message_ids:
                await self._record_partial_delivery_after_discord_acceptance(key, error)
                return DailyDigestResult(
                    status=DigestServiceStatus.PARTIAL_POSTED,
                    run_key=key.value,
                    target_date=target_date,
                    event_count=len(digest_events),
                    message_ids=error.accepted_message_ids,
                    reason="partial_delivery",
                )
            raise

        await self._mark_posted_after_discord_acceptance(key, publish_result.message_ids)
        return DailyDigestResult(
            status=DigestServiceStatus.POSTED,
            run_key=key.value,
            target_date=target_date,
            event_count=len(digest_events),
            message_ids=publish_result.message_ids,
        )

    async def _fetch_events(
        self,
        window: LocalDayWindow,
        *,
        retry_deadline: float,
    ) -> tuple[CalendarEvent, ...]:
        """Fetch, normalize, and combine events from every configured calendar."""
        normalized: list[CalendarEvent] = []
        for calendar_id in self._settings.google_calendar_ids:
            raw_events = await self._retry_policy.run(
                lambda calendar_id=calendar_id: self._calendar_client.list_events_for_window(
                    calendar_id=calendar_id,
                    window=window,
                    timezone_name=self._settings.bot_timezone_name,
                ),
                is_retryable=is_retryable_error,
                deadline=retry_deadline,
            )
            normalized.extend(
                normalize_google_events(
                    raw_events,
                    calendar_id=calendar_id,
                    timezone=self._settings.bot_timezone,
                    window=window,
                )
            )
        return tuple(normalized)

    def _filter_digest_events(self, events: tuple[CalendarEvent, ...]) -> tuple[CalendarEvent, ...]:
        """Filter digest events and clean display titles when needed."""
        return tuple(
            CalendarEvent(
                calendar_id=event.calendar_id,
                event_id=event.event_id,
                title=self._tag_filter.clean_title(event.title),
                time=event.time,
                description=event.description,
                location=event.location,
                html_link=event.html_link,
                status=event.status,
            )
            for event in events
            if self._tag_filter.matches(event)
        )

    async def _publish_with_retry(
        self,
        message_parts: Sequence[DiscordMessagePart],
        *,
        retry_deadline: float,
    ) -> DiscordPublishResult:
        """Publish message parts with retry only before any Discord acceptance."""
        return await self._retry_policy.run(
            lambda: self._publisher.publish(message_parts),
            is_retryable=is_retryable_publish_error,
            deadline=retry_deadline,
        )

    async def _record_partial_delivery_after_discord_acceptance(
        self,
        key: DigestRunKey,
        error: DiscordPublishError,
    ) -> None:
        """Record partial delivery, logging accepted IDs if storage fails afterward."""
        try:
            await self._repository.record_partial_delivery(
                key.value,
                partial_message_ids=error.accepted_message_ids,
                now=self._clock.now(),
            )
        except Exception:
            logger.critical(
                "Failed to record partial digest after Discord accepted messages",
                extra={
                    "run_key": key.value,
                    "discord_message_ids": error.accepted_message_ids,
                },
            )
            raise

    async def _mark_posted_after_discord_acceptance(
        self,
        key: DigestRunKey,
        message_ids: tuple[str, ...],
    ) -> None:
        """Record success, logging accepted IDs if storage fails afterward."""
        try:
            await self._repository.mark_posted(
                key.value,
                message_ids=message_ids,
                now=self._clock.now(),
            )
        except Exception:
            logger.critical(
                "Failed to record posted digest after Discord accepted messages",
                extra={"run_key": key.value, "discord_message_ids": message_ids},
            )
            raise

    def _retry_deadline(self) -> float:
        """Return the monotonic deadline for retries inside one claimed run."""
        budget = max(0.0, float(self._settings.run_lock_ttl_seconds - RETRY_LOCK_MARGIN_SECONDS))
        return self._retry_policy.monotonic() + budget


def build_digest_run_key(
    settings: BotSettings,
    target_date: date,
    *,
    namespace: str = "daily",
) -> DigestRunKey:
    """Build a stable digest run key without storing raw calendar IDs or tags."""
    return DigestRunKey(
        target_date=target_date,
        timezone=settings.bot_timezone_name,
        guild_id=str(settings.discord_guild_id),
        channel_id=str(settings.discord_channel_id),
        calendar_ids_hash=stable_config_hash(settings.google_calendar_ids),
        event_tag_hash=stable_filter_hash(settings),
        namespace=namespace,
    )


def stable_filter_hash(settings: BotSettings) -> str:
    """Return the idempotency hash for the configured filter policy."""
    if settings.event_filter_mode == EventFilterMode.ALL:
        return stable_config_hash((settings.event_filter_mode.value,))
    return stable_config_hash((settings.event_filter_mode.value, settings.event_tag or ""))


def stable_config_hash(values: Sequence[str]) -> str:
    """Return a stable hash for sensitive config values used in idempotency keys."""
    digest = hashlib.sha256()
    for value in values:
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def is_retryable_publish_error(error: BaseException) -> bool:
    """Return whether a publish error can be retried safely."""
    if isinstance(error, DiscordPublishError) and error.accepted_message_ids:
        return False
    if isinstance(error, DiscordPublishError) and error.__cause__ is not None:
        return is_retryable_error(error.__cause__)
    if isinstance(error, DiscordPublishError):
        return True
    return is_retryable_error(error)


def is_retryable_error(error: BaseException) -> bool:
    """Return whether an error looks transient."""
    if isinstance(error, GoogleAuthError | GoogleEventMappingError | ValueError):
        return False
    if isinstance(error, DiscordPublishError):
        return is_retryable_publish_error(error)
    if isinstance(error, TimeoutError | ConnectionError):
        return True
    status = status_code_for_error(error)
    return (
        status == HTTP_TOO_MANY_REQUESTS or HTTP_SERVER_ERROR_MIN <= status <= HTTP_SERVER_ERROR_MAX
    )


def status_code_for_error(error: BaseException) -> int:
    """Extract a status-like integer from common SDK exception shapes."""
    for attribute in ("status", "status_code", "code"):
        value = getattr(error, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(error, "response", None)
    response_status = getattr(response, "status", None)
    return response_status if isinstance(response_status, int) else 0


def error_kind(error: BaseException) -> str:
    """Classify a failure without storing sensitive exception detail."""
    for error_type, kind in ERROR_KIND_BY_TYPE:
        if isinstance(error, error_type):
            return kind
    return type(error).__name__
