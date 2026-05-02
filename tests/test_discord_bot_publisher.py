"""Tests for Discord bot lifecycle validation and publisher safety."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from discordcalendarbot.config import BotSettings
from discordcalendarbot.discord.bot import (
    CalendarDigestBot,
    DiscordRuntime,
    DiscordRuntimeError,
    build_minimal_intents,
    validate_discord_target,
)
from discordcalendarbot.discord.formatter import DiscordMessagePart
from discordcalendarbot.discord.publisher import (
    DiscordPublisher,
    DiscordPublishError,
    allowed_mentions_as_dict,
)

GUILD_ID = 123_456
CHANNEL_ID = 234_567
ROLE_ID = 345_678
MESSAGE_ID = 456_789
TIMEOUT_SECONDS = 5


@dataclass
class FakeChannelPermissions:
    """Fake Discord channel permissions."""

    view_channel: bool = True
    send_messages: bool = True


@dataclass
class FakeRolePermissions:
    """Fake Discord role permissions."""

    administrator: bool = False
    manage_guild: bool = False
    manage_roles: bool = False
    manage_channels: bool = False
    manage_webhooks: bool = False
    kick_members: bool = False
    ban_members: bool = False
    mention_everyone: bool = False


@dataclass
class FakeMessage:
    """Fake Discord message returned by channel.send."""

    id: int


@dataclass
class SentMessage:
    """Captured fake Discord send call."""

    content: str
    allowed_mentions: object


@dataclass
class FakeChannel:
    """Fake Discord text channel."""

    id: int
    guild: FakeGuild
    permissions: FakeChannelPermissions = field(default_factory=FakeChannelPermissions)
    sent_messages: list[SentMessage] = field(default_factory=list)
    fail_on_send_number: int | None = None

    def permissions_for(self, member: object) -> FakeChannelPermissions:
        """Return fake bot permissions for this channel."""
        return self.permissions

    async def send(self, *, content: str, allowed_mentions: object) -> FakeMessage:
        """Capture a fake Discord send call."""
        self.sent_messages.append(SentMessage(content=content, allowed_mentions=allowed_mentions))
        if self.fail_on_send_number == len(self.sent_messages):
            raise RuntimeError("discord rejected message")
        return FakeMessage(id=MESSAGE_ID + len(self.sent_messages))


@dataclass
class FakeReadOnlyChannel:
    """Fake Discord channel that intentionally lacks send support."""

    id: int
    guild: FakeGuild

    def permissions_for(self, member: object) -> FakeChannelPermissions:
        """Return fake bot permissions for this channel."""
        return FakeChannelPermissions()


@dataclass
class FakeUncheckedChannel:
    """Fake Discord channel that intentionally lacks permission checks."""

    id: int
    guild: FakeGuild

    async def send(self, *, content: str, allowed_mentions: object) -> FakeMessage:
        """Pretend to send a message."""
        return FakeMessage(id=MESSAGE_ID)


@dataclass
class FakeRole:
    """Fake Discord role."""

    id: int
    guild: FakeGuild
    permissions: FakeRolePermissions = field(default_factory=FakeRolePermissions)
    name: str = "digest"
    managed: bool = False
    mentionable: bool = True
    members: tuple[object, ...] = ()
    default: bool = False

    @property
    def mention(self) -> str:
        """Return a fake Discord role mention string."""
        return f"<@&{self.id}>"

    def is_default(self) -> bool:
        """Return whether this fake role is the @everyone role."""
        return self.default


@dataclass
class FakeGuild:
    """Fake Discord guild with cached channels and roles."""

    id: int = GUILD_ID
    me: object = "bot-member"
    channels: dict[int, FakeChannel] = field(default_factory=dict)
    roles: dict[int, FakeRole] = field(default_factory=dict)

    def get_channel(self, channel_id: int) -> FakeChannel | None:
        """Return a fake channel from cache."""
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id: int) -> FakeChannel:
        """Fetch a fake channel or fail like Discord HTTP would."""
        if channel := self.channels.get(channel_id):
            return channel
        raise LookupError(channel_id)

    def get_role(self, role_id: int) -> FakeRole | None:
        """Return a fake role from cache."""
        return self.roles.get(role_id)


class FakeClient:
    """Fake Discord client with one cached guild."""

    def __init__(self, guild: FakeGuild | None) -> None:
        """Store the fake guild."""
        self._guild = guild

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        """Return a cached fake guild."""
        if self._guild is not None and self._guild.id == guild_id:
            return self._guild
        return None

    async def fetch_guild(self, guild_id: int) -> FakeGuild:
        """Fetch a fake guild or fail like Discord HTTP would."""
        if self._guild is not None and self._guild.id == guild_id:
            return self._guild
        raise LookupError(guild_id)


class FakeCalendarDigestBot(CalendarDigestBot):
    """Calendar bot subclass with fake guild lookup for lifecycle tests."""

    def __init__(
        self,
        settings: BotSettings,
        guild: FakeGuild,
        *,
        scheduler_start_hook: object,
        shutdown_hook: object,
    ) -> None:
        """Create a fake-backed calendar bot."""
        super().__init__(
            settings,
            scheduler_start_hook=scheduler_start_hook,
            shutdown_hook=shutdown_hook,
        )
        self._fake_guild = guild

    def get_guild(self, guild_id: int) -> FakeGuild | None:
        """Return the fake guild from the Discord cache path."""
        if self._fake_guild.id == guild_id:
            return self._fake_guild
        return None


def make_settings(
    tmp_path: Path,
    *,
    enable_role_mention: bool = False,
    role_id: int | None = None,
) -> BotSettings:
    """Build test settings without reading environment variables."""
    return BotSettings(
        discord_bot_token=f"token-{tmp_path.name}",
        discord_guild_id=GUILD_ID,
        discord_channel_id=CHANNEL_ID,
        google_credentials_path=tmp_path / "credentials.json",
        google_token_path=tmp_path / "token.json",
        google_calendar_ids=("calendar@example.com",),
        event_tag="#discord-daily",
        bot_timezone_name="Europe/Kiev",
        bot_timezone=ZoneInfo("Europe/Kiev"),
        daily_digest_time=time(hour=7),
        sqlite_path=tmp_path / "discordcalendarbot.sqlite3",
        enable_role_mention=enable_role_mention,
        discord_role_mention_id=role_id,
        discord_publish_timeout_seconds=TIMEOUT_SECONDS,
    )


def make_guild_with_channel() -> tuple[FakeGuild, FakeChannel]:
    """Build a fake guild containing the configured channel."""
    guild = FakeGuild()
    channel = FakeChannel(id=CHANNEL_ID, guild=guild)
    guild.channels[channel.id] = channel
    return guild, channel


def test_minimal_intents_disable_privileged_message_content() -> None:
    """Minimal intents should not request privileged message content."""
    intents = build_minimal_intents()

    assert intents.guilds
    assert not intents.members
    assert not intents.message_content


@pytest.mark.asyncio
async def test_validate_target_accepts_configured_channel(tmp_path: Path) -> None:
    """Target validation should accept the configured guild/channel pair."""
    guild, channel = make_guild_with_channel()
    settings = make_settings(tmp_path)

    target = await validate_discord_target(FakeClient(guild), settings)

    assert target.guild is guild
    assert target.channel is channel
    assert target.role is None


@pytest.mark.asyncio
async def test_validate_target_rejects_missing_send_permission(tmp_path: Path) -> None:
    """Target validation should fail if the bot cannot send to the channel."""
    guild, channel = make_guild_with_channel()
    channel.permissions = FakeChannelPermissions(send_messages=False)
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="send messages"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_target_rejects_missing_guild(tmp_path: Path) -> None:
    """Target validation should fail closed when the configured guild is absent."""
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="guild not found"):
        await validate_discord_target(FakeClient(None), settings)


@pytest.mark.asyncio
async def test_validate_target_rejects_missing_channel(tmp_path: Path) -> None:
    """Target validation should fail closed when the configured channel is absent."""
    guild = FakeGuild()
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="channel not found"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_target_rejects_channel_from_another_guild(tmp_path: Path) -> None:
    """Target validation should reject channels outside the configured guild."""
    guild = FakeGuild()
    other_guild = FakeGuild(id=999_999)
    guild.channels[CHANNEL_ID] = FakeChannel(id=CHANNEL_ID, guild=other_guild)
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="does not belong"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_target_rejects_missing_view_permission(tmp_path: Path) -> None:
    """Target validation should fail if the bot cannot view the channel."""
    guild, channel = make_guild_with_channel()
    channel.permissions = FakeChannelPermissions(view_channel=False)
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="view"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_target_rejects_non_sendable_channel(tmp_path: Path) -> None:
    """Target validation should reject channels that cannot receive messages."""
    guild = FakeGuild()
    guild.channels[CHANNEL_ID] = FakeReadOnlyChannel(id=CHANNEL_ID, guild=guild)
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="cannot receive"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_target_rejects_channel_without_permission_checks(tmp_path: Path) -> None:
    """Target validation should reject channels when permissions cannot be checked."""
    guild = FakeGuild()
    guild.channels[CHANNEL_ID] = FakeUncheckedChannel(id=CHANNEL_ID, guild=guild)
    settings = make_settings(tmp_path)

    with pytest.raises(DiscordRuntimeError, match="permissions cannot be checked"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_privileged_roles(tmp_path: Path) -> None:
    """Role validation should reject elevated roles for automatic mentions."""
    guild, _channel = make_guild_with_channel()
    guild.roles[ROLE_ID] = FakeRole(
        id=ROLE_ID,
        guild=guild,
        permissions=FakeRolePermissions(manage_guild=True),
    )
    settings = make_settings(tmp_path, enable_role_mention=True, role_id=ROLE_ID)

    with pytest.raises(DiscordRuntimeError, match="privileged permissions"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_missing_role_id(tmp_path: Path) -> None:
    """Role validation should fail closed when no role ID is configured."""
    guild, _channel = make_guild_with_channel()
    settings = make_settings(tmp_path, enable_role_mention=True)

    with pytest.raises(DiscordRuntimeError, match="without a configured role ID"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_missing_role(tmp_path: Path) -> None:
    """Role validation should fail closed when the configured role is absent."""
    guild, _channel = make_guild_with_channel()
    settings = make_settings(tmp_path, enable_role_mention=True, role_id=ROLE_ID)

    with pytest.raises(DiscordRuntimeError, match="role not found"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_wrong_guild_role(tmp_path: Path) -> None:
    """Role validation should reject roles that belong to another guild."""
    guild, _channel = make_guild_with_channel()
    other_guild = FakeGuild(id=999_999)
    guild.roles[ROLE_ID] = FakeRole(id=ROLE_ID, guild=other_guild)
    settings = make_settings(tmp_path, enable_role_mention=True, role_id=ROLE_ID)

    with pytest.raises(DiscordRuntimeError, match="role does not belong"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_everyone_role(tmp_path: Path) -> None:
    """Role validation should reject @everyone for automatic mentions."""
    guild, _channel = make_guild_with_channel()
    guild.roles[ROLE_ID] = FakeRole(id=ROLE_ID, guild=guild, default=True)
    settings = make_settings(tmp_path, enable_role_mention=True, role_id=ROLE_ID)

    with pytest.raises(DiscordRuntimeError, match="@everyone"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_managed_role(tmp_path: Path) -> None:
    """Role validation should reject managed integration roles."""
    guild, _channel = make_guild_with_channel()
    guild.roles[ROLE_ID] = FakeRole(id=ROLE_ID, guild=guild, managed=True)
    settings = make_settings(tmp_path, enable_role_mention=True, role_id=ROLE_ID)

    with pytest.raises(DiscordRuntimeError, match="managed"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_validate_role_rejects_unmentionable_role(tmp_path: Path) -> None:
    """Role validation should reject roles that cannot be explicitly mentioned."""
    guild, _channel = make_guild_with_channel()
    guild.roles[ROLE_ID] = FakeRole(id=ROLE_ID, guild=guild, mentionable=False)
    settings = make_settings(tmp_path, enable_role_mention=True, role_id=ROLE_ID)

    with pytest.raises(DiscordRuntimeError, match="mentionable"):
        await validate_discord_target(FakeClient(guild), settings)


@pytest.mark.asyncio
async def test_publisher_disables_mentions_by_default() -> None:
    """Publisher should disable all mention parsing unless a role is configured."""
    _guild, channel = make_guild_with_channel()
    publisher = DiscordPublisher(channel, timeout_seconds=TIMEOUT_SECONDS)

    result = await publisher.publish((DiscordMessagePart(content="@everyone hello"),))

    assert result.message_ids == (str(MESSAGE_ID + 1),)
    payload = allowed_mentions_as_dict(channel.sent_messages[0].allowed_mentions)
    assert payload["parse"] == []


@pytest.mark.asyncio
async def test_publisher_allows_only_configured_role_on_first_message() -> None:
    """Publisher should prepend the configured role once and allow only that role."""
    guild, channel = make_guild_with_channel()
    role = FakeRole(id=ROLE_ID, guild=guild)
    publisher = DiscordPublisher(channel, timeout_seconds=TIMEOUT_SECONDS, role=role)

    result = await publisher.publish(
        (
            DiscordMessagePart(content="first"),
            DiscordMessagePart(content="second"),
        )
    )

    assert result.message_ids == (str(MESSAGE_ID + 1), str(MESSAGE_ID + 2))
    assert channel.sent_messages[0].content == f"{role.mention}\nfirst"
    assert channel.sent_messages[1].content == "second"
    first_payload = allowed_mentions_as_dict(channel.sent_messages[0].allowed_mentions)
    second_payload = allowed_mentions_as_dict(channel.sent_messages[1].allowed_mentions)
    assert first_payload["roles"] == [ROLE_ID]
    assert second_payload["parse"] == []
    assert "roles" not in second_payload
    assert "everyone" not in first_payload.get("parse", [])
    assert "users" not in first_payload.get("parse", [])


@pytest.mark.asyncio
async def test_publisher_preserves_accepted_ids_on_partial_failure() -> None:
    """Publisher errors should expose accepted IDs for partial-delivery recording."""
    _guild, channel = make_guild_with_channel()
    channel.fail_on_send_number = 2
    publisher = DiscordPublisher(channel, timeout_seconds=TIMEOUT_SECONDS)

    with pytest.raises(DiscordPublishError) as error_info:
        await publisher.publish(
            (
                DiscordMessagePart(content="first"),
                DiscordMessagePart(content="second"),
            )
        )

    assert error_info.value.accepted_message_ids == (str(MESSAGE_ID + 1),)


@pytest.mark.asyncio
async def test_bot_ready_starts_scheduler_once_and_shutdown_once(tmp_path: Path) -> None:
    """Readiness should start the scheduler once and shutdown should run once."""
    guild, _channel = make_guild_with_channel()
    settings = make_settings(tmp_path)
    starts = 0
    shutdowns = 0

    async def start_scheduler(runtime: DiscordRuntime) -> None:
        """Record scheduler startup."""
        nonlocal starts
        assert runtime.target.channel is guild.channels[CHANNEL_ID]
        assert runtime.publisher is not None
        starts += 1

    async def shutdown() -> None:
        """Record shutdown."""
        nonlocal shutdowns
        shutdowns += 1

    bot = FakeCalendarDigestBot(
        settings,
        guild,
        scheduler_start_hook=start_scheduler,
        shutdown_hook=shutdown,
    )

    await bot.on_ready()
    await bot.on_ready()
    await bot.close()
    await bot.close()

    assert starts == 1
    assert shutdowns == 1
    assert bot.publisher is not None


@pytest.mark.asyncio
async def test_concurrent_ready_events_start_scheduler_once(tmp_path: Path) -> None:
    """Overlapping ready events should not race the scheduler startup guard."""
    guild, _channel = make_guild_with_channel()
    settings = make_settings(tmp_path)
    starts = 0

    async def start_scheduler(_runtime: DiscordRuntime) -> None:
        """Record scheduler startup after yielding to expose races."""
        nonlocal starts
        starts += 1
        await asyncio.sleep(0)

    async def shutdown() -> None:
        """No-op shutdown hook."""

    bot = FakeCalendarDigestBot(
        settings,
        guild,
        scheduler_start_hook=start_scheduler,
        shutdown_hook=shutdown,
    )

    await asyncio.gather(bot.on_ready(), bot.on_ready(), bot.on_ready())
    await bot.close()

    assert starts == 1
