# Agent 4 - Integration test reviewer

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
  File: `src/discordcalendarbot/services/digest_service.py:453`
  Issue: `stable_filter_hash()` includes `settings.event_tag` even when `EVENT_FILTER_MODE=all`, while `build_digest_event_filter()` ignores that tag in all-events mode.
  Impact: The scheduler and operator digest paths can create different idempotency keys for the same all-events digest depending only on whether an unused `EVENT_TAG` remains in `.env`. An operator changing from `EVENT_FILTER_MODE=all` with `EVENT_TAG=#discord-daily` to `EVENT_FILTER_MODE=all` with no `EVENT_TAG`, or changing the unused tag value, could repost the same all-events digest for the same date/channel/calendars.
  Required change: Make the filter hash reflect the effective filter policy: for `all`, hash only the mode, and for `tagged`, hash the mode plus the required tag. Add an integration/unit test proving two all-mode settings with different or missing `EVENT_TAG` produce the same digest run key, while tagged and all still produce different keys.

## Approval Notes

The application and operator command wiring both use `build_digest_event_filter()`, so scheduler and dry-run/send paths now share the same filter factory. Config defaults preserve the original tagged behavior, `EVENT_TAG` is optional in `all` mode, and all-events filtering includes untagged events without title cleanup. Documentation and `.gitignore` updates are aligned with the integration intent.

Validation run during review:

- `uv run pytest tests/test_config_domain_security.py tests/test_daily_digest_service_scheduler.py tests/test_project_foundation.py -q`: passed, 40 passed, 1 Python 3.10 Google support warning.
- `uv run pytest`: passed, 110 passed, 2 skipped, 1 Python 3.10 Google support warning.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed.

Residual risk after the required change is low; the remaining integration surface is mostly the live Google/Discord behavior, which is intentionally mocked in this TODO.
