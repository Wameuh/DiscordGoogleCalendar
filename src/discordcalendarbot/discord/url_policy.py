"""URL display policy for untrusted calendar links."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

PRIVATE_MEETING_HOST_PARTS: tuple[str, ...] = (
    "meet.google.com",
    "zoom.us",
    "teams.microsoft.com",
)


@dataclass(frozen=True)
class UrlDisplay:
    """Allowed URL display data."""

    url: str
    hostname: str


@dataclass(frozen=True)
class UrlPolicy:
    """Decide whether event URLs may be displayed."""

    allow_location_urls: bool = False

    def display_location_url(self, value: str | None) -> UrlDisplay | None:
        """Return display data for an allowed location URL."""
        if not self.allow_location_urls or not value:
            return None
        parsed = urlparse(value.strip())
        if parsed.scheme != "https" or not parsed.hostname:
            return None
        hostname = parsed.hostname.lower()
        if any(host_part in hostname for host_part in PRIVATE_MEETING_HOST_PARTS):
            return None
        stripped = parsed._replace(query="", fragment="")
        return UrlDisplay(url=urlunparse(stripped), hostname=hostname)
