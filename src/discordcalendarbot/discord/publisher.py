"""Mention-safe Discord publisher."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import discord

from discordcalendarbot.discord.formatter import DiscordMessagePart


class DiscordPublishError(RuntimeError):
    """Raised when Discord publishing fails before all message parts are accepted."""

    def __init__(self, message: str, *, accepted_message_ids: tuple[str, ...] = ()) -> None:
        """Store accepted message IDs for partial-delivery reconciliation."""
        super().__init__(message)
        self.accepted_message_ids = accepted_message_ids


@dataclass(frozen=True)
class DiscordPublishResult:
    """Discord publish result with accepted message IDs."""

    message_ids: tuple[str, ...]


class SupportsDiscordMessage(Protocol):
    """Small protocol for Discord message objects returned by send."""

    id: int


class SupportsDiscordChannel(Protocol):
    """Small protocol for channels that can send Discord messages."""

    async def send(
        self,
        *,
        content: str,
        allowed_mentions: discord.AllowedMentions,
    ) -> SupportsDiscordMessage:
        """Send a message to Discord."""


class SupportsDiscordRole(Protocol):
    """Small protocol for role mention behavior."""

    id: int
    mention: str


class DiscordPublisher:
    """Publish already-formatted digest parts to one configured Discord channel."""

    def __init__(
        self,
        channel: SupportsDiscordChannel,
        *,
        timeout_seconds: int,
        role: SupportsDiscordRole | None = None,
    ) -> None:
        """Store the channel and mention policy."""
        self._channel = channel
        self._timeout_seconds = timeout_seconds
        self._role = role

    async def publish(
        self,
        message_parts: Sequence[DiscordMessagePart],
    ) -> DiscordPublishResult:
        """Publish all message parts and return the accepted Discord message IDs."""
        accepted_ids: list[str] = []
        for index, part in enumerate(message_parts):
            include_role = index == 0
            try:
                message = await asyncio.wait_for(
                    self._channel.send(
                        content=self._content_for_part(part, include_role=include_role),
                        allowed_mentions=self._allowed_mentions(include_role=include_role),
                    ),
                    timeout=self._timeout_seconds,
                )
            except Exception as error:
                raise DiscordPublishError(
                    "Discord publish failed",
                    accepted_message_ids=tuple(accepted_ids),
                ) from error
            accepted_ids.append(str(message.id))
        return DiscordPublishResult(message_ids=tuple(accepted_ids))

    def _content_for_part(self, part: DiscordMessagePart, *, include_role: bool) -> str:
        """Return message content with the configured role prepended once."""
        if self._role is None or not include_role:
            return part.content
        return f"{self._role.mention}\n{part.content}"

    def _allowed_mentions(self, *, include_role: bool) -> discord.AllowedMentions:
        """Return Discord allowed mention policy for the current message."""
        if self._role is None or not include_role:
            return discord.AllowedMentions.none()
        return discord.AllowedMentions(
            everyone=False,
            users=False,
            roles=[self._role],
            replied_user=False,
        )


def allowed_mentions_as_dict(allowed_mentions: discord.AllowedMentions) -> dict[str, Any]:
    """Return Discord's serializable allowed_mentions payload for tests and logging."""
    return allowed_mentions.to_dict()
