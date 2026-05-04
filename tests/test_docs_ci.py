"""Tests for documentation and CI coverage."""

from __future__ import annotations

from pathlib import Path


def test_ci_workflow_runs_required_quality_gates() -> None:
    """CI should run the same local checks plus supply-chain scans."""
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "fetch-depth: 0" in workflow
    assert "uv run ruff check ." in workflow
    assert "uv run ruff format --check ." in workflow
    assert "uv run pytest" in workflow
    assert "uv run --with pip-audit pip-audit --local" in workflow
    assert "gitleaks" in workflow


def test_deployment_guide_documents_required_operations_topics() -> None:
    """Deployment docs should cover setup, hardening, recovery, and privacy topics."""
    guide = Path("docs/deployment.md").read_text(encoding="utf-8").casefold()
    required_topics = (
        "discord setup",
        "google oauth setup",
        "environment variables",
        "python-dotenv",
        "windows deployment",
        "linux deployment",
        "dry-run output can contain private calendar titles",
        "rotate the discord bot token",
        "revoke the google oauth token",
        "encrypted backups",
        "log_file_path",
        "log_backup_count=2",
        "one active log file plus two rotated backups",
        "journalctl",
        "safe update procedure",
        "git status --short",
        "uv sync --locked",
        "rollback",
        "git clean -fdx",
        ".env",
        "credentials.json",
        "token.json",
        "*.sqlite3",
        "*.sqlite3-wal",
        "*.sqlite3-shm",
        "logs",
        "retention",
        "privacy",
        "ci",
    )

    for topic in required_topics:
        assert topic in guide


def test_safe_update_section_documents_runtime_preservation_workflow() -> None:
    """Safe update guidance should be complete inside its dedicated section."""
    guide = Path("docs/deployment.md").read_text(encoding="utf-8").casefold()
    safe_update = section_between(
        guide,
        "## safe update procedure",
        "## operator commands",
    )
    required_topics = (
        "git status --short",
        "git rev-parse --short head",
        "uv sync --locked",
        "check-google-calendar",
        "check-discord",
        "check-full-digest",
        "rollback",
        "systemctl stop discordcalendarbot",
        "systemctl start discordcalendarbot",
        "windows rollback",
        "git clean -fdx",
        ".env",
        "credentials.json",
        "token.json",
        "*.sqlite3",
        "*.sqlite3-wal",
        "*.sqlite3-shm",
        "logs",
        "encrypted",
    )

    for topic in required_topics:
        assert topic in safe_update


def test_readme_links_deployment_and_ci_guidance() -> None:
    """README should point operators to deployment and CI details."""
    readme = Path("README.md").read_text(encoding="utf-8").casefold()

    assert "docs/deployment.md" in readme
    assert "continuous integration" in readme
    assert "encrypted backups" in readme
    assert "empty_digest_text" in readme
    assert "log_file_path" in readme
    assert "one active file plus two rotated backups" in readme
    assert "safe update procedure" in readme
    assert "runtime data" in readme


def section_between(text: str, start_marker: str, end_marker: str) -> str:
    """Return the text section between two markdown headers."""
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    return text[start:end]
