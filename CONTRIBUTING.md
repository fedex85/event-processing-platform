# Contributing

Issues and pull requests are welcome.

## Set up

```bash
make install          # virtualenv with the project and the dev tools
make check            # ruff + mypy + pytest: the same checks CI runs
```

On Windows without `make`, see the PowerShell commands in the README.

## Before opening a pull request

- Add or update tests: every endpoint and every business rule has them.
- Run `make check` (or `ruff check .`, `ruff format --check .`, `mypy`, `pytest`).
- Keep commits small, with a message of the form `type: what changed`
  (`feat`, `fix`, `docs`, `ci`, `chore`, `refactor`).
- No secrets, project ids or URLs in the code: use environment variables.

## Architecture rules

- `api/` and `processor/` are separate services; code they share lives in `common/`.
- Google Cloud clients stay behind small adapters (`publishers`, `repositories`) that are
  injected, so tests never need Google Cloud.
- Do not add Django, FastAPI, Celery, Redis, Kafka or a relational database.
