"""Temporary Discord publisher for local operator commands."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

from discordcalendarbot.config import BotSettings
from discordcalendarbot.discord.bot import DiscordRuntime, start_discord_bot
from discordcalendarbot.discord.formatter import DiscordMessagePart
from discordcalendarbot.discord.publisher import DiscordPublishResult


class DiscordCliPublishError(RuntimeError):
    """Raised when local Discord publishing cannot reach the ready publish hook."""


class DiscordCliPublisher:
    """Publish through a temporary gateway-ready Discord bot for one local command."""

    def __init__(self, settings: BotSettings) -> None:
        """Store settings used for Discord authentication and target validation."""
        self._settings = settings

    async def publish(self, message_parts: Sequence[DiscordMessagePart]) -> DiscordPublishResult:
        """Connect to Discord, validate readiness, publish all parts, and close."""
        result_future = asyncio.get_running_loop().create_future()

        async def start_and_publish(runtime: DiscordRuntime) -> None:
            """Publish after Discord readiness validation succeeds."""
            try:
                result_future.set_result(await runtime.publisher.publish(message_parts))
            except Exception as error:
                result_future.set_exception(error)

        bot_task = asyncio.create_task(
            start_discord_bot(
                self._settings,
                scheduler_start_hook=start_and_publish,
            )
        )
        try:
            done, pending = await asyncio.wait(
                {result_future, bot_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if bot_task in done and not result_future.done():
                await bot_task
                raise DiscordCliPublishError("Discord bot exited before publishing")
            for pending_task in pending:
                pending_task.cancel()
            return await result_future
        finally:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass
