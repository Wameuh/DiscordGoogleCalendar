# Agent 1 - Cyber Security Reviewer

Status: Changes requested
Reviewed TODO: TODO 4 - Tag Filtering, Digest Rules, Formatting, Sanitization, And URL Policy
Review iteration: 1
Reviewed files:

- `src/discordcalendarbot/calendar/tag_filter.py`
- `src/discordcalendarbot/domain/digest.py`
- `src/discordcalendarbot/discord/sanitizer.py`
- `src/discordcalendarbot/discord/url_policy.py`
- `src/discordcalendarbot/discord/formatter.py`
- `tests/test_tag_digest_discord_formatting.py`

## Findings

- Severity: Low
  File: `src/discordcalendarbot/discord/formatter.py:101`
  Issue: Multipart message prefixes are added after `split_message_lines` enforces `max_chars`, so final `DiscordMessagePart.content` values can exceed the configured Discord message limit once `(index/total)\n` is prepended.
  Impact: A calendar source that can create enough tagged events to force multipart output can make the digest publisher produce oversized Discord payloads when `max_chars` is configured near Discord's hard limit. That can cause Discord sends to fail and creates an avoidable availability weakness in the digest path.
  Required change: Reserve prefix room during splitting or apply prefixing before the final length check so every returned `DiscordMessagePart.content` is guaranteed to be `<= max_chars`, including multipart prefixes. Add a regression assertion covering multipart output lengths.

## Approval Notes

The sanitizer handles the main untrusted calendar text risks reviewed here: it breaks user, role, channel, `@everyone`, and `@here` mentions; removes control and bidirectional formatting characters; flattens masked markdown links; neutralizes custom emoji syntax; escapes Discord markdown metacharacters; collapses whitespace; and caps sanitized field length. The formatter sanitizes event titles and empty digest text before rendering.

The URL policy is privacy-preserving by default because location URL display is disabled unless explicitly opted in. When enabled, it rejects non-HTTPS URLs, omits known private meeting hosts, and strips query strings and fragments before display. Current formatting code does not render location or event links, so no calendar URL is leaked by the reviewed formatter path.

Reported checks are `ruff`, `format`, and `pytest` with 38 passing tests. Approval is withheld only for the multipart length enforcement issue above.
