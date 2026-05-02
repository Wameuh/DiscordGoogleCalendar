"""Google Calendar API adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import google_auth_httplib2
import httplib2
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from discordcalendarbot.domain.digest import LocalDayWindow


class GoogleCalendarService(Protocol):
    """Minimal protocol for the Google Calendar service resource."""

    def events(self) -> Any:
        """Return the events resource."""


ToThread = Callable[..., Awaitable[list[dict[str, Any]]]]


def build_calendar_service(
    credentials: Credentials,
    *,
    request_timeout_seconds: int,
) -> Any:
    """Build a Google Calendar service with a transport-level timeout."""
    http = httplib2.Http(timeout=request_timeout_seconds)
    authorized_http = google_auth_httplib2.AuthorizedHttp(credentials, http=http)
    return build("calendar", "v3", http=authorized_http, cache_discovery=False)


class GoogleCalendarClient:
    """Fetch raw Google Calendar event payloads through the synchronous SDK."""

    def __init__(
        self,
        service: GoogleCalendarService,
        *,
        request_timeout_seconds: int,
        to_thread: ToThread | None = None,
    ) -> None:
        """Store the Google Calendar service resource."""
        self._service = service
        self._request_timeout_seconds = request_timeout_seconds
        self._to_thread = to_thread or asyncio.to_thread

    async def list_events_for_window(
        self,
        *,
        calendar_id: str,
        window: LocalDayWindow,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        """List raw events for a configured local-day window."""
        return await asyncio.wait_for(
            self._to_thread(
                self._list_events_for_window_sync,
                calendar_id=calendar_id,
                window=window,
                timezone_name=timezone_name,
            ),
            timeout=self._request_timeout_seconds,
        )

    def _list_events_for_window_sync(
        self,
        *,
        calendar_id: str,
        window: LocalDayWindow,
        timezone_name: str,
    ) -> list[dict[str, Any]]:
        """Synchronously execute every Google events.list page."""
        events: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            response = self._execute_events_list_page(
                calendar_id=calendar_id,
                window=window,
                timezone_name=timezone_name,
                page_token=page_token,
            )
            items = response.get("items", [])
            if isinstance(items, list):
                events.extend(item for item in items if isinstance(item, dict))
            page_token = response.get("nextPageToken")
            if not isinstance(page_token, str) or not page_token:
                return events

    def _execute_events_list_page(
        self,
        *,
        calendar_id: str,
        window: LocalDayWindow,
        timezone_name: str,
        page_token: str | None,
    ) -> dict[str, Any]:
        """Execute one synchronous Google events.list page request."""
        request = self._service.events().list(
            calendarId=calendar_id,
            timeMin=window.start.isoformat(),
            timeMax=window.end.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            showDeleted=False,
            timeZone=timezone_name,
            pageToken=page_token,
        )
        response = request.execute()
        return response if isinstance(response, dict) else {}
