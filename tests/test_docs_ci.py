"""Tests for documentation and CI coverage."""

from __future__ import annotations

from pathlib import Path


def test_ci_workflow_runs_required_quality_gates() -> None:
    """CI should run the same local checks plus supply-chain scans."""
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

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
        "retention",
        "privacy",
        "ci",
    )

    for topic in required_topics:
        assert topic in guide


def test_readme_links_deployment_and_ci_guidance() -> None:
    """README should point operators to deployment and CI details."""
    readme = Path("README.md").read_text(encoding="utf-8").casefold()

    assert "docs/deployment.md" in readme
    assert "continuous integration" in readme
    assert "encrypted backups" in readme
    assert "empty_digest_text" in readme
