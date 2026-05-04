"""Calendar event domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class EventTime:
    """Normalized event time in the configured bot timezone."""

    start: datetime | date
    end: datetime | date
    is_all_day: bool = False


@dataclass(frozen=True)
class CalendarEvent:
    """Normalized calendar event used by digest services.

    provider_identity stores a provider-stable identity, such as Google iCalUID,
    when one is available for cross-calendar digest deduplication.
    """

    calendar_id: str
    event_id: str
    title: str
    time: EventTime
    description: str | None = None
    location: str | None = None
    html_link: str | None = None
    status: str | None = None
    provider_identity: str | None = None

    @property
    def stable_identity(self) -> tuple[str, str]:
        """Return the stable identity used for deduplication."""
        return (self.calendar_id, self.event_id)
