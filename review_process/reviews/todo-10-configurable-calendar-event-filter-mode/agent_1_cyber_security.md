# Agent 1 - Cyber Security Reviewer

Status: Changes requested
Reviewed TODO: configurable-calendar-event-filter-mode
Review iteration: 1
Reviewed files:

- `.gitignore`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `README.md`
- `docs/deployment.md`
- `src/discordcalendarbot/app.py`
- `src/discordcalendarbot/calendar/tag_filter.py`
- `src/discordcalendarbot/config.py`
- `src/discordcalendarbot/operator_commands.py`
- `src/discordcalendarbot/services/digest_service.py`
- `tests/test_config_domain_security.py`
- `tests/test_daily_digest_service_scheduler.py`
- `tests/test_discord_bot_publisher.py`
- `tests/test_operator_commands.py`
- `tests/test_project_foundation.py`

## Findings

- Severity: Medium
  File: `src/discordcalendarbot/services/digest_service.py:451`
  Issue: `stable_filter_hash()` hashes only `EVENT_TAG` whenever a tag is configured, so `EVENT_FILTER_MODE=all` with `EVENT_TAG` still present produces the same idempotency key as `EVENT_FILTER_MODE=tagged` with the same tag.
  Impact: The repository can treat privacy-impacting all-events digests as equivalent to tagged-only digests. This can cause skipped sends, misleading run history, and unsafe operational ambiguity when switching between a constrained tagged policy and the broader all-events policy.
  Required change: Include `settings.event_filter_mode.value` in the filter-policy hash for every mode, and include the tag only as an additional component when present. Add a regression test proving `tagged + #tag`, `all + #tag`, and `all + no tag` produce distinct run keys.

## Approval Notes

The configuration default remains fail-closed as `tagged`, invalid filter modes are rejected, `EVENT_TAG` is still required for tagged mode, and the documentation clearly warns that `all` mode can expose private calendar content to Discord. The new `.gitignore` entries improve local secret/artifact safety, and no staged files were present during this review.

Approval is blocked until the idempotency hash uniquely represents the full filter policy.
