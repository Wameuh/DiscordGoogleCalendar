"""Sanitize untrusted calendar text before rendering Discord messages."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

MENTION_PATTERN = re.compile(r"@(?=everyone|here|[!&]?\d{10,}|[A-Za-z0-9_.-])")
CHANNEL_PATTERN = re.compile(r"<#(\d{10,})>")
CUSTOM_EMOJI_PATTERN = re.compile(r"<a?:([A-Za-z0-9_]+):(\d{10,})>")
MASKED_LINK_PATTERN = re.compile(r"\[([^\]]+)]\(([^)]+)\)")
MARKDOWN_CHARS_PATTERN = re.compile(r"([\\`*_{}\[\]()#+.!|>~-])")
BIDI_CONTROL_CATEGORIES = {"Cf", "Cc"}


@dataclass(frozen=True)
class DiscordContentSanitizer:
    """Neutralize mentions, markdown, masked links, and control characters."""

    max_field_chars: int = 200

    def sanitize(self, value: object) -> str:
        """Return a Discord-safe, length-capped string."""
        text = str(value)
        text = "".join(
            replacement
            for character in text
            if (replacement := sanitize_character(character)) is not None
        )
        text = MASKED_LINK_PATTERN.sub(r"\1 (\2)", text)
        text = CUSTOM_EMOJI_PATTERN.sub(r":\1:", text)
        text = CHANNEL_PATTERN.sub("#channel-\u200b\\1", text)
        text = MENTION_PATTERN.sub("@\u200b", text)
        text = MARKDOWN_CHARS_PATTERN.sub(r"\\\1", text)
        text = " ".join(text.split())
        if len(text) > self.max_field_chars:
            return f"{text[: self.max_field_chars - 3]}..."
        return text


def sanitize_character(character: str) -> str | None:
    """Return a safe replacement for one character, or None to drop it."""
    category = unicodedata.category(character)
    if category in BIDI_CONTROL_CATEGORIES:
        if character in {"\n", "\r", "\t"}:
            return " "
        return None
    return character
