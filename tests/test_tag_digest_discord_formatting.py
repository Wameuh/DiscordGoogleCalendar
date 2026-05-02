"""Tests for tag filtering, digest rules, and Discord formatting."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from discordcalendarbot.calendar.tag_filter import TagFilter, filter_tagged_events
from discordcalendarbot.discord.formatter import DigestFormatter
from discordcalendarbot.discord.sanitizer import DiscordContentSanitizer
from discordcalendarbot.discord.url_policy import UrlPolicy
from discordcalendarbot.domain.digest import build_daily_digest
from discordcalendarbot.domain.events import CalendarEvent, EventTime

EXPECTED_PART_COUNT = 3
MAX_TEST_MESSAGE_CHARS = 120


def make_event(
    event_id: str,
    title: str,
    *,
    start: datetime | date,
    end: datetime | date,
    description: str | None = None,
    location: str | None = None,
    is_all_day: bool = False,
) -> CalendarEvent:
    """Build a normalized calendar event for tests."""
    return CalendarEvent(
        calendar_id="primary",
        event_id=event_id,
        title=title,
        time=EventTime(start=start, end=end, is_all_day=is_all_day),
        description=description,
        location=location,
    )


def test_tag_filter_is_token_aware_and_case_insensitive() -> None:
    """Tag matching should be case-insensitive without matching partial tokens."""
    timezone = ZoneInfo("Europe/Kiev")
    tagged = make_event(
        "tagged",
        "Planning #Discord-Daily",
        start=datetime(2026, 5, 2, 8, tzinfo=timezone),
        end=datetime(2026, 5, 2, 9, tzinfo=timezone),
    )
    partial = make_event(
        "partial",
        "Planning #discord-dailyish",
        start=datetime(2026, 5, 2, 10, tzinfo=timezone),
        end=datetime(2026, 5, 2, 11, tzinfo=timezone),
    )
    tag_filter = TagFilter("#discord-daily")

    filtered = filter_tagged_events((tagged, partial), tag_filter)

    assert len(filtered) == 1
    assert filtered[0].title == "Planning"


def test_tag_filter_normalizes_html_description() -> None:
    """Description matching should strip HTML and decode entities."""
    timezone = ZoneInfo("Europe/Kiev")
    event = make_event(
        "description-tag",
        "Planning",
        start=datetime(2026, 5, 2, 8, tzinfo=timezone),
        end=datetime(2026, 5, 2, 9, tzinfo=timezone),
        description="<p>Discuss &amp; decide #discord-daily</p>",
    )

    assert TagFilter("#discord-daily").matches(event)


def test_digest_sorting_and_empty_policy() -> None:
    """Digest construction should sort events and honor the empty-post policy."""
    timezone = ZoneInfo("Europe/Kiev")
    timed = make_event(
        "timed",
        "Timed",
        start=datetime(2026, 5, 2, 9, tzinfo=timezone),
        end=datetime(2026, 5, 2, 10, tzinfo=timezone),
    )
    all_day = make_event(
        "all-day",
        "All Day",
        start=date(2026, 5, 2),
        end=date(2026, 5, 3),
        is_all_day=True,
    )

    digest = build_daily_digest(
        target_date=date(2026, 5, 2),
        timezone_name="Europe/Kiev",
        timezone=timezone,
        events=(timed, all_day),
        post_empty_digest=False,
        empty_digest_text="No tagged events today.",
    )
    empty = build_daily_digest(
        target_date=date(2026, 5, 2),
        timezone_name="Europe/Kiev",
        timezone=timezone,
        events=(),
        post_empty_digest=False,
        empty_digest_text="No tagged events today.",
    )

    assert [event.event_id for event in digest.events] == ["all-day", "timed"]
    assert not empty.should_post


def test_discord_sanitizer_neutralizes_mentions_markdown_links_and_controls() -> None:
    """Untrusted text should not render active mentions or masked markdown links."""
    sanitizer = DiscordContentSanitizer(max_field_chars=500)

    sanitized = sanitizer.sanitize(
        "@everyone <@123456789012> <#123456789012> **bold** "
        "[click](https://evil.example/path?x=1) \u202e hidden"
    )

    assert "@everyone" not in sanitized
    assert "<@123456789012>" not in sanitized
    assert "<#123456789012>" not in sanitized
    assert "[click](https://evil.example/path?x=1)" not in sanitized
    assert "\u202e" not in sanitized


def test_url_policy_omits_private_or_unsafe_links_and_strips_query() -> None:
    """URL policy should default to privacy-preserving URL display."""
    default_policy = UrlPolicy()
    enabled_policy = UrlPolicy(allow_location_urls=True)

    assert default_policy.display_location_url("https://example.com/place") is None
    assert enabled_policy.display_location_url("http://example.com/place") is None
    assert enabled_policy.display_location_url("https://meet.google.com/abc-defg-hij") is None

    allowed = enabled_policy.display_location_url("https://example.com/place?secret=1#fragment")

    assert allowed is not None
    assert allowed.url == "https://example.com/place"
    assert allowed.hostname == "example.com"


def test_digest_formatter_splits_messages_and_sanitizes_titles() -> None:
    """Formatter should split long digests and sanitize event titles."""
    timezone = ZoneInfo("Europe/Kiev")
    events = tuple(
        make_event(
            f"event-{index}",
            f"Important @everyone event {index}",
            start=datetime(2026, 5, 2, 8, index, tzinfo=timezone),
            end=datetime(2026, 5, 2, 9, index, tzinfo=timezone),
        )
        for index in range(4)
    )
    digest = build_daily_digest(
        target_date=date(2026, 5, 2),
        timezone_name="Europe/Kiev",
        timezone=timezone,
        events=events,
        post_empty_digest=True,
        empty_digest_text="No tagged events today.",
    )
    formatter = DigestFormatter(
        sanitizer=DiscordContentSanitizer(max_field_chars=100),
        max_chars=MAX_TEST_MESSAGE_CHARS,
    )

    parts = formatter.format_digest(digest, timezone)

    assert len(parts) == EXPECTED_PART_COUNT
    assert parts[0].content.startswith("(1/3)")
    assert all("@everyone" not in part.content for part in parts)
    assert all(len(part.content) <= MAX_TEST_MESSAGE_CHARS for part in parts)
