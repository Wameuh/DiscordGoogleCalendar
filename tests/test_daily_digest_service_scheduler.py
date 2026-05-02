"""Tests for daily digest service and scheduler integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from discordcalendarbot.calendar.tag_filter import TagFilter
from discordcalendarbot.config import BotSettings
from discordcalendarbot.discord.formatter import DigestFormatter, DiscordMessagePart
from discordcalendarbot.discord.publisher import DiscordPublishError, DiscordPublishResult
from discordcalendarbot.discord.sanitizer import DiscordContentSanitizer
from discordcalendarbot.scheduler.daily_digest import (
    DAILY_DIGEST_JOB_ID,
    DailyDigestScheduler,
    startup_catch_up_decision,
)
from discordcalendarbot.services.digest_service import (
    DailyDigestResult,
    DailyDigestService,
    DigestServiceStatus,
    RetryBudgetExceededError,
    RetryPolicy,
    build_digest_run_key,
)
from discordcalendarbot.storage.repository import DigestRunStatus
from discordcalendarbot.storage.sqlite import SQLiteDigestRunRepository

GUILD_ID = 123_456
CHANNEL_ID = 234_567
LOCK_TTL_SECONDS = 900
EXPECTED_DISCORD_RETRY_CALLS = 2
KYIV = ZoneInfo("Europe/Kiev")


@dataclass
class FixedClock:
    """Clock returning a fixed timezone-aware datetime."""

    value: datetime

    def now(self) -> datetime:
        """Return the fixed datetime."""
        return self.value


@dataclass
class AdvancingMonotonic:
    """Monotonic clock that advances past the retry deadline after setup."""

    values: list[float]

    def __call__(self) -> float:
        """Return configured values, repeating the final value."""
        if len(self.values) > 1:
            return self.values.pop(0)
        return self.values[0]


@dataclass
class TransientHttpError(Exception):
    """Fake transient HTTP error."""

    status: int


@dataclass
class RetryAfterHttpError(Exception):
    """Fake transient HTTP error carrying retry-after metadata."""

    status: int
    retry_after: float


@dataclass
class FakeCalendarClient:
    """Fake calendar client with optional transient failures."""

    payloads_by_calendar: dict[str, list[dict[str, Any]]]
    failures_before_success: int = 0
    calls: list[str] = field(default_factory=list)

    async def list_events_for_window(
        self,
        *,
        calendar_id: str,
        window: object,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        """Return fake raw Google events or fail transiently."""
        self.calls.append(calendar_id)
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            raise TransientHttpError(status=500)
        return self.payloads_by_calendar.get(calendar_id, [])


@dataclass
class FakePublisher:
    """Fake Discord publisher."""

    result_ids: tuple[str, ...] = ("111",)
    error: Exception | None = None
    failures_before_success: int = 0
    calls: list[tuple[DiscordMessagePart, ...]] = field(default_factory=list)

    async def publish(
        self,
        message_parts: tuple[DiscordMessagePart, ...],
    ) -> DiscordPublishResult:
        """Capture formatted messages and return fake IDs or raise."""
        self.calls.append(message_parts)
        if self.failures_before_success > 0:
            self.failures_before_success -= 1
            error = self.error or DiscordPublishError("temporary discord failure")
            if self.failures_before_success == 0:
                self.error = None
            raise error
        if self.error is not None:
            raise self.error
        return DiscordPublishResult(message_ids=self.result_ids)


@dataclass
class FakeDigestService:
    """Fake service used by scheduler tests."""

    results: list[DailyDigestResult] = field(default_factory=list)
    runs: list[tuple[date, str]] = field(default_factory=list)

    async def run_for_date(self, target_date: date, *, lock_owner: str) -> DailyDigestResult:
        """Record requested digest runs."""
        self.runs.append((target_date, lock_owner))
        result = DailyDigestResult(
            status=DigestServiceStatus.POSTED,
            run_key="run-key",
            target_date=target_date,
        )
        self.results.append(result)
        return result


@dataclass
class FakeScheduler:
    """Fake APScheduler for job registration assertions."""

    running: bool = False
    jobs: list[dict[str, Any]] = field(default_factory=list)
    shutdown_wait: bool | None = None

    def add_job(self, func: object, **kwargs: Any) -> object:
        """Capture a scheduled job."""
        self.jobs.append({"func": func, **kwargs})
        return object()

    def start(self) -> None:
        """Mark the fake scheduler as running."""
        self.running = True

    def shutdown(self, *, wait: bool) -> None:
        """Mark the fake scheduler as stopped."""
        self.running = False
        self.shutdown_wait = wait


class FailingPartialRepository(SQLiteDigestRunRepository):
    """Repository that fails after partial Discord acceptance."""

    async def record_partial_delivery(
        self,
        run_key: str,
        *,
        partial_message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Fail while recording partial delivery."""
        _ = (run_key, partial_message_ids, now)
        raise RuntimeError("sqlite unavailable")


def make_settings(tmp_path: Path, *, post_empty_digest: bool = False) -> BotSettings:
    """Build test settings without reading environment variables."""
    return BotSettings(
        discord_bot_token=f"token-{tmp_path.name}",
        discord_guild_id=GUILD_ID,
        discord_channel_id=CHANNEL_ID,
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        google_calendar_ids=("primary",),
        event_tag="#discord-daily",
        bot_timezone_name="Europe/Kiev",
        bot_timezone=KYIV,
        daily_digest_time=time(hour=7),
        sqlite_path=tmp_path / "discordcalendarbot.sqlite3",
        post_empty_digest=post_empty_digest,
        empty_digest_text="No tagged events today.",
        catch_up_cutoff_time=time(hour=10),
        run_lock_ttl_seconds=LOCK_TTL_SECONDS,
    )


async def make_repository(tmp_path: Path) -> SQLiteDigestRunRepository:
    """Build and initialize a SQLite repository."""
    repository = SQLiteDigestRunRepository(tmp_path / "discordcalendarbot.sqlite3")
    await repository.initialize()
    return repository


def make_raw_event(event_id: str, *, title: str = "Planning #discord-daily") -> dict[str, Any]:
    """Build a raw Google Calendar event payload."""
    return {
        "id": event_id,
        "summary": title,
        "start": {"dateTime": "2026-05-02T08:00:00+03:00"},
        "end": {"dateTime": "2026-05-02T09:00:00+03:00"},
    }


def make_service(
    settings: BotSettings,
    repository: SQLiteDigestRunRepository,
    calendar_client: FakeCalendarClient,
    publisher: FakePublisher,
    *,
    now: datetime,
    retry_policy: RetryPolicy | None = None,
) -> DailyDigestService:
    """Build a digest service with fakes."""
    return DailyDigestService(
        settings,
        calendar_client=calendar_client,
        repository=repository,
        publisher=publisher,
        formatter=DigestFormatter(
            sanitizer=DiscordContentSanitizer(max_field_chars=200),
            max_chars=settings.max_discord_message_chars,
        ),
        tag_filter=TagFilter(settings.event_tag, settings.event_tag_fields),
        clock=FixedClock(now),
        retry_policy=retry_policy or RetryPolicy(max_attempts=1, base_delay_seconds=0),
    )


async def no_sleep(_seconds: float) -> None:
    """Avoid real retry delays in tests."""


@pytest.mark.asyncio
async def test_daily_digest_posts_once_and_records_success(tmp_path: Path) -> None:
    """Successful digest should fetch, publish, and mark the ledger posted."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    publisher = FakePublisher(result_ids=("111", "222"))
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(date(2026, 5, 2))
    record = await repository.get_run(result.run_key)

    assert result.status == DigestServiceStatus.POSTED
    assert result.message_ids == ("111", "222")
    assert result.event_count == 1
    assert record is not None
    assert record.status == DigestRunStatus.POSTED
    assert record.discord_message_ids == ("111", "222")
    assert len(publisher.calls) == 1


@pytest.mark.asyncio
async def test_existing_success_skips_google_fetch_and_discord_post(tmp_path: Path) -> None:
    """Existing posted runs should skip fetch and publish paths."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    target_date = date(2026, 5, 2)
    key = build_digest_run_key(settings, target_date)
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_posted(key.value, message_ids=("111",), now=now)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    publisher = FakePublisher()
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(target_date)

    assert result.status == DigestServiceStatus.SKIPPED_IDEMPOTENT
    assert result.reason == "already_posted"
    assert calendar_client.calls == []
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_no_tagged_events_marks_skipped_without_publish(tmp_path: Path) -> None:
    """Empty tagged digest should mark skipped when empty posts are disabled."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1", title="Planning")]})
    publisher = FakePublisher()
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(date(2026, 5, 2))
    record = await repository.get_run(result.run_key)

    assert result.status == DigestServiceStatus.SKIPPED_EMPTY
    assert record is not None
    assert record.status == DigestRunStatus.SKIPPED_EMPTY
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_google_transient_failure_records_retryable_failure(tmp_path: Path) -> None:
    """Unrecovered transient Google errors should record a retryable failure."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": []}, failures_before_success=3)
    publisher = FakePublisher()
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(date(2026, 5, 2))
    record = await repository.get_run(result.run_key)

    assert result.status == DigestServiceStatus.FAILED_RETRYABLE
    assert record is not None
    assert record.status == DigestRunStatus.FAILED_RETRYABLE
    assert publisher.calls == []


@pytest.mark.asyncio
async def test_google_mapping_failure_records_non_retryable_failure(tmp_path: Path) -> None:
    """Malformed Google payloads should record a non-retryable mapping failure."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [{"id": "bad"}]})
    publisher = FakePublisher()
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(date(2026, 5, 2))
    record = await repository.get_run(result.run_key)

    assert result.status == DigestServiceStatus.FAILED_NON_RETRYABLE
    assert result.reason == "google_event_mapping"
    assert record is not None
    assert record.status == DigestRunStatus.FAILED_NON_RETRYABLE


@pytest.mark.asyncio
async def test_partial_discord_delivery_records_partial_state(tmp_path: Path) -> None:
    """Split-message partial delivery should record known accepted Discord IDs."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    publisher = FakePublisher(error=DiscordPublishError("boom", accepted_message_ids=("111",)))
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(date(2026, 5, 2))
    record = await repository.get_run(result.run_key)

    assert result.status == DigestServiceStatus.PARTIAL_POSTED
    assert result.message_ids == ("111",)
    assert record is not None
    assert record.status == DigestRunStatus.PARTIAL_POSTED
    assert record.partial_discord_message_ids == ("111",)


@pytest.mark.asyncio
async def test_discord_failure_before_acceptance_records_retryable_failure(tmp_path: Path) -> None:
    """Discord failures before acceptance should record retryable failure context."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    publisher = FakePublisher(error=DiscordPublishError("temporary discord failure"))
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    result = await service.run_for_date(date(2026, 5, 2))
    record = await repository.get_run(result.run_key)

    assert result.status == DigestServiceStatus.FAILED_RETRYABLE
    assert result.reason == "discord"
    assert record is not None
    assert record.status == DigestRunStatus.FAILED_RETRYABLE


@pytest.mark.asyncio
async def test_partial_delivery_logs_ids_when_persistence_fails(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Accepted Discord IDs should be logged immediately if partial persistence fails."""
    settings = make_settings(tmp_path)
    repository = FailingPartialRepository(tmp_path / "discordcalendarbot.sqlite3")
    await repository.initialize()
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    publisher = FakePublisher(error=DiscordPublishError("boom", accepted_message_ids=("111",)))
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    service = make_service(settings, repository, calendar_client, publisher, now=now)

    with caplog.at_level("CRITICAL"):
        result = await service.run_for_date(date(2026, 5, 2))

    assert result.status == DigestServiceStatus.FAILED_NON_RETRYABLE
    assert any(
        record.discord_message_ids == ("111",)
        for record in caplog.records
        if hasattr(record, "discord_message_ids")
    )


@pytest.mark.asyncio
async def test_transient_calendar_failure_retries_within_lock_budget(tmp_path: Path) -> None:
    """Transient calendar failures should retry and still finish inside lock bounds."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient(
        {"primary": [make_raw_event("event-1")]},
        failures_before_success=1,
    )
    publisher = FakePublisher()
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    retry_policy = RetryPolicy(max_attempts=3, base_delay_seconds=0, sleep=no_sleep)
    service = make_service(
        settings,
        repository,
        calendar_client,
        publisher,
        now=now,
        retry_policy=retry_policy,
    )

    result = await service.run_for_date(date(2026, 5, 2))

    assert result.status == DigestServiceStatus.POSTED
    assert calendar_client.calls == ["primary", "primary"]


@pytest.mark.asyncio
async def test_transient_discord_failure_retries_with_retry_after(tmp_path: Path) -> None:
    """Discord retryable causes should retry and respect retry-after delay metadata."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    retry_after_error = RetryAfterHttpError(status=429, retry_after=2.5)
    publisher = FakePublisher(
        error=DiscordPublishError("rate limited", accepted_message_ids=()),
        failures_before_success=1,
    )
    publisher.error.__cause__ = retry_after_error
    sleeps: list[float] = []

    async def capture_sleep(seconds: float) -> None:
        """Capture retry delays."""
        sleeps.append(seconds)

    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    retry_policy = RetryPolicy(
        max_attempts=3,
        base_delay_seconds=0,
        jitter_ratio=0,
        sleep=capture_sleep,
    )
    service = make_service(
        settings,
        repository,
        calendar_client,
        publisher,
        now=now,
        retry_policy=retry_policy,
    )

    result = await service.run_for_date(date(2026, 5, 2))

    assert result.status == DigestServiceStatus.POSTED
    assert len(publisher.calls) == EXPECTED_DISCORD_RETRY_CALLS
    assert sleeps == [2.5]


@pytest.mark.asyncio
async def test_retry_budget_exceeded_stops_before_operation(tmp_path: Path) -> None:
    """Whole-run retry deadline should prevent new work after the lock budget is exhausted."""
    settings = make_settings(tmp_path)
    repository = await make_repository(tmp_path)
    calendar_client = FakeCalendarClient({"primary": [make_raw_event("event-1")]})
    publisher = FakePublisher()
    now = datetime(2026, 5, 2, 7, 0, tzinfo=KYIV)
    retry_policy = RetryPolicy(max_attempts=3, monotonic=AdvancingMonotonic([0.0, 1_000_000.0]))
    service = make_service(
        settings,
        repository,
        calendar_client,
        publisher,
        now=now,
        retry_policy=retry_policy,
    )

    result = await service.run_for_date(date(2026, 5, 2))

    assert result.status == DigestServiceStatus.FAILED_RETRYABLE
    assert result.reason == RetryBudgetExceededError.__name__
    assert calendar_client.calls == []


def test_startup_catch_up_decision_uses_digest_time_and_cutoff() -> None:
    """Startup catch-up should only run within the configured local window."""
    before = startup_catch_up_decision(
        now=datetime(2026, 5, 2, 6, 59, tzinfo=KYIV),
        daily_digest_time=time(hour=7),
        catch_up_cutoff_time=time(hour=10),
    )
    within = startup_catch_up_decision(
        now=datetime(2026, 5, 2, 7, 30, tzinfo=KYIV),
        daily_digest_time=time(hour=7),
        catch_up_cutoff_time=time(hour=10),
    )
    after = startup_catch_up_decision(
        now=datetime(2026, 5, 2, 10, 0, tzinfo=KYIV),
        daily_digest_time=time(hour=7),
        catch_up_cutoff_time=time(hour=10),
    )

    assert not before.should_run
    assert within.should_run
    assert not after.should_run


@pytest.mark.asyncio
async def test_scheduler_registers_daily_job_and_runs_startup_catchup(tmp_path: Path) -> None:
    """Scheduler start should register the cron job and run startup catch-up once."""
    settings = make_settings(tmp_path)
    fake_scheduler = FakeScheduler()
    service = FakeDigestService()
    clock = FixedClock(datetime(2026, 5, 2, 7, 30, tzinfo=KYIV))
    scheduler = DailyDigestScheduler(
        settings,
        service=service,
        scheduler=fake_scheduler,
        clock=clock,
    )

    await scheduler.start()
    await scheduler.start()
    await scheduler.shutdown()

    assert len(fake_scheduler.jobs) == 1
    job = fake_scheduler.jobs[0]
    assert job["id"] == DAILY_DIGEST_JOB_ID
    assert job["func"] == scheduler.run_scheduled_digest
    assert job["max_instances"] == 1
    assert job["misfire_grace_time"] == settings.scheduler_misfire_grace_seconds
    fields = {field.name: str(field) for field in job["trigger"].fields}
    assert fields["hour"] == "7"
    assert fields["minute"] == "0"
    assert str(job["trigger"].timezone) == "Europe/Kiev"
    assert service.runs == [(date(2026, 5, 2), "startup-catch-up")]
    assert fake_scheduler.shutdown_wait is False


@pytest.mark.asyncio
async def test_scheduler_skips_startup_catchup_after_cutoff(tmp_path: Path) -> None:
    """Scheduler should require manual recovery after the catch-up cutoff."""
    settings = make_settings(tmp_path)
    service = FakeDigestService()
    scheduler = DailyDigestScheduler(
        settings,
        service=service,
        scheduler=FakeScheduler(),
        clock=FixedClock(datetime(2026, 5, 2, 10, 1, tzinfo=KYIV)),
    )

    decision = await scheduler.run_startup_catch_up()

    assert not decision.should_run
    assert decision.reason == "after_catch_up_cutoff"
    assert service.runs == []
