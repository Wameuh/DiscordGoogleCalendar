# Agent 4 - Integration test reviewer

Status: Changes requested
Reviewed TODO: TODO 9: Documentation, Deployment, And CI
Review iteration: 1
Reviewed files:

- `.github/workflows/ci.yml`
- `.python-version`
- `pyproject.toml`
- `uv.lock`
- `README.md`
- `docs/deployment.md`
- `tests/test_docs_ci.py`

## Findings

- Severity: Medium
  File: `.github/workflows/ci.yml:41`
  Issue: The dependency vulnerability audit runs `uvx pip-audit` without pointing pip-audit at the project's locked dependency set. A dry run of that command audits 29 packages from the tool/runtime environment, while `uv export --locked --format requirements.txt --all-groups --no-hashes --no-emit-project` shows 60 locked project dependencies, including the Discord, Google, scheduler, SQLite, pytest, and Ruff packages.
  Impact: CI can report a successful dependency audit while missing vulnerabilities in packages resolved by `uv.lock`. This breaks the intended integration between CI, the committed lockfile, and the documentation's claim that CI audits project dependencies.
  Required change: Change the CI audit to consume the locked project dependencies, for example by exporting `uv.lock` to a temporary requirements file and running `uvx pip-audit -r <file>`, or by adding a supported project/lockfile-aware audit command and documenting the exact command in `docs/deployment.md`.

## Approval Notes

The remaining integration points reviewed are aligned. CI uses `.python-version`, which is `3.10`, matching `requires-python = ">=3.10"` in `pyproject.toml` and `uv.lock`. The workflow installs with `uv sync --locked --all-extras --dev`, then runs the same Ruff and pytest commands documented in the README and deployment guide. The documentation covers both Windows and Linux deployment, keeps credentials out of CI expectations, and the docs/CI tests are deterministic file checks with no real Discord or Google credentials.

Approval is blocked only on making the dependency audit actually cover the locked project dependency graph.
