"""Central redaction utilities for logs and stored errors."""

from __future__ import annotations

import re
from pathlib import Path

TOKEN_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"Bot\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"(client_secret['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(refresh_token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(access_token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(id_token['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"(\btoken['\"]?\s*[:=]\s*['\"]?)[^'\"\s,}]+", re.IGNORECASE),
    re.compile(r"([A-Za-z0-9_-]{24}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{20,})"),
)


class LogSanitizer:
    """Redact sensitive values before logging or persistence."""

    def __init__(self, secret_paths: tuple[Path, ...] = (), *, max_length: int = 1_000) -> None:
        """Store paths and output limits used during sanitization."""
        self._secret_paths = tuple(path.resolve() for path in secret_paths)
        self._max_length = max_length

    def sanitize(self, value: object) -> str:
        """Return a redacted and length-capped string."""
        text = str(value)
        for pattern in TOKEN_PATTERNS:
            text = pattern.sub(self._redact_match, text)
        text = strip_url_queries(text)
        for path in self._secret_paths:
            text = text.replace(str(path), "[REDACTED_PATH]")
        if len(text) > self._max_length:
            return f"{text[: self._max_length - 3]}..."
        return text

    @staticmethod
    def _redact_match(match: re.Match[str]) -> str:
        """Preserve assignment prefixes while redacting secret material."""
        if match.lastindex:
            return f"{match.group(1)}[REDACTED]"
        return "[REDACTED]"


def strip_url_queries(value: str) -> str:
    """Strip query strings from URLs in text."""
    return re.sub(r"(https?://[^\s?]+)\?[^\s]+", r"\1?[REDACTED_QUERY]", value)
