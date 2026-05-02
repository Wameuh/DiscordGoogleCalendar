"""Format daily digests into Discord message parts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from discordcalendarbot.discord.sanitizer import DiscordContentSanitizer
from discordcalendarbot.domain.digest import DailyDigest
from discordcalendarbot.domain.events import CalendarEvent


@dataclass(frozen=True)
class DiscordMessagePart:
    """One Discord message payload."""

    content: str


@dataclass(frozen=True)
class DigestFormatter:
    """Render digests into one or more Discord message parts."""

    sanitizer: DiscordContentSanitizer
    max_chars: int = 1_900

    def format_digest(
        self,
        digest: DailyDigest,
        timezone: ZoneInfo,
    ) -> tuple[DiscordMessagePart, ...]:
        """Render a digest into message parts below the configured character limit."""
        if not digest.should_post:
            return ()
        lines = [format_header(digest.target_date, digest.timezone_name)]
        if digest.events:
            lines.extend(
                format_event_line(event, timezone, self.sanitizer) for event in digest.events
            )
        else:
            lines.append(self.sanitizer.sanitize(digest.empty_message or "No tagged events today."))
        return split_message_lines(lines, max_chars=self.max_chars)


def format_header(target_date: date, timezone_name: str) -> str:
    """Format the digest heading."""
    return f"Daily calendar digest for {target_date.isoformat()} ({timezone_name})"


def format_event_line(
    event: CalendarEvent,
    timezone: ZoneInfo,
    sanitizer: DiscordContentSanitizer,
) -> str:
    """Format one sanitized event line."""
    event_time = format_event_time(event, timezone)
    title = sanitizer.sanitize(event.title)
    return f"- {event_time} {title}"


def format_event_time(event: CalendarEvent, timezone: ZoneInfo) -> str:
    """Format an event time for Discord output."""
    if event.time.is_all_day:
        return "All day:"
    start = coerce_datetime(event.time.start, timezone)
    end = coerce_datetime(event.time.end, timezone)
    return f"{start:%H:%M}-{end:%H:%M}:"


def coerce_datetime(value: datetime | date, timezone: ZoneInfo) -> datetime:
    """Coerce a date or datetime to a timezone-aware datetime."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone)
        return value.astimezone(timezone)
    return datetime.combine(value, time.min, tzinfo=timezone)


def split_message_lines(lines: list[str], *, max_chars: int) -> tuple[DiscordMessagePart, ...]:
    """Split lines into message parts under the configured limit."""
    raw_parts = split_raw_message_lines(lines, max_chars=max_chars)
    if len(raw_parts) <= 1:
        return tuple(DiscordMessagePart(content=part) for part in raw_parts)

    raw_parts = split_raw_message_lines(lines, max_chars=max_chars - prefix_width(len(raw_parts)))
    while True:
        width = prefix_width(len(raw_parts))
        numbered_parts = tuple(
            DiscordMessagePart(content=f"({index}/{len(raw_parts)})\n{part}")
            for index, part in enumerate(raw_parts, start=1)
        )
        if all(len(part.content) <= max_chars for part in numbered_parts):
            return numbered_parts
        raw_parts = split_raw_message_lines(lines, max_chars=max_chars - width - 1)


def split_raw_message_lines(lines: list[str], *, max_chars: int) -> tuple[str, ...]:
    """Split lines into raw message strings under a character budget."""
    parts: list[str] = []
    current = ""
    for line in lines:
        candidate = line if not current else f"{current}\n{line}"
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            parts.append(current)
        current = line
        if len(current) > max_chars:
            parts.append(current[:max_chars])
            current = ""
    if current:
        parts.append(current)
    return tuple(parts)


def prefix_width(total_parts: int) -> int:
    """Return the length of a multipart prefix."""
    return len(f"({total_parts}/{total_parts})\n")
