"""Central logging configuration for runtime and operator commands."""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Protocol

from discordcalendarbot.security.log_sanitizer import LogSanitizer

LOG_FORMAT_DATE = "%Y-%m-%dT%H:%M:%S%z"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
MANAGED_HANDLER_MARKER = "_discordcalendarbot_managed"
STANDARD_RECORD_ATTRIBUTES = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}
SAFE_EXTRA_FIELDS = frozenset(
    {
        "channel_id",
        "discord_message_ids",
        "event_count",
        "guild_id",
        "local_time",
        "message_count",
        "reason",
        "role_id",
        "role_member_count",
        "role_name",
        "run_key",
        "status",
        "target_date",
        "utc_time",
    }
)


class LoggingSettings(Protocol):
    """Settings subset required to configure application logging."""

    log_level: str
    log_file_path: Path | None
    log_max_bytes: int
    log_backup_count: int


class SanitizingFormatter(logging.Formatter):
    """Format log records while redacting sensitive values."""

    def __init__(self, sanitizer: LogSanitizer) -> None:
        """Store the sanitizer used for formatted log output."""
        super().__init__(LOG_FORMAT, datefmt=LOG_FORMAT_DATE)
        self._sanitizer = sanitizer

    def format(self, record: logging.LogRecord) -> str:
        """Return a sanitized log line with safe structured extras."""
        formatted = super().format(record)
        extras = format_record_extras(record)
        if extras:
            formatted = f"{formatted} {extras}"
        return self._sanitizer.sanitize(formatted)


def configure_logging(settings: LoggingSettings) -> None:
    """Configure console logging and optional rotating file logging."""
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    remove_existing_handlers(root_logger)

    formatter = SanitizingFormatter(build_log_sanitizer(settings))
    console_handler = logging.StreamHandler()
    mark_managed(console_handler)
    console_handler.setLevel(settings.log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if settings.log_file_path is not None:
        file_handler = build_rotating_file_handler(settings)
        mark_managed(file_handler)
        file_handler.setLevel(settings.log_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)


def build_rotating_file_handler(settings: LoggingSettings) -> RotatingFileHandler:
    """Build a rotating file handler and prepare its parent directory."""
    log_path = settings.log_file_path
    if log_path is None:
        raise ValueError("LOG_FILE_PATH is required for file logging")
    prepare_log_file_path(log_path)
    handler = RotatingFileHandler(
        log_path,
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    restrict_file_permissions(log_path)
    return handler


def prepare_log_file_path(log_path: Path) -> None:
    """Create the log directory with restrictive permissions where possible."""
    parent = log_path.parent
    if not parent.exists():
        parent.mkdir(parents=True)
        restrict_directory_permissions(parent)


def restrict_directory_permissions(path: Path) -> None:
    """Restrict a directory to the current account on Unix-like systems."""
    if os.name != "nt":
        path.chmod(0o700)


def restrict_file_permissions(path: Path) -> None:
    """Restrict a log file to the current account on Unix-like systems."""
    if os.name != "nt" and path.exists():
        path.chmod(0o600)


def remove_existing_handlers(logger: logging.Logger) -> None:
    """Remove existing root handlers so application logs use sanitized handlers."""
    for handler in tuple(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def mark_managed(handler: logging.Handler) -> None:
    """Mark a handler as owned by the application logging configuration."""
    setattr(handler, MANAGED_HANDLER_MARKER, True)


def build_log_sanitizer(settings: LoggingSettings) -> LogSanitizer:
    """Build a log sanitizer with known sensitive runtime paths."""
    return LogSanitizer(secret_paths=tuple(configured_secret_paths(settings)), max_length=4_000)


def configured_secret_paths(settings: LoggingSettings) -> Iterable[Path]:
    """Yield configured runtime paths that should not appear in logs."""
    for path in (
        getattr(settings, "google_credentials_path", None),
        getattr(settings, "google_token_path", None),
        getattr(settings, "sqlite_path", None),
        settings.log_file_path,
    ):
        if path is not None:
            yield path


def format_record_extras(record: logging.LogRecord) -> str:
    """Format structured log extras without relying on private logging internals."""
    extras = {
        key: value
        for key, value in record.__dict__.items()
        if key in SAFE_EXTRA_FIELDS
        and key not in STANDARD_RECORD_ATTRIBUTES
        and not key.startswith("_")
    }
    if not extras:
        return ""
    return " ".join(f"{key}={value}" for key, value in sorted(extras.items()))
