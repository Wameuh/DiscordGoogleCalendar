"""Pure digest domain rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from discordcalendarbot.domain.events import CalendarEvent


@dataclass(frozen=True)
class LocalDayWindow:
    """Half-open local day window in the configured bot timezone."""

    target_date: date
    start: datetime
    end: datetime


@dataclass(frozen=True)
class DailyDigest:
    """Events selected for one local-day digest."""

    target_date: date
    timezone_name: str
    events: tuple[CalendarEvent, ...]
    should_post: bool = True
    empty_message: str | None = None


def build_local_day_window(target_date: date, timezone: ZoneInfo) -> LocalDayWindow:
    """Build the half-open local day window for a target date."""
    start = datetime.combine(target_date, time.min, tzinfo=timezone)
    end = datetime.combine(target_date + timedelta(days=1), time.min, tzinfo=timezone)
    return LocalDayWindow(target_date=target_date, start=start, end=end)


def event_overlaps_window(event: CalendarEvent, window: LocalDayWindow) -> bool:
    """Return whether an event overlaps the half-open local day window."""
    event_start = normalize_event_boundary(event.time.start, window.start.tzinfo)
    event_end = normalize_event_boundary(event.time.end, window.start.tzinfo)
    return event_start < window.end and event_end > window.start


def normalize_event_boundary(value: datetime | date, timezone: ZoneInfo | None) -> datetime:
    """Normalize an event date or datetime boundary to a timezone-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)
    return datetime.combine(value, time.min, tzinfo=timezone)


def sort_events(events: tuple[CalendarEvent, ...], timezone: ZoneInfo) -> tuple[CalendarEvent, ...]:
    """Sort events by all-day status, start time, and title."""
    return tuple(
        sorted(
            events,
            key=lambda event: (
                not event.time.is_all_day,
                normalize_event_boundary(event.time.start, timezone),
                event.title.casefold(),
            ),
        )
    )


def build_daily_digest(
    *,
    target_date: date,
    timezone_name: str,
    timezone: ZoneInfo,
    events: tuple[CalendarEvent, ...],
    post_empty_digest: bool,
    empty_digest_text: str,
) -> DailyDigest:
    """Build a sorted digest and apply empty-day policy."""
    sorted_events = sort_events(events, timezone)
    if sorted_events:
        return DailyDigest(
            target_date=target_date,
            timezone_name=timezone_name,
            events=sorted_events,
        )
    return DailyDigest(
        target_date=target_date,
        timezone_name=timezone_name,
        events=(),
        should_post=post_empty_digest,
        empty_message=empty_digest_text if post_empty_digest else None,
    )
