"""Tests for centralized logging configuration."""

from __future__ import annotations

import logging
import logging.handlers
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from discordcalendarbot.logging_config import (
    MANAGED_HANDLER_MARKER,
    SanitizingFormatter,
    configure_logging,
)
from discordcalendarbot.security.log_sanitizer import LogSanitizer

DEFAULT_BACKUP_COUNT = 2
DEFAULT_MAX_BYTES = 1_048_576


@dataclass(frozen=True)
class FakeLoggingSettings:
    """Small settings object for logging configuration tests."""

    google_credentials_path: Path
    google_token_path: Path
    sqlite_path: Path
    log_level: str = "INFO"
    log_file_path: Path | None = None
    log_max_bytes: int = DEFAULT_MAX_BYTES
    log_backup_count: int = DEFAULT_BACKUP_COUNT


@pytest.fixture(autouse=True)
def restore_root_logging() -> Iterator[None]:
    """Restore root logging handlers after each logging configuration test."""
    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    yield
    for handler in tuple(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()
    for handler in original_handlers:
        root_logger.addHandler(handler)
    root_logger.setLevel(original_level)


def managed_handlers() -> list[logging.Handler]:
    """Return application-managed root logging handlers."""
    return [
        handler
        for handler in logging.getLogger().handlers
        if getattr(handler, MANAGED_HANDLER_MARKER, False)
    ]


def test_configure_logging_keeps_console_handler_without_file(tmp_path: Path) -> None:
    """Console logging should work when no LOG_FILE_PATH is configured."""
    settings = FakeLoggingSettings(
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        sqlite_path=tmp_path / "state.sqlite3",
    )

    configure_logging(settings)

    handlers = managed_handlers()
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert logging.getLogger().level == logging.INFO


def test_configure_logging_adds_rotating_file_handler(tmp_path: Path) -> None:
    """File logging should use bounded rotating files when configured."""
    log_path = tmp_path / "logs" / "bot.log"
    settings = FakeLoggingSettings(
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        sqlite_path=tmp_path / "state.sqlite3",
        log_file_path=log_path,
    )

    configure_logging(settings)

    handlers = managed_handlers()
    file_handlers = [
        handler for handler in handlers if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    assert file_handlers[0].baseFilename == str(log_path)
    assert file_handlers[0].maxBytes == DEFAULT_MAX_BYTES
    assert file_handlers[0].backupCount == DEFAULT_BACKUP_COUNT
    assert log_path.parent.exists()


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    """Repeated configuration should replace managed handlers instead of duplicating them."""
    settings = FakeLoggingSettings(
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        sqlite_path=tmp_path / "state.sqlite3",
    )

    configure_logging(settings)
    configure_logging(settings)

    assert len(managed_handlers()) == 1


def test_sanitizing_formatter_redacts_messages_extras_and_paths(tmp_path: Path) -> None:
    """Formatted logs should redact secrets in messages, extras, URLs, and paths."""
    token_path = tmp_path / "token.json"
    formatter = SanitizingFormatter(LogSanitizer(secret_paths=(token_path,), max_length=1_000))
    record = logging.LogRecord(
        name="discordcalendarbot.tests",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Bearer abc.def.ghi at https://example.test/path?secret=value in %s",
        args=(str(token_path),),
        exc_info=None,
    )
    record.refresh_token = "refresh-secret"  # noqa: S105 - intentional fake token for redaction.

    formatted = formatter.format(record)

    assert "Bearer abc.def.ghi" not in formatted
    assert "secret=value" not in formatted
    assert str(token_path) not in formatted
    assert "refresh-secret" not in formatted
    assert "refresh_token" not in formatted
    assert "[REDACTED_PATH]" in formatted


def test_configured_file_logging_sanitizes_real_emitted_records(tmp_path: Path) -> None:
    """Real file output should redact messages, allowed extras, and secret paths."""
    token_path = tmp_path / "token.json"
    log_path = tmp_path / "logs" / "bot.log"
    settings = FakeLoggingSettings(
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=token_path,
        sqlite_path=tmp_path / "state.sqlite3",
        log_file_path=log_path,
    )

    configure_logging(settings)
    logging.getLogger("discordcalendarbot.tests").info(
        "Bearer abc.def.ghi in %s",
        token_path,
        extra={
            "target_date": "2026-05-02",
            "refresh_token": "refresh-secret",
        },
    )
    for handler in managed_handlers():
        handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "target_date=2026-05-02" in content
    assert "Bearer abc.def.ghi" not in content
    assert str(token_path) not in content
    assert "refresh-secret" not in content
    assert "refresh_token" not in content
    assert "[REDACTED_PATH]" in content
