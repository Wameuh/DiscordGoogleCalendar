"""Tests for the SQLite digest run repository."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from discordcalendarbot.security.log_sanitizer import LogSanitizer
from discordcalendarbot.storage.repository import DigestRunKey, DigestRunRepository, DigestRunStatus
from discordcalendarbot.storage.sqlite import SQLiteDigestRunRepository, sqlite_state_paths

LOCK_TTL_SECONDS = 900
EXPECTED_RECLAIM_ATTEMPTS = 2
ERROR_MAX_LENGTH = 200
CONCURRENT_CLAIM_ATTEMPTS = 5
EXPECTED_LOCKED_DUPLICATES = 4
EXPECTED_RETENTION_DELETIONS = 3
KYIV = ZoneInfo("Europe/Kiev")


def run_key(target_date: date = date(2026, 5, 2)) -> DigestRunKey:
    """Build a deterministic digest run key."""
    return DigestRunKey(
        target_date=target_date,
        timezone="Europe/Kiev",
        guild_id="guild-hash",
        channel_id="channel-hash",
        calendar_ids_hash="calendar-hash",
        event_tag_hash="tag-hash",
    )


async def initialized_repository(tmp_path: Path) -> SQLiteDigestRunRepository:
    """Create an initialized repository for tests."""
    repository = SQLiteDigestRunRepository(
        tmp_path / "discordcalendarbot.sqlite3",
        log_sanitizer=LogSanitizer(max_length=200),
    )
    await repository.initialize()
    return repository


def test_sqlite_repository_satisfies_protocol(tmp_path: Path) -> None:
    """SQLite implementation should expose the full repository lifecycle protocol."""
    repository: DigestRunRepository = SQLiteDigestRunRepository(
        tmp_path / "discordcalendarbot.sqlite3"
    )

    assert repository is not None


@pytest.mark.asyncio
async def test_claim_run_inserts_posting_record(tmp_path: Path) -> None:
    """First claim should insert a posting run with a lock."""
    repository = await initialized_repository(tmp_path)
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)

    result = await repository.claim_run(
        run_key(),
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert result.claimed
    assert result.record is not None
    assert result.record.status == DigestRunStatus.POSTING
    assert result.record.attempt_count == 1
    assert result.record.lock_owner == "scheduler"


@pytest.mark.asyncio
async def test_existing_posted_run_skips_claim_without_fetch_or_post(tmp_path: Path) -> None:
    """Posted runs should not be claimed again."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_posted(key.value, message_ids=("111", "222"), now=now)

    result = await repository.claim_run(
        key,
        lock_owner="manual",
        now=now + timedelta(minutes=1),
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert not result.claimed
    assert result.reason == "already_posted"
    assert result.record is not None
    assert result.record.discord_message_ids == ("111", "222")


@pytest.mark.asyncio
async def test_existing_skipped_empty_run_blocks_claim(tmp_path: Path) -> None:
    """Skipped empty runs should remain idempotent for the same digest key."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_skipped_empty(key.value, now=now)

    result = await repository.claim_run(
        key,
        lock_owner="manual",
        now=now + timedelta(minutes=1),
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert not result.claimed
    assert result.reason == "already_skipped"
    assert result.record is not None
    assert result.record.status == DigestRunStatus.SKIPPED_EMPTY
    assert result.record.lock_owner is None
    assert result.record.locked_at is None
    assert result.record.lock_expires_at is None
    assert result.record.finished_at == now


@pytest.mark.asyncio
async def test_active_lock_blocks_duplicate_claim(tmp_path: Path) -> None:
    """Active posting locks should prevent overlapping scheduled/manual sends."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    duplicate = await repository.claim_run(
        key,
        lock_owner="manual",
        now=now + timedelta(minutes=1),
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert not duplicate.claimed
    assert duplicate.reason == "locked"


@pytest.mark.asyncio
async def test_overlapping_claims_allow_only_one_owner(tmp_path: Path) -> None:
    """Concurrent claim attempts should produce one owner and locked duplicates."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)

    results = await asyncio.gather(
        *(
            repository.claim_run(
                key,
                lock_owner=f"worker-{index}",
                now=now,
                lock_ttl_seconds=LOCK_TTL_SECONDS,
            )
            for index in range(CONCURRENT_CLAIM_ATTEMPTS)
        )
    )

    claimed = [result for result in results if result.claimed]
    locked = [result for result in results if result.reason == "locked"]
    record = await repository.get_run(key.value)

    assert len(claimed) == 1
    assert len(locked) == EXPECTED_LOCKED_DUPLICATES
    assert record is not None
    assert record.attempt_count == 1
    assert claimed[0].record is not None
    assert record.lock_owner == claimed[0].record.lock_owner


@pytest.mark.asyncio
async def test_stale_lock_can_be_reclaimed(tmp_path: Path) -> None:
    """Expired posting locks should be reclaimable and increment attempts."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=1,
    )

    reclaimed = await repository.claim_run(
        key,
        lock_owner="manual",
        now=now + timedelta(seconds=2),
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert reclaimed.claimed
    assert reclaimed.record is not None
    assert reclaimed.record.attempt_count == EXPECTED_RECLAIM_ATTEMPTS
    assert reclaimed.record.lock_owner == "manual"


@pytest.mark.asyncio
async def test_partial_delivery_blocks_full_reclaim(tmp_path: Path) -> None:
    """Partial delivery should never trigger an automatic full repost."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.record_partial_delivery(
        key.value,
        partial_message_ids=("333",),
        now=now + timedelta(minutes=1),
    )

    result = await repository.claim_run(
        key,
        lock_owner="manual",
        now=now + timedelta(minutes=2),
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert not result.claimed
    assert result.reason == "partial_delivery"
    assert result.record is not None
    assert result.record.partial_discord_message_ids == ("333",)


@pytest.mark.asyncio
async def test_failure_error_is_sanitized_and_capped(tmp_path: Path) -> None:
    """Stored errors should be sanitized and capped."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    await repository.mark_failed(
        key.value,
        retryable=True,
        error="Bearer secret-token https://example.com/path?token=secret " + ("x" * 500),
        error_kind="network",
        now=now,
    )
    record = await repository.get_run(key.value)

    assert record is not None
    assert record.status == DigestRunStatus.FAILED_RETRYABLE
    assert "secret-token" not in (record.last_error or "")
    assert "token=secret" not in (record.last_error or "")
    assert len(record.last_error or "") <= ERROR_MAX_LENGTH


@pytest.mark.asyncio
async def test_non_retryable_failure_blocks_automatic_reclaim(tmp_path: Path) -> None:
    """Non-retryable failures should remain terminal until an operator reconciles them."""
    repository = await initialized_repository(tmp_path)
    key = run_key()
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_failed(
        key.value,
        retryable=False,
        error="configuration validation failed",
        error_kind="configuration",
        now=now,
    )

    result = await repository.claim_run(
        key,
        lock_owner="scheduler",
        now=now + timedelta(minutes=1),
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )

    assert not result.claimed
    assert result.reason == "failed_non_retryable"
    assert result.record is not None
    assert result.record.status == DigestRunStatus.FAILED_NON_RETRYABLE
    assert result.record.attempt_count == 1
    assert result.record.lock_owner is None
    assert result.record.locked_at is None
    assert result.record.lock_expires_at is None
    assert result.record.finished_at == now
    assert result.record.last_error == "configuration validation failed"
    assert result.record.last_error_kind == "configuration"


@pytest.mark.asyncio
async def test_retention_preserves_unresolved_partial_deliveries(tmp_path: Path) -> None:
    """Cleanup should delete old resolved rows but keep unresolved partial rows."""
    repository = await initialized_repository(tmp_path)
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    old_success = run_key(date(2025, 12, 1))
    old_partial = run_key(date(2025, 12, 2))
    await repository.claim_run(
        old_success,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_posted(old_success.value, message_ids=("111",), now=now)
    await repository.claim_run(
        old_partial,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.record_partial_delivery(
        old_partial.value,
        partial_message_ids=("222",),
        now=now,
    )

    deleted = await repository.cleanup_old_runs(now=now)

    assert deleted == 1
    assert await repository.get_run(old_success.value) is None
    assert await repository.get_run(old_partial.value) is not None


@pytest.mark.asyncio
async def test_retention_deletes_skipped_and_old_failed_runs(tmp_path: Path) -> None:
    """Cleanup should apply the configured windows for skipped and failed states."""
    repository = await initialized_repository(tmp_path)
    now = datetime(2026, 5, 2, 7, tzinfo=KYIV)
    old_skipped = run_key(date(2025, 12, 1))
    old_non_retryable_failed = run_key(date(2025, 10, 1))
    old_retryable_failed = run_key(date(2025, 10, 2))
    recent_failed = run_key(date(2026, 1, 1))

    await repository.claim_run(
        old_skipped,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_skipped_empty(old_skipped.value, now=now)
    await repository.claim_run(
        old_non_retryable_failed,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_failed(
        old_non_retryable_failed.value,
        retryable=False,
        error="old failure",
        error_kind="configuration",
        now=now,
    )
    await repository.claim_run(
        old_retryable_failed,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_failed(
        old_retryable_failed.value,
        retryable=True,
        error="old retryable failure",
        error_kind="network",
        now=now,
    )
    await repository.claim_run(
        recent_failed,
        lock_owner="scheduler",
        now=now,
        lock_ttl_seconds=LOCK_TTL_SECONDS,
    )
    await repository.mark_failed(
        recent_failed.value,
        retryable=True,
        error="recent network failure",
        error_kind="network",
        now=now,
    )

    deleted = await repository.cleanup_old_runs(now=now)

    assert deleted == EXPECTED_RETENTION_DELETIONS
    assert await repository.get_run(old_skipped.value) is None
    assert await repository.get_run(old_non_retryable_failed.value) is None
    assert await repository.get_run(old_retryable_failed.value) is None
    assert await repository.get_run(recent_failed.value) is not None


@pytest.mark.skipif(__import__("os").name == "nt", reason="Unix permissions only")
@pytest.mark.asyncio
async def test_initialize_sets_restrictive_sqlite_permissions(tmp_path: Path) -> None:
    """SQLite state files should use restrictive permissions where chmod is supported."""
    repository = await initialized_repository(tmp_path)

    findings = repository.check_sqlite_permissions()

    assert findings == ()


@pytest.mark.skipif(__import__("os").name == "nt", reason="Unix permissions only")
@pytest.mark.asyncio
async def test_sqlite_permission_check_includes_wal_sidecars(tmp_path: Path) -> None:
    """SQLite WAL sidecars should be checked as sensitive state files."""
    repository = await initialized_repository(tmp_path)
    for state_path in sqlite_state_paths(tmp_path / "discordcalendarbot.sqlite3"):
        state_path.touch(exist_ok=True)
        state_path.chmod(0o644)

    findings = repository.check_sqlite_permissions()

    assert {finding.path.name for finding in findings} >= {
        "discordcalendarbot.sqlite3",
        "discordcalendarbot.sqlite3-wal",
        "discordcalendarbot.sqlite3-shm",
    }


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows permission warning only")
@pytest.mark.asyncio
async def test_windows_permission_check_returns_explicit_warning(tmp_path: Path) -> None:
    """Windows permission checks should report that ACL inspection is pending."""
    repository = await initialized_repository(tmp_path)

    findings = repository.check_sqlite_permissions()

    assert findings
    assert "Windows SQLite ACL inspection" in findings[0].message
