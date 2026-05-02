"""Google OAuth credential loading and bootstrap helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

READONLY_CALENDAR_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
EXPECTED_SCOPES: frozenset[str] = frozenset({READONLY_CALENDAR_SCOPE})


class GoogleAuthError(RuntimeError):
    """Raised when Google OAuth credentials are missing, invalid, or unsafe."""


class RefreshableCredentials(Protocol):
    """Protocol for credentials that can be validated and refreshed."""

    valid: bool
    expired: bool
    refresh_token: str | None
    scopes: list[str] | tuple[str, ...] | None

    def refresh(self, request: Request) -> None:
        """Refresh credentials using a Google auth request."""


@dataclass(frozen=True)
class OAuthTokenMetadata:
    """Non-secret metadata recorded next to an OAuth token."""

    account_email: str | None
    granted_scopes: tuple[str, ...]
    created_at: datetime

    def to_json(self) -> str:
        """Serialize metadata to stable JSON."""
        return json.dumps(
            {
                "account_email": self.account_email,
                "granted_scopes": list(self.granted_scopes),
                "created_at": self.created_at.isoformat(),
            },
            indent=2,
            sort_keys=True,
        )


def validate_readonly_scopes(scopes: list[str] | tuple[str, ...] | set[str] | None) -> None:
    """Validate that credentials grant only the v1 read-only Calendar scope."""
    granted_scopes = frozenset(scopes or ())
    if granted_scopes != EXPECTED_SCOPES:
        raise GoogleAuthError(
            "Google OAuth credentials must grant exactly the read-only calendar scope"
        )


def load_authorized_credentials(token_path: Path) -> Credentials:
    """Load OAuth credentials from an authorized-user token file."""
    if not token_path.exists():
        raise GoogleAuthError(f"Google token file does not exist: {token_path}")
    token_payload = json.loads(token_path.read_text(encoding="utf-8"))
    validate_readonly_scopes(token_payload.get("scopes"))
    credentials = Credentials.from_authorized_user_info(token_payload)
    return credentials


def refresh_credentials_if_needed(
    credentials: RefreshableCredentials,
    *,
    request: Request | None = None,
) -> RefreshableCredentials:
    """Refresh expired credentials when a refresh token is available."""
    validate_readonly_scopes(credentials.scopes)
    if credentials.valid:
        return credentials
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(request or Request())
        validate_readonly_scopes(credentials.scopes)
        return credentials
    raise GoogleAuthError("Google OAuth credentials are invalid or require interactive consent")


def write_oauth_metadata(
    metadata_path: Path,
    metadata: OAuthTokenMetadata,
    *,
    force: bool = False,
) -> None:
    """Write non-secret OAuth metadata without overwriting unless forced."""
    if metadata_path.exists() and not force:
        raise GoogleAuthError(f"OAuth metadata already exists: {metadata_path}")
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(metadata.to_json(), encoding="utf-8")


def assert_token_write_allowed(token_path: Path, *, force: bool = False) -> None:
    """Refuse accidental OAuth token overwrites."""
    if token_path.exists() and not force:
        raise GoogleAuthError(f"OAuth token already exists: {token_path}")
