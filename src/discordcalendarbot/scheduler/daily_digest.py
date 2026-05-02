"""Daily digest APScheduler integration."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Any, Protocol

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from discordcalendarbot.config import BotSettings
from discordcalendarbot.services.digest_service import Clock, DailyDigestService, SystemClock

logger = logging.getLogger(__name__)

DAILY_DIGEST_JOB_ID = "daily-calendar-digest"
STARTUP_CATCH_UP_LOCK_OWNER = "startup-catch-up"
SCHEDULED_LOCK_OWNER = "scheduler"


class SchedulerLike(Protocol):
    """Subset of APScheduler used by the daily digest scheduler."""

    running: bool

    def add_job(self, func: Callable[[], Any], **kwargs: Any) -> Any:
        """Register one scheduler job."""

    def start(self) -> None:
        """Start the scheduler."""

    def shutdown(self, *, wait: bool) -> None:
        """Shutdown the scheduler."""


@dataclass(frozen=True)
class StartupCatchUpDecision:
    """Decision for whether startup catch-up should run."""

    should_run: bool
    target_date: date
    reason: str


class DailyDigestScheduler:
    """Own the APScheduler daily digest job and startup catch-up behavior."""

    def __init__(
        self,
        settings: BotSettings,
        *,
        service: DailyDigestService,
        scheduler: SchedulerLike | None = None,
        clock: Clock | None = None,
    ) -> None:
        """Store scheduler dependencies."""
        self._settings = settings
        self._service = service
        self._scheduler = scheduler or AsyncIOScheduler(timezone=settings.bot_timezone)
        self._clock = clock or SystemClock(settings)
        self._started = False

    async def start(self) -> None:
        """Register the daily job, start APScheduler, and run bounded startup catch-up."""
        if self._started:
            return
        self._register_daily_job()
        self._scheduler.start()
        self._started = True
        await self.run_startup_catch_up()

    async def shutdown(self) -> None:
        """Shutdown APScheduler resources."""
        if self._started or getattr(self._scheduler, "running", False):
            self._scheduler.shutdown(wait=False)
            self._started = False

    async def run_scheduled_digest(self) -> None:
        """Run the scheduled digest for the current local date."""
        now = self._clock.now()
        result = await self._service.run_for_date(
            now.date(),
            lock_owner=SCHEDULED_LOCK_OWNER,
        )
        logger.info(
            "Daily digest scheduled run completed",
            extra={
                "target_date": result.target_date.isoformat(),
                "status": result.status.value,
                "event_count": result.event_count,
                "message_count": len(result.message_ids),
            },
        )

    async def run_startup_catch_up(self) -> StartupCatchUpDecision:
        """Run startup catch-up when startup happens after digest time and before cutoff."""
        now = self._clock.now()
        decision = startup_catch_up_decision(
            now=now,
            daily_digest_time=self._settings.daily_digest_time,
            catch_up_cutoff_time=self._settings.catch_up_cutoff_time,
        )
        logger.info(
            "Evaluated startup digest catch-up",
            extra={
                "utc_time": datetime.now(tz=UTC).isoformat(),
                "local_time": now.isoformat(),
                "target_date": decision.target_date.isoformat(),
                "reason": decision.reason,
            },
        )
        if decision.should_run:
            await self._service.run_for_date(
                decision.target_date,
                lock_owner=STARTUP_CATCH_UP_LOCK_OWNER,
            )
        return decision

    def _register_daily_job(self) -> None:
        """Register the timezone-aware daily cron job."""
        trigger = CronTrigger(
            hour=self._settings.daily_digest_time.hour,
            minute=self._settings.daily_digest_time.minute,
            timezone=self._settings.bot_timezone,
        )
        self._scheduler.add_job(
            self.run_scheduled_digest,
            trigger=trigger,
            id=DAILY_DIGEST_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=self._settings.scheduler_misfire_grace_seconds,
        )


def startup_catch_up_decision(
    *,
    now: datetime,
    daily_digest_time: time,
    catch_up_cutoff_time: time,
) -> StartupCatchUpDecision:
    """Return whether startup should catch up today's digest."""
    target_date = now.date()
    digest_at = datetime.combine(target_date, daily_digest_time, tzinfo=now.tzinfo)
    cutoff_at = datetime.combine(target_date, catch_up_cutoff_time, tzinfo=now.tzinfo)
    if cutoff_at <= digest_at:
        return StartupCatchUpDecision(False, target_date, "invalid_cutoff")
    if now < digest_at:
        return StartupCatchUpDecision(False, target_date, "before_digest_time")
    if now >= cutoff_at:
        return StartupCatchUpDecision(False, target_date, "after_catch_up_cutoff")
    return StartupCatchUpDecision(True, target_date, "within_catch_up_window")
