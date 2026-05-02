"""Command line interface for local operator commands."""

from __future__ import annotations

import argparse
import asyncio
import sys
from typing import cast

from discordcalendarbot import __version__
from discordcalendarbot.app import RuntimeApplication, build_application
from discordcalendarbot.operator_commands import (
    load_operator_settings,
    parse_target_date,
    run_check_google_calendar_command,
    run_dry_run_command,
    run_google_auth_login_command,
    run_reconcile_digest_command,
    run_send_digest_command,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(prog="discordcalendarbot")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    google_auth = subparsers.add_parser("google-auth-login")
    google_auth.add_argument("--force", action="store_true")
    google_auth.add_argument("--confirm-write-token")
    google_auth.set_defaults(handler=handle_google_auth_login)

    dry_run = subparsers.add_parser("dry-run")
    dry_run.add_argument("--date", required=True)
    dry_run.add_argument("--redact", action="store_true")
    dry_run.add_argument("--summary-only", action="store_true")
    dry_run.set_defaults(handler=handle_dry_run)

    check_google = subparsers.add_parser("check-google-calendar")
    check_google.add_argument("--date", required=True)
    check_google.set_defaults(handler=handle_check_google_calendar)

    send_digest = subparsers.add_parser("send-digest")
    send_digest.add_argument("--date", required=True)
    send_digest.add_argument("--channel-id", type=int)
    send_digest.add_argument("--force", action="store_true")
    send_digest.add_argument("--confirm-force")
    send_digest.set_defaults(handler=handle_send_digest)

    reconcile = subparsers.add_parser("reconcile-digest")
    reconcile.add_argument("--date", required=True)
    reconcile.add_argument("--message-id", action="append", required=True)
    reconcile.add_argument("--partial", action="store_true")
    reconcile.add_argument("--confirm-reconcile")
    reconcile.set_defaults(handler=handle_reconcile_digest)

    parser.set_defaults(handler=handle_run)
    return parser


def handle_run(_args: argparse.Namespace) -> int:
    """Start the long-running Discord calendar bot."""
    settings = load_operator_settings()
    application = cast(RuntimeApplication, build_application(settings))
    asyncio.run(application.run())
    return 0


def handle_google_auth_login(args: argparse.Namespace) -> int:
    """Handle the OAuth bootstrap command."""
    settings = load_operator_settings()
    result = asyncio.run(
        run_google_auth_login_command(
            settings,
            force=args.force,
            confirm_write_token=args.confirm_write_token,
            output=sys.stdout,
        )
    )
    if result.message and result.exit_code:
        sys.stderr.write(result.message + "\n")
    return result.exit_code


def handle_dry_run(args: argparse.Namespace) -> int:
    """Handle dry-run preview rendering."""
    settings = load_operator_settings()
    result = asyncio.run(
        run_dry_run_command(
            settings,
            target_date=parse_target_date(args.date),
            redact=args.redact,
            summary_only=args.summary_only,
            output=sys.stdout,
        )
    )
    return result.exit_code


def handle_check_google_calendar(args: argparse.Namespace) -> int:
    """Handle Google Calendar read-path checks."""
    settings = load_operator_settings()
    result = asyncio.run(
        run_check_google_calendar_command(
            settings,
            target_date=parse_target_date(args.date),
            output=sys.stdout,
        )
    )
    return result.exit_code


def handle_send_digest(args: argparse.Namespace) -> int:
    """Handle local digest sending."""
    settings = load_operator_settings()
    result = asyncio.run(
        run_send_digest_command(
            settings,
            target_date=parse_target_date(args.date),
            force=args.force,
            channel_id=args.channel_id,
            confirm_force=args.confirm_force,
            output=sys.stdout,
        )
    )
    if result.message and result.exit_code:
        sys.stderr.write(result.message + "\n")
    return result.exit_code


def handle_reconcile_digest(args: argparse.Namespace) -> int:
    """Handle digest reconciliation."""
    settings = load_operator_settings()
    result = asyncio.run(
        run_reconcile_digest_command(
            settings,
            target_date=parse_target_date(args.date),
            message_ids=tuple(args.message_id),
            partial=args.partial,
            confirm_reconcile=args.confirm_reconcile,
            output=sys.stdout,
        )
    )
    if result.message and result.exit_code:
        sys.stderr.write(result.message + "\n")
    return result.exit_code


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))
