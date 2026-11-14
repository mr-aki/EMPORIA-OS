# Hourly engineering workforce

## What runs

The Hourly Engineering Workforce is a repository-native, deterministic engineering
quality system. It is separate from Emporia's advisory commerce agents and from the
PostgreSQL background-job worker.

The workflow launches 24 independently scheduled jobs:

- 17 focused pytest workers, one for each existing API test module.
- Ruff lint and Python source compilation.
- A fresh SQLite database migration through the current Alembic head.
- OpenAPI generation and duplicate operation-ID validation.
- Installed dependency consistency, repository-local Markdown links, and isolated API wheel build.

Every worker writes a pass/fail result to its GitHub Actions job summary. Test output and
tracebacks remain in the normal job log. A failed worker fails its own job; the matrix
continues running other workers so one failure does not hide unrelated results.

## Scheduling and capacity

- Automatic schedule: hourly, at 17 minutes past the hour (UTC).
- Manual trigger: GitHub Actions workflow dispatch.
- Pull-request validation: runs on pull requests targeting `main`.
- Concurrency: at most 20 standard hosted jobs at once; the remaining four workers wait
  in the GitHub Actions queue.
- Permissions: read-only repository contents. Checkout does not persist its token.

For public repositories, standard GitHub-hosted runner use is not billed as private-repository
minutes, subject to GitHub's service policies and abuse controls. Scheduled workflows are
best-effort: GitHub may delay them during load, and schedule events operate from the default
branch. This is hourly automation, not a guarantee of execution at an exact minute.

## What this is not

This no-secret slice does **not** call an LLM, write or commit source changes, create pull
requests, deploy services, or perform commerce actions. It provides 24 real, repeatable
engineering checks and evidence without requiring an API key or a ChatGPT subscription.

Autonomous AI coding workers require a configured inference provider and a separately
reviewed, permission-bounded code-change pipeline. Until that exists, these jobs must not
be described as AI coding agents or as autonomous feature developers. A green run proves
only the checks in this workflow passed for that commit; it does not prove production
readiness.

## Adding a worker

Add a named implementation to `scripts/engineering_workers.py`, add the same identifier
to the workflow matrix, and update this document. Workers must be bounded, deterministic,
read-only, time-limited, and must not require live customer data or production credentials.
