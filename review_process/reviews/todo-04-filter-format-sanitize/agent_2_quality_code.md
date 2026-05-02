# Agent 2 - Quality Code Reviewer

Status: Changes requested
Reviewed TODO: TODO 4 - Tag filtering and digest formatting
Review iteration: 1
Reviewed files:

- `AGENTS.md`
- `.cursor/rules/python-best-practices.mdc`
- `.cursor/rules/python-fastapi.mdc`
- `review_process/review_agents.md`
- `ARCHITECTURE.md`
- `src/discordcalendarbot/calendar/tag_filter.py`
- `src/discordcalendarbot/discord/formatter.py`
- `src/discordcalendarbot/discord/sanitizer.py`
- `src/discordcalendarbot/discord/url_policy.py`
- `src/discordcalendarbot/domain/digest.py`
- `tests/test_tag_digest_discord_formatting.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/discord/formatter.py:101`
  Issue: Multi-part message numbering is added after line splitting has already enforced `max_chars`.
  Impact: A message part that was exactly at or near the configured limit can exceed the limit once the `(1/N)` prefix and newline are prepended. This breaks the formatter's documented contract to return message parts below the configured character limit and can cause Discord publish failures when the real Discord limit is approached.
  Required change: Reserve prefix length during splitting when more than one part is needed, or perform a second bounded split after numbering so every returned `DiscordMessagePart.content` remains `<= max_chars`. Add a regression assertion that every part respects the configured limit after numbering.

- Severity: Low
  File: `src/discordcalendarbot/discord/formatter.py:27`
  Issue: `DigestFormatter` stores a required `UrlPolicy` dependency but never uses it while formatting.
  Impact: This creates avoidable coupling and blurs the formatter/URL-policy responsibility boundary. Future maintainers may assume location URL policy is enforced by the formatter even though URL display is currently ignored entirely.
  Required change: Either remove `url_policy` from `DigestFormatter` until location/link output is implemented, or use it through a focused helper that renders only explicitly allowed location URLs. Keep URL filtering decisions inside `UrlPolicy` and presentation decisions inside the formatter.

## Approval Notes

Checks are reported as passing, and the broad module layout fits the architecture: `TagFilter` owns tag matching/title cleanup, `DailyDigest` owns sorting and empty-day policy, `DiscordContentSanitizer` owns untrusted text neutralization, and `UrlPolicy` owns URL allow/deny decisions.

Typing and docstrings are present across the changed source and test helpers. The remaining required changes are limited to the formatter boundary: preserve the message length contract after numbering and resolve the unused URL policy dependency so the formatter's responsibilities stay explicit.
