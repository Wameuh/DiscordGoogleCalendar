# Agent 4 - Integration Test Reviewer

Status: Changes requested
Reviewed TODO: TODO 4 - Tag filtering and digest formatting
Review iteration: 1
Reviewed files:

- `ARCHITECTURE.md`
- `.cursor/rules/python-best-practices.mdc`
- `.cursor/rules/python-fastapi.mdc`
- `src/discordcalendarbot/calendar/tag_filter.py`
- `src/discordcalendarbot/domain/digest.py`
- `src/discordcalendarbot/discord/sanitizer.py`
- `src/discordcalendarbot/discord/url_policy.py`
- `src/discordcalendarbot/discord/formatter.py`
- `tests/test_tag_digest_discord_formatting.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/discord/formatter.py:101`
  Issue: Multipart numbering is added after `split_message_lines` has enforced `max_chars`, so returned `DiscordMessagePart.content` can exceed the configured message limit once `(index/total)\n` is prepended.
  Impact: The later Discord publisher/service boundary will receive payloads that can violate `MAX_DISCORD_MESSAGE_CHARS`, especially when configuration allows values near Discord's hard 2000-character limit. This can make a correctly filtered and sanitized digest fail during publish, leaving idempotency and partial-delivery logic to handle an avoidable formatter contract breach.
  Required change: Ensure every returned message part remains `<= max_chars` after numbering, either by reserving prefix space before splitting multipart digests or by applying a second bounded split after prefixes are known. Add an integration-style regression assertion that all formatted parts respect the configured limit after numbering.

## Approval Notes

The changed modules otherwise integrate cleanly for TODO 4's current scope. `TagFilter` produces cleaned `CalendarEvent` values without mutating the source events, `build_daily_digest` sorts events and carries empty-digest posting decisions in a service-friendly data object, and `DigestFormatter.format_digest` returns publisher-ready `DiscordMessagePart` objects while returning an empty tuple when `should_post` is false.

The sanitizer and URL policy boundaries fit the architecture: event text is sanitized before Discord rendering, URL display is privacy-preserving by default, and the current formatter does not render optional locations or links, which matches the v1 architecture note to include only title and time by default. Future service wiring should instantiate `TagFilter` from `settings.event_tag` and `settings.event_tag_fields`, pass `settings.post_empty_digest` and `settings.empty_digest_text` into `build_daily_digest`, and use `settings.max_discord_message_chars` for `DigestFormatter.max_chars`.

Verification completed during this review:

- `uv run ruff check .` passed.
- `uv run ruff format --check .` passed.
- `uv run pytest` passed with 38 tests and 1 external dependency Python-version warning.

Approval is withheld until the multipart length contract is enforced for final publisher-ready outputs.
