"""Map Google Calendar payloads into domain events."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from discordcalendarbot.domain.digest import LocalDayWindow, event_overlaps_window
from discordcalendarbot.domain.events import CalendarEvent, EventTime


class GoogleEventMappingError(ValueError):
    """Raised when a Google event payload cannot be normalized."""


def map_google_event(
    payload: dict[str, Any],
    *,
    calendar_id: str,
    timezone: ZoneInfo,
) -> CalendarEvent:
    """Map one raw Google event payload into a normalized domain event."""
    event_id = str(payload.get("id") or payload.get("iCalUID") or "")
    if not event_id:
        raise GoogleEventMappingError("Google event payload is missing an id")

    start = parse_google_event_time(payload.get("start"), timezone=timezone)
    end = parse_google_event_time(payload.get("end"), timezone=timezone)
    if start.is_all_day != end.is_all_day:
        raise GoogleEventMappingError("Google event start and end types do not match")

    return CalendarEvent(
        calendar_id=calendar_id,
        event_id=event_id,
        title=str(payload.get("summary") or "Untitled event"),
        time=EventTime(start=start.value, end=end.value, is_all_day=start.is_all_day),
        description=optional_string(payload.get("description")),
        location=optional_string(payload.get("location")),
        html_link=optional_string(payload.get("htmlLink")),
        status=optional_string(payload.get("status")),
        provider_identity=optional_string(payload.get("iCalUID")),
    )


def normalize_google_events(
    payloads: Iterable[dict[str, Any]],
    *,
    calendar_id: str,
    timezone: ZoneInfo,
    window: LocalDayWindow,
) -> tuple[CalendarEvent, ...]:
    """Map, deduplicate, remove cancelled events, and apply local-day overlap filtering."""
    events_by_identity: dict[tuple[str, str], CalendarEvent] = {}
    for payload in payloads:
        event = map_google_event(payload, calendar_id=calendar_id, timezone=timezone)
        if event.status == "cancelled":
            continue
        if not event_overlaps_window(event, window):
            continue
        events_by_identity.setdefault(event.stable_identity, event)
    return tuple(events_by_identity.values())


class ParsedGoogleTime:
    """Normalized parsed Google event time."""

    def __init__(self, value: datetime | date, *, is_all_day: bool) -> None:
        """Store the parsed value and whether it represents an all-day boundary."""
        self.value = value
        self.is_all_day = is_all_day


def parse_google_event_time(value: object, *, timezone: ZoneInfo) -> ParsedGoogleTime:
    """Parse a Google event start or end object."""
    if not isinstance(value, dict):
        raise GoogleEventMappingError("Google event time must be an object")
    if "date" in value:
        return ParsedGoogleTime(date.fromisoformat(str(value["date"])), is_all_day=True)
    if "dateTime" in value:
        parsed = datetime.fromisoformat(str(value["dateTime"]).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return ParsedGoogleTime(parsed.astimezone(timezone), is_all_day=False)
    raise GoogleEventMappingError("Google event time must contain date or dateTime")


def optional_string(value: object) -> str | None:
    """Return a stripped string for optional Google text fields."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
