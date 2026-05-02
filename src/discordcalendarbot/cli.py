"""Command line interface for local operator commands."""

from __future__ import annotations

import argparse

from discordcalendarbot import __version__
from discordcalendarbot.app import build_application


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level command parser."""
    parser = argparse.ArgumentParser(prog="discordcalendarbot")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.set_defaults(handler=handle_run)
    return parser


def handle_run(_args: argparse.Namespace) -> int:
    """Handle the default command until runtime startup is implemented."""
    build_application()
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line interface."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))
