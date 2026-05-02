"""Application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from google.auth.transport.requests import Request

from discordcalendarbot.calendar.auth import (
    load_authorized_credentials,
    refresh_credentials_if_needed,
)
from discordcalendarbot.calendar.client import GoogleCalendarClient, build_calendar_service
from discordcalendarbot.calendar.tag_filter import AllEventsFilter, TagFilter
from discordcalendarbot.config import BotSettings, EventFilterMode
from discordcalendarbot.discord.bot import DiscordRuntime, start_discord_bot
from discordcalendarbot.discord.formatter import DigestFormatter
from discordcalendarbot.discord.sanitizer import DiscordContentSanitizer
from discordcalendarbot.scheduler.daily_digest import DailyDigestScheduler
from discordcalendarbot.services.digest_service import DailyDigestService, RetryPolicy, SystemClock
from discordcalendarbot.storage.sqlite import SQLiteDigestRunRepository


@dataclass
class RuntimeApplication:
    """Runtime composition for the long-running Discord calendar bot."""

    settings: BotSettings

    async def run(self) -> None:
        """Start the Discord bot and internal scheduler wiring."""
        scheduler_ref: dict[str, DailyDigestScheduler] = {}

        async def start_scheduler(runtime: DiscordRuntime) -> None:
            """Build service dependencies after Discord target validation."""
            scheduler = await build_daily_digest_scheduler(self.settings, runtime=runtime)
            scheduler_ref["scheduler"] = scheduler
            await scheduler.start()

        async def shutdown() -> None:
            """Shutdown scheduler resources when Discord closes."""
            scheduler = scheduler_ref.get("scheduler")
            if scheduler is not None:
                await scheduler.shutdown()

        await start_discord_bot(
            self.settings,
            scheduler_start_hook=start_scheduler,
            shutdown_hook=shutdown,
        )


def build_application(settings: BotSettings | None = None) -> RuntimeApplication | str:
    """Build the runtime application when settings are supplied."""
    if settings is None:
        return "discordcalendarbot"
    return RuntimeApplication(settings=settings)


async def build_daily_digest_scheduler(
    settings: BotSettings,
    *,
    runtime: DiscordRuntime,
) -> DailyDigestScheduler:
    """Build scheduler, service, Google, Discord, and SQLite dependencies."""
    repository = SQLiteDigestRunRepository(settings.sqlite_path)
    await repository.initialize()
    credentials = refresh_credentials_if_needed(
        load_authorized_credentials(settings.google_token_path),
        request=Request(),
    )
    service_resource = build_calendar_service(
        credentials,
        request_timeout_seconds=settings.google_request_timeout_seconds,
    )
    calendar_client = GoogleCalendarClient(
        service_resource,
        request_timeout_seconds=settings.google_request_timeout_seconds,
    )
    clock = SystemClock(settings)
    service = DailyDigestService(
        settings,
        calendar_client=calendar_client,
        repository=repository,
        publisher=runtime.publisher,
        formatter=DigestFormatter(
            sanitizer=DiscordContentSanitizer(),
            max_chars=settings.max_discord_message_chars,
        ),
        tag_filter=build_digest_event_filter(settings),
        clock=clock,
        retry_policy=RetryPolicy(),
    )
    return DailyDigestScheduler(settings, service=service, clock=clock)


def build_digest_event_filter(settings: BotSettings) -> AllEventsFilter | TagFilter:
    """Build the configured digest event filter."""
    if settings.event_filter_mode == EventFilterMode.ALL:
        return AllEventsFilter()
    if settings.event_tag is None:
        raise ValueError("EVENT_TAG is required when EVENT_FILTER_MODE=tagged")
    return TagFilter(settings.event_tag, settings.event_tag_fields)
