"""Tests for the Google Calendar read path."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

import pytest

from discordcalendarbot.calendar.auth import (
    READONLY_CALENDAR_SCOPE,
    GoogleAuthError,
    OAuthTokenMetadata,
    assert_token_write_allowed,
    load_authorized_credentials,
    refresh_credentials_if_needed,
    validate_readonly_scopes,
    write_oauth_metadata,
)
from discordcalendarbot.calendar.client import GoogleCalendarClient, build_calendar_service
from discordcalendarbot.calendar.mapper import (
    GoogleEventMappingError,
    map_google_event,
    normalize_google_events,
)
from discordcalendarbot.domain.digest import build_local_day_window

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

EXPECTED_KYIV_HOUR = 11
EXPECTED_TIMEOUT_SECONDS = 20
FAKE_REFRESH_TOKEN = "fake-refresh-token-value"  # noqa: S105


class FakeCredentials:
    """Small fake for refreshable Google credentials."""

    def __init__(self, *, valid: bool, expired: bool, scopes: list[str]) -> None:
        """Store fake credential state."""
        self.valid = valid
        self.expired = expired
        self.scopes = scopes
        self.refresh_token = FAKE_REFRESH_TOKEN
        self.was_refreshed = False

    def refresh(self, _request: object) -> None:
        """Mark credentials as refreshed."""
        self.valid = True
        self.expired = False
        self.was_refreshed = True


class FakeEventsResource:
    """Fake Google events resource that records list parameters."""

    def __init__(self, response: dict[str, Any] | list[dict[str, Any]]) -> None:
        """Store the response returned by execute."""
        self.responses = response if isinstance(response, list) else [response]
        self.list_calls: list[dict[str, Any]] = []

    def list(self, **kwargs: Any) -> FakeEventsResource:
        """Record events.list keyword arguments."""
        self.list_calls.append(kwargs)
        return self

    def execute(self) -> dict[str, Any]:
        """Return the configured fake API response."""
        return self.responses.pop(0)


class FakeCalendarService:
    """Fake Google Calendar service resource."""

    def __init__(self, events_resource: FakeEventsResource) -> None:
        """Store the fake events resource."""
        self.events_resource = events_resource

    def events(self) -> FakeEventsResource:
        """Return the fake events resource."""
        return self.events_resource


class FakeHttp:
    """Fake httplib2 transport that captures the configured timeout."""

    timeout: int | None = None

    def __init__(self, *, timeout: int) -> None:
        """Store the configured timeout for assertions."""
        type(self).timeout = timeout


class FakeAuthorizedHttp:
    """Fake authorized HTTP wrapper that captures the wrapped transport."""

    http: FakeHttp | None = None

    def __init__(self, _credentials: object, *, http: FakeHttp) -> None:
        """Store the wrapped HTTP transport."""
        type(self).http = http


def test_validate_readonly_scopes_rejects_broader_scopes() -> None:
    """Google credentials should grant exactly the read-only v1 scope."""
    with pytest.raises(GoogleAuthError, match="read-only calendar scope"):
        validate_readonly_scopes(
            [READONLY_CALENDAR_SCOPE, "https://www.googleapis.com/auth/calendar"]
        )


def test_load_authorized_credentials_validates_stored_token_scopes(tmp_path: Path) -> None:
    """Credential loading should validate scopes stored in the token file."""
    token_path = tmp_path / "token.json"
    token_path.write_text(
        """
        {
          "token": "access-token",
          "refresh_token": "refresh-token",
          "client_id": "client-id",
          "client_secret": "client-secret",
          "token_uri": "https://oauth2.googleapis.com/token",
          "scopes": ["https://www.googleapis.com/auth/calendar"]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(GoogleAuthError, match="read-only calendar scope"):
        load_authorized_credentials(token_path)


def test_refresh_credentials_if_needed_refreshes_expired_credentials() -> None:
    """Expired credentials with refresh tokens should refresh through the adapter boundary."""
    credentials = FakeCredentials(valid=False, expired=True, scopes=[READONLY_CALENDAR_SCOPE])

    refreshed = refresh_credentials_if_needed(credentials, request=object())

    assert refreshed is credentials
    assert credentials.was_refreshed
    assert credentials.valid


def test_assert_token_write_allowed_refuses_overwrite_without_force(tmp_path: Path) -> None:
    """OAuth bootstrap should refuse accidental token overwrite."""
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")

    with pytest.raises(GoogleAuthError, match="already exists"):
        assert_token_write_allowed(token_path)


def test_write_oauth_metadata_writes_non_secret_metadata(tmp_path: Path) -> None:
    """OAuth metadata should be written as non-secret operator context."""
    metadata_path = tmp_path / "token.metadata.json"
    metadata = OAuthTokenMetadata(
        account_email="user@example.com",
        granted_scopes=(READONLY_CALENDAR_SCOPE,),
        created_at=datetime(2026, 5, 2, 7, 0),
    )

    write_oauth_metadata(metadata_path, metadata)

    text = metadata_path.read_text(encoding="utf-8")
    assert "user@example.com" in text
    assert READONLY_CALENDAR_SCOPE in text


def test_build_calendar_service_uses_transport_timeout(monkeypatch: MonkeyPatch) -> None:
    """Google service construction should set a finite transport-level timeout."""
    build_calls: list[dict[str, Any]] = []

    def fake_build(*args: Any, **kwargs: Any) -> object:
        """Capture discovery build arguments."""
        build_calls.append({"args": args, "kwargs": kwargs})
        return object()

    monkeypatch.setattr("discordcalendarbot.calendar.client.httplib2.Http", FakeHttp)
    monkeypatch.setattr(
        "discordcalendarbot.calendar.client.google_auth_httplib2.AuthorizedHttp",
        FakeAuthorizedHttp,
    )
    monkeypatch.setattr("discordcalendarbot.calendar.client.build", fake_build)

    service = build_calendar_service(
        object(),
        request_timeout_seconds=EXPECTED_TIMEOUT_SECONDS,
    )

    assert service is not None
    assert FakeHttp.timeout == EXPECTED_TIMEOUT_SECONDS
    assert FakeAuthorizedHttp.http is not None
    assert build_calls[0]["args"] == ("calendar", "v3")
    assert build_calls[0]["kwargs"]["cache_discovery"] is False


@pytest.mark.asyncio
async def test_google_calendar_client_sends_expected_events_list_parameters(
    monkeypatch: MonkeyPatch,
) -> None:
    """Google adapter should send the architecture-defined events.list parameters."""
    monkeypatch.setenv("DISCORDCALENDARBOT_TESTING", "1")
    timezone = ZoneInfo("Europe/Kiev")
    window = build_local_day_window(date(2026, 5, 2), timezone)
    events_resource = FakeEventsResource(response={"items": [{"id": "event-1"}]})
    to_thread_calls: list[str] = []

    async def fake_to_thread(function: Any, **kwargs: Any) -> Any:
        """Run synchronously while proving the executor boundary was used."""
        to_thread_calls.append(function.__name__)
        return function(**kwargs)

    client = GoogleCalendarClient(
        FakeCalendarService(events_resource),
        request_timeout_seconds=EXPECTED_TIMEOUT_SECONDS,
        to_thread=fake_to_thread,
    )

    events = await client.list_events_for_window(
        calendar_id="primary",
        window=window,
        timezone_name="Europe/Kiev",
    )

    assert events == [{"id": "event-1"}]
    assert to_thread_calls == ["_list_events_for_window_sync"]
    assert events_resource.list_calls == [
        {
            "calendarId": "primary",
            "timeMin": window.start.isoformat(),
            "timeMax": window.end.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "showDeleted": False,
            "timeZone": "Europe/Kiev",
            "pageToken": None,
        }
    ]


@pytest.mark.asyncio
async def test_google_calendar_client_follows_pagination() -> None:
    """Google adapter should fetch all event pages for busy days."""
    timezone = ZoneInfo("Europe/Kiev")
    window = build_local_day_window(date(2026, 5, 2), timezone)
    events_resource = FakeEventsResource(
        response=[
            {"items": [{"id": "event-1"}], "nextPageToken": "next-page"},
            {"items": [{"id": "event-2"}]},
        ]
    )
    client = GoogleCalendarClient(
        FakeCalendarService(events_resource),
        request_timeout_seconds=EXPECTED_TIMEOUT_SECONDS,
    )

    events = await client.list_events_for_window(
        calendar_id="primary",
        window=window,
        timezone_name="Europe/Kiev",
    )

    assert events == [{"id": "event-1"}, {"id": "event-2"}]
    assert events_resource.list_calls[1] == {
        "calendarId": "primary",
        "timeMin": window.start.isoformat(),
        "timeMax": window.end.isoformat(),
        "singleEvents": True,
        "orderBy": "startTime",
        "showDeleted": False,
        "timeZone": "Europe/Kiev",
        "pageToken": "next-page",
    }


def test_map_google_event_normalizes_timed_event() -> None:
    """Mapper should convert timed Google payloads to configured timezone datetimes."""
    event = map_google_event(
        {
            "id": "event-1",
            "summary": "Session",
            "start": {"dateTime": "2026-05-02T08:00:00+00:00"},
            "end": {"dateTime": "2026-05-02T09:00:00+00:00"},
            "status": "confirmed",
        },
        calendar_id="primary",
        timezone=ZoneInfo("Europe/Kiev"),
    )

    assert event.title == "Session"
    assert event.time.start.hour == EXPECTED_KYIV_HOUR
    assert not event.time.is_all_day


def test_map_google_event_normalizes_all_day_event() -> None:
    """Mapper should preserve all-day Google date boundaries."""
    event = map_google_event(
        {
            "id": "event-2",
            "summary": "Holiday",
            "start": {"date": "2026-05-02"},
            "end": {"date": "2026-05-03"},
        },
        calendar_id="primary",
        timezone=ZoneInfo("Europe/Kiev"),
    )

    assert event.time.start == date(2026, 5, 2)
    assert event.time.end == date(2026, 5, 3)
    assert event.time.is_all_day


def test_map_google_event_rejects_missing_time() -> None:
    """Mapper should fail clearly for malformed Google payloads."""
    with pytest.raises(GoogleEventMappingError, match="time must be an object"):
        map_google_event({"id": "event-3"}, calendar_id="primary", timezone=ZoneInfo("Europe/Kiev"))


def test_normalize_google_events_filters_cancelled_out_of_window_and_duplicates() -> None:
    """Normalization should filter cancelled/out-of-window events and deduplicate by identity."""
    timezone = ZoneInfo("Europe/Kiev")
    window = build_local_day_window(date(2026, 5, 2), timezone)
    payloads = [
        {
            "id": "keep",
            "summary": "Keep",
            "start": {"dateTime": "2026-05-02T08:00:00+03:00"},
            "end": {"dateTime": "2026-05-02T09:00:00+03:00"},
        },
        {
            "id": "keep",
            "summary": "Duplicate",
            "start": {"dateTime": "2026-05-02T10:00:00+03:00"},
            "end": {"dateTime": "2026-05-02T11:00:00+03:00"},
        },
        {
            "id": "cancelled",
            "summary": "Cancelled",
            "status": "cancelled",
            "start": {"dateTime": "2026-05-02T08:00:00+03:00"},
            "end": {"dateTime": "2026-05-02T09:00:00+03:00"},
        },
        {
            "id": "tomorrow",
            "summary": "Tomorrow",
            "start": {"dateTime": "2026-05-03T08:00:00+03:00"},
            "end": {"dateTime": "2026-05-03T09:00:00+03:00"},
        },
    ]

    events = normalize_google_events(
        payloads,
        calendar_id="primary",
        timezone=timezone,
        window=window,
    )

    assert len(events) == 1
    assert events[0].event_id == "keep"
