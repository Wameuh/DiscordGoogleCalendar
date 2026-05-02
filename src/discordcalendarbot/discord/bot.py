"""Discord bot lifecycle, validation, and scheduler startup guard."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import discord

from discordcalendarbot.config import BotSettings
from discordcalendarbot.discord.publisher import DiscordPublisher

logger = logging.getLogger(__name__)

SchedulerStartHook = Callable[["DiscordRuntime"], Awaitable[None] | None]
ShutdownHook = Callable[[], Awaitable[None] | None]


class DiscordRuntimeError(RuntimeError):
    """Raised when Discord startup validation fails."""


@dataclass(frozen=True)
class DiscordTarget:
    """Validated Discord startup target."""

    guild: Any
    channel: Any
    role: Any | None = None


@dataclass(frozen=True)
class DiscordRuntime:
    """Validated Discord runtime dependencies for digest service wiring."""

    target: DiscordTarget
    publisher: DiscordPublisher


class SupportsPermissions(Protocol):
    """Subset of Discord permissions used by startup validation."""

    view_channel: bool
    send_messages: bool


class SupportsDiscordGuild(Protocol):
    """Subset of Discord guild behavior used by startup validation."""

    id: int
    me: Any

    def get_channel(self, channel_id: int) -> Any | None:
        """Return a cached channel."""

    async def fetch_channel(self, channel_id: int) -> Any:
        """Fetch a channel by ID."""

    def get_role(self, role_id: int) -> Any | None:
        """Return a cached role."""


class SupportsDiscordClient(Protocol):
    """Subset of Discord client behavior used by startup validation."""

    def get_guild(self, guild_id: int) -> SupportsDiscordGuild | None:
        """Return a cached guild."""

    async def fetch_guild(self, guild_id: int) -> SupportsDiscordGuild:
        """Fetch a guild by ID."""


class CalendarDigestBot(discord.Client):
    """Long-running Discord client for the calendar digest bot."""

    def __init__(
        self,
        settings: BotSettings,
        *,
        scheduler_start_hook: SchedulerStartHook,
        shutdown_hook: ShutdownHook | None = None,
    ) -> None:
        """Create the Discord client with minimal gateway intents."""
        super().__init__(intents=build_minimal_intents())
        self._settings = settings
        self._scheduler_start_hook = scheduler_start_hook
        self._shutdown_hook = shutdown_hook
        self._scheduler_started = False
        self._scheduler_start_lock = asyncio.Lock()
        self._shutdown_called = False
        self.target: DiscordTarget | None = None
        self.publisher: DiscordPublisher | None = None

    async def on_ready(self) -> None:
        """Validate Discord target and start the scheduler once after readiness."""
        target = await validate_discord_target(self, self._settings)
        self.target = target
        self.publisher = DiscordPublisher(
            target.channel,
            timeout_seconds=self._settings.discord_publish_timeout_seconds,
            role=target.role,
        )
        await self._start_scheduler_once(DiscordRuntime(target=target, publisher=self.publisher))

    async def _start_scheduler_once(self, runtime: DiscordRuntime) -> None:
        """Start the scheduler once, including during overlapping ready events."""
        async with self._scheduler_start_lock:
            if self._scheduler_started:
                return
            await maybe_await(self._scheduler_start_hook(runtime))
            self._scheduler_started = True
        logger.info(
            "Discord ready; scheduler started",
            extra={
                "guild_id": self._settings.discord_guild_id,
                "channel_id": self._settings.discord_channel_id,
            },
        )

    async def close(self) -> None:
        """Run shutdown hooks before closing the Discord connection."""
        if self._shutdown_hook is not None and not self._shutdown_called:
            self._shutdown_called = True
            await maybe_await(self._shutdown_hook())
        await super().close()


def build_minimal_intents() -> discord.Intents:
    """Return gateway intents needed for one-guild channel validation."""
    intents = discord.Intents.none()
    intents.guilds = True
    return intents


async def start_discord_bot(
    settings: BotSettings,
    *,
    scheduler_start_hook: SchedulerStartHook,
    shutdown_hook: ShutdownHook | None = None,
) -> None:
    """Start the Discord client with the configured bot token."""
    bot = CalendarDigestBot(
        settings,
        scheduler_start_hook=scheduler_start_hook,
        shutdown_hook=shutdown_hook,
    )
    try:
        await bot.start(settings.discord_bot_token)
    finally:
        await bot.close()


async def validate_discord_target(
    client: SupportsDiscordClient,
    settings: BotSettings,
) -> DiscordTarget:
    """Validate the configured guild, channel, permissions, and optional role."""
    guild = await resolve_guild(client, settings.discord_guild_id)
    channel = await resolve_channel(guild, settings.discord_channel_id)
    validate_channel_guild(channel, settings.discord_guild_id)
    validate_channel_permissions(guild, channel)
    role = validate_configured_role(guild, settings) if settings.enable_role_mention else None
    if role is not None:
        logger.info(
            "Validated Discord role mention target",
            extra={
                "guild_id": settings.discord_guild_id,
                "role_id": settings.discord_role_mention_id,
                "role_name": getattr(role, "name", "<unknown>"),
                "role_member_count": len(getattr(role, "members", ()) or ()),
            },
        )
    return DiscordTarget(guild=guild, channel=channel, role=role)


async def resolve_guild(
    client: SupportsDiscordClient,
    guild_id: int,
) -> SupportsDiscordGuild:
    """Resolve a configured guild from cache or Discord HTTP."""
    guild = client.get_guild(guild_id)
    if guild is not None:
        return guild
    try:
        return await client.fetch_guild(guild_id)
    except Exception as error:
        raise DiscordRuntimeError(f"Configured Discord guild not found: {guild_id}") from error


async def resolve_channel(guild: SupportsDiscordGuild, channel_id: int) -> Any:
    """Resolve a configured channel from cache or Discord HTTP."""
    channel = guild.get_channel(channel_id)
    if channel is not None:
        return channel
    try:
        return await guild.fetch_channel(channel_id)
    except Exception as error:
        raise DiscordRuntimeError(f"Configured Discord channel not found: {channel_id}") from error


def validate_channel_guild(channel: Any, guild_id: int) -> None:
    """Validate that the channel belongs to the configured guild."""
    channel_guild = getattr(channel, "guild", None)
    channel_guild_id = getattr(channel_guild, "id", None)
    if channel_guild_id != guild_id:
        raise DiscordRuntimeError("Configured Discord channel does not belong to the guild")


def validate_channel_permissions(guild: SupportsDiscordGuild, channel: Any) -> None:
    """Validate that the bot can view and send messages in the channel."""
    if not hasattr(channel, "send"):
        raise DiscordRuntimeError("Configured Discord channel cannot receive messages")
    permissions_for = getattr(channel, "permissions_for", None)
    if permissions_for is None:
        raise DiscordRuntimeError("Configured Discord channel permissions cannot be checked")
    permissions = permissions_for(guild.me)
    if not getattr(permissions, "view_channel", False):
        raise DiscordRuntimeError("Bot cannot view the configured Discord channel")
    if not getattr(permissions, "send_messages", False):
        raise DiscordRuntimeError("Bot cannot send messages to the configured Discord channel")


def validate_configured_role(guild: SupportsDiscordGuild, settings: BotSettings) -> Any:
    """Validate the configured automatic mention role."""
    role_id = settings.discord_role_mention_id
    if role_id is None:
        raise DiscordRuntimeError("Role mention is enabled without a configured role ID")
    role = guild.get_role(role_id)
    if role is None:
        raise DiscordRuntimeError(f"Configured Discord role not found: {role_id}")
    role_guild_id = getattr(getattr(role, "guild", None), "id", None)
    if role_guild_id != settings.discord_guild_id:
        raise DiscordRuntimeError("Configured Discord role does not belong to the guild")
    is_default = getattr(role, "is_default", None)
    if callable(is_default) and is_default():
        raise DiscordRuntimeError("Configured Discord role cannot be @everyone")
    if getattr(role, "managed", False):
        raise DiscordRuntimeError("Configured Discord role cannot be managed")
    if is_privileged_role(role):
        raise DiscordRuntimeError("Configured Discord role has privileged permissions")
    if not getattr(role, "mentionable", False):
        raise DiscordRuntimeError("Configured Discord role must be mentionable")
    return role


def is_privileged_role(role: Any) -> bool:
    """Return whether a role has elevated operational permissions."""
    permissions = getattr(role, "permissions", None)
    privileged_flags = (
        "administrator",
        "manage_guild",
        "manage_roles",
        "manage_channels",
        "manage_webhooks",
        "kick_members",
        "ban_members",
        "mention_everyone",
    )
    return any(getattr(permissions, flag, False) for flag in privileged_flags)


async def maybe_await(value: Awaitable[None] | None) -> None:
    """Await hook results only when the hook returns an awaitable."""
    if inspect.isawaitable(value):
        await value
