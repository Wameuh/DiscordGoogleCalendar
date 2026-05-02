"""Calendar tag matching and display-title cleanup."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

from discordcalendarbot.domain.events import CalendarEvent

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class TagFilter:
    """Token-aware visible marker filter for Google Calendar events."""

    event_tag: str
    fields: tuple[str, ...] = ("summary", "description")

    def matches(self, event: CalendarEvent) -> bool:
        """Return whether an event contains the configured tag."""
        return any(self._contains_tag(self._field_text(event, field)) for field in self.fields)

    def clean_title(self, title: str) -> str:
        """Remove the configured tag from a displayed title."""
        cleaned = self._tag_pattern().sub("", title)
        return " ".join(cleaned.split()) or "Untitled event"

    def _field_text(self, event: CalendarEvent, field: str) -> str:
        """Return normalized text for a supported tag field."""
        if field == "summary":
            return event.title
        if field == "description":
            return normalize_description(event.description or "")
        if field == "location":
            return event.location or ""
        return ""

    def _contains_tag(self, value: str) -> bool:
        """Return whether a normalized string contains the token-aware tag."""
        return bool(self._tag_pattern().search(value))

    def _tag_pattern(self) -> re.Pattern[str]:
        """Build a case-insensitive token-aware pattern for the configured tag."""
        escaped = re.escape(self.event_tag)
        return re.compile(rf"(?<![\w-]){escaped}(?![\w-])", re.IGNORECASE)


def normalize_description(value: str) -> str:
    """Strip basic HTML, decode entities, and collapse whitespace."""
    without_tags = HTML_TAG_PATTERN.sub(" ", value)
    decoded = html.unescape(without_tags)
    return " ".join(decoded.split())


def filter_tagged_events(
    events: tuple[CalendarEvent, ...],
    tag_filter: TagFilter,
) -> tuple[CalendarEvent, ...]:
    """Filter events that match a tag and clean summary tags from titles."""
    return tuple(
        CalendarEvent(
            calendar_id=event.calendar_id,
            event_id=event.event_id,
            title=tag_filter.clean_title(event.title),
            time=event.time,
            description=event.description,
            location=event.location,
            html_link=event.html_link,
            status=event.status,
        )
        for event in events
        if tag_filter.matches(event)
    )
