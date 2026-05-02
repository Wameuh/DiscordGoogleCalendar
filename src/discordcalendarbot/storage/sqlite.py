"""SQLite digest run repository."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from discordcalendarbot.security.filesystem_permissions import (
    PermissionFinding,
    check_unix_secret_mode,
)
from discordcalendarbot.security.log_sanitizer import LogSanitizer
from discordcalendarbot.storage.repository import (
    ClaimResult,
    DigestRunKey,
    DigestRunRecord,
    DigestRunStatus,
)

ERROR_CAP = 1_000
TERMINAL_CLAIM_REASONS = {
    DigestRunStatus.POSTED: "already_posted",
    DigestRunStatus.SKIPPED_EMPTY: "already_skipped",
    DigestRunStatus.FAILED_NON_RETRYABLE: "failed_non_retryable",
    DigestRunStatus.PARTIAL_POSTED: "partial_delivery",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS digest_runs (
    run_key TEXT PRIMARY KEY,
    target_date TEXT NOT NULL,
    timezone TEXT NOT NULL,
    guild_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    calendar_ids_hash TEXT NOT NULL,
    event_tag_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    discord_message_ids TEXT,
    partial_discord_message_ids TEXT,
    lock_owner TEXT,
    locked_at TEXT,
    lock_expires_at TEXT,
    last_error TEXT,
    last_error_kind TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    finished_at TEXT
);
"""


class SQLiteDigestRunRepository:
    """SQLite implementation of digest idempotency state."""

    def __init__(self, sqlite_path: Path, *, log_sanitizer: LogSanitizer | None = None) -> None:
        """Store the SQLite path and sanitizer."""
        self._sqlite_path = sqlite_path
        self._log_sanitizer = log_sanitizer or LogSanitizer()

    async def initialize(self) -> None:
        """Initialize schema and WAL mode."""
        self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._sqlite_path) as database:
            await database.execute("PRAGMA journal_mode=WAL")
            await database.execute(SCHEMA)
            await database.commit()
        set_restrictive_sqlite_permissions(self._sqlite_path)

    async def claim_run(
        self,
        key: DigestRunKey,
        *,
        lock_owner: str,
        now: datetime,
        lock_ttl_seconds: int,
    ) -> ClaimResult:
        """Atomically claim a run unless posted or actively locked."""
        lock_expires_at = now + timedelta(seconds=lock_ttl_seconds)
        async with aiosqlite.connect(self._sqlite_path) as database:
            await database.execute("BEGIN IMMEDIATE")
            row = await fetch_one(
                database,
                "SELECT * FROM digest_runs WHERE run_key = ?",
                (key.value,),
            )
            if row is None:
                await database.execute(
                    """
                    INSERT INTO digest_runs (
                        run_key, target_date, timezone, guild_id, channel_id,
                        calendar_ids_hash, event_tag_hash, status, attempt_count,
                        lock_owner, locked_at, lock_expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        key.value,
                        key.target_date.isoformat(),
                        key.timezone,
                        key.guild_id,
                        key.channel_id,
                        key.calendar_ids_hash,
                        key.event_tag_hash,
                        DigestRunStatus.POSTING.value,
                        1,
                        lock_owner,
                        serialize_datetime(now),
                        serialize_datetime(lock_expires_at),
                        serialize_datetime(now),
                        serialize_datetime(now),
                    ),
                )
                await database.commit()
                record = await self.get_run(key.value)
                return ClaimResult(claimed=True, record=record)

            record = row_to_record(row)
            if terminal_reason := TERMINAL_CLAIM_REASONS.get(record.status):
                await database.rollback()
                return ClaimResult(claimed=False, record=record, reason=terminal_reason)
            if record.status == DigestRunStatus.POSTING and record.lock_expires_at:
                if record.lock_expires_at > now:
                    await database.rollback()
                    return ClaimResult(claimed=False, record=record, reason="locked")
            await database.execute(
                """
                UPDATE digest_runs
                SET status = ?, attempt_count = attempt_count + 1, lock_owner = ?,
                    locked_at = ?, lock_expires_at = ?, updated_at = ?
                WHERE run_key = ?
                """,
                (
                    DigestRunStatus.POSTING.value,
                    lock_owner,
                    serialize_datetime(now),
                    serialize_datetime(lock_expires_at),
                    serialize_datetime(now),
                    key.value,
                ),
            )
            await database.commit()
        return ClaimResult(claimed=True, record=await self.get_run(key.value))

    async def get_run(self, run_key: str) -> DigestRunRecord | None:
        """Return one digest run by key."""
        async with aiosqlite.connect(self._sqlite_path) as database:
            row = await fetch_one(
                database,
                "SELECT * FROM digest_runs WHERE run_key = ?",
                (run_key,),
            )
        return row_to_record(row) if row else None

    async def mark_posted(
        self,
        run_key: str,
        *,
        message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Mark a digest run as posted."""
        await self._mark_terminal(
            run_key,
            status=DigestRunStatus.POSTED,
            now=now,
            discord_message_ids=message_ids,
        )

    async def mark_skipped_empty(self, run_key: str, *, now: datetime) -> None:
        """Mark a digest run as skipped because no tagged events were found."""
        await self._mark_terminal(run_key, status=DigestRunStatus.SKIPPED_EMPTY, now=now)

    async def mark_failed(
        self,
        run_key: str,
        *,
        retryable: bool,
        error: object,
        error_kind: str,
        now: datetime,
    ) -> None:
        """Mark a digest run as failed with sanitized error context."""
        sanitized = self._log_sanitizer.sanitize(error)[:ERROR_CAP]
        status = (
            DigestRunStatus.FAILED_RETRYABLE if retryable else DigestRunStatus.FAILED_NON_RETRYABLE
        )
        await self._mark_terminal(
            run_key,
            status=status,
            now=now,
            last_error=sanitized,
            last_error_kind=error_kind,
        )

    async def record_partial_delivery(
        self,
        run_key: str,
        *,
        partial_message_ids: tuple[str, ...],
        now: datetime,
    ) -> None:
        """Record known Discord message IDs after partial delivery."""
        async with aiosqlite.connect(self._sqlite_path) as database:
            await database.execute(
                """
                UPDATE digest_runs
                SET status = ?, partial_discord_message_ids = ?, lock_owner = NULL,
                    locked_at = NULL, lock_expires_at = NULL, updated_at = ?
                WHERE run_key = ?
                """,
                (
                    DigestRunStatus.PARTIAL_POSTED.value,
                    serialize_ids(partial_message_ids),
                    serialize_datetime(now),
                    run_key,
                ),
            )
            await database.commit()

    async def cleanup_old_runs(self, *, now: datetime) -> int:
        """Delete resolved old rows while preserving unresolved partial deliveries."""
        successful_cutoff = (now - timedelta(days=90)).date().isoformat()
        failed_cutoff = (now - timedelta(days=180)).date().isoformat()
        async with aiosqlite.connect(self._sqlite_path) as database:
            cursor = await database.execute(
                """
                DELETE FROM digest_runs
                WHERE (
                    status IN (?, ?) AND target_date < ?
                ) OR (
                    status IN (?, ?) AND target_date < ?
                )
                """,
                (
                    DigestRunStatus.POSTED.value,
                    DigestRunStatus.SKIPPED_EMPTY.value,
                    successful_cutoff,
                    DigestRunStatus.FAILED_RETRYABLE.value,
                    DigestRunStatus.FAILED_NON_RETRYABLE.value,
                    failed_cutoff,
                ),
            )
            await database.commit()
            return cursor.rowcount

    async def _mark_terminal(
        self,
        run_key: str,
        *,
        status: DigestRunStatus,
        now: datetime,
        discord_message_ids: tuple[str, ...] = (),
        last_error: str | None = None,
        last_error_kind: str | None = None,
    ) -> None:
        """Mark a run as terminal and clear the lock."""
        async with aiosqlite.connect(self._sqlite_path) as database:
            await database.execute(
                """
                UPDATE digest_runs
                SET status = ?, discord_message_ids = ?, lock_owner = NULL,
                    locked_at = NULL, lock_expires_at = NULL, last_error = ?,
                    last_error_kind = ?, updated_at = ?, finished_at = ?
                WHERE run_key = ?
                """,
                (
                    status.value,
                    serialize_ids(discord_message_ids),
                    last_error,
                    last_error_kind,
                    serialize_datetime(now),
                    serialize_datetime(now),
                    run_key,
                ),
            )
            await database.commit()

    def check_sqlite_permissions(self) -> tuple[PermissionFinding, ...]:
        """Check SQLite file and sidecar permissions when they exist."""
        if os.name == "nt":
            return (
                PermissionFinding(
                    path=self._sqlite_path,
                    severity="Medium",
                    message="Windows SQLite ACL inspection is not implemented yet",
                ),
            )
        if not self._sqlite_path.exists():
            return ()
        findings: list[PermissionFinding] = []
        for path in sqlite_state_paths(self._sqlite_path):
            if path.exists():
                findings.extend(
                    check_unix_secret_mode(path, path.stat().st_mode, is_directory=False)
                )
        return tuple(findings)


async def fetch_one(
    database: aiosqlite.Connection,
    query: str,
    parameters: tuple[Any, ...],
) -> aiosqlite.Row | None:
    """Fetch one row using dictionary-like row access."""
    database.row_factory = aiosqlite.Row
    cursor = await database.execute(query, parameters)
    return await cursor.fetchone()


def row_to_record(row: aiosqlite.Row) -> DigestRunRecord:
    """Convert a SQLite row into a digest run record."""
    return DigestRunRecord(
        run_key=row["run_key"],
        target_date=datetime.strptime(row["target_date"], "%Y-%m-%d").date(),
        timezone=row["timezone"],
        guild_id=row["guild_id"],
        channel_id=row["channel_id"],
        calendar_ids_hash=row["calendar_ids_hash"],
        event_tag_hash=row["event_tag_hash"],
        status=DigestRunStatus(row["status"]),
        attempt_count=row["attempt_count"],
        discord_message_ids=parse_ids(row["discord_message_ids"]),
        partial_discord_message_ids=parse_ids(row["partial_discord_message_ids"]),
        lock_owner=row["lock_owner"],
        locked_at=parse_datetime(row["locked_at"]),
        lock_expires_at=parse_datetime(row["lock_expires_at"]),
        last_error=row["last_error"],
        last_error_kind=row["last_error_kind"],
        created_at=parse_datetime(row["created_at"]) or datetime.min,
        updated_at=parse_datetime(row["updated_at"]) or datetime.min,
        finished_at=parse_datetime(row["finished_at"]),
    )


def serialize_datetime(value: datetime) -> str:
    """Serialize a timezone-aware timestamp."""
    return value.isoformat()


def parse_datetime(value: str | None) -> datetime | None:
    """Parse an optional timestamp."""
    if not value:
        return None
    return datetime.fromisoformat(value)


def serialize_ids(message_ids: tuple[str, ...]) -> str:
    """Serialize Discord message IDs as JSON."""
    return json.dumps(list(message_ids))


def parse_ids(value: str | None) -> tuple[str, ...]:
    """Parse serialized Discord message IDs."""
    if not value:
        return ()
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        return ()
    return tuple(str(item) for item in parsed)


def set_restrictive_sqlite_permissions(path: Path) -> None:
    """Set restrictive permissions on SQLite files and existing sidecars."""
    if os.name == "nt":
        return
    for state_path in sqlite_state_paths(path):
        if state_path.exists():
            state_path.chmod(0o600)


def sqlite_state_paths(path: Path) -> tuple[Path, ...]:
    """Return the SQLite database path and sensitive sidecar paths."""
    return (path, Path(f"{path}-wal"), Path(f"{path}-shm"))
