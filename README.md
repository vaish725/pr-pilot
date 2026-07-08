# pr-pilot

[![CI](https://github.com/vaish725/pr-pilot/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/vaish725/pr-pilot/actions/workflows/ci.yml)

A GitHub App that automatically reviews pull requests using a large language model. It posts inline review comments on changed lines, tracks review history, and exposes an admin dashboard for managing per-repo behavior.

## Goals (MVP)

- Post automated inline comments within about 60 seconds of a PR being opened or updated.
- Surface bugs, security issues, style suggestions, and missing error handling.
- Let each repo configure and override review behavior without changing code.

## How it works

1. GitHub sends a webhook to the FastAPI server (`pr_pilot/server.py`) when a PR is opened or updated.
2. The webhook handler enqueues a background job (Redis + RQ) that fetches the diff, resolves the repo's config, and calls the configured LLM provider to analyze changed lines.
3. The worker (`pr_pilot/worker.py`) posts inline review comments back to the PR and, if `DATABASE_URL` is set, records the run and comments for later inspection.
4. The admin dashboard reads that history and lets you inspect runs, adjust per-repo config, and retry failed jobs.

## Quickstart (developer)

1. Create and install the GitHub App, and configure its webhook URL and permissions (read code, read/write pull requests).
2. Copy `.env.example` to `.env` and fill in the values:

   ```
   GITHUB_APP_ID=...              # numeric App ID from your GitHub App settings
   GITHUB_PRIVATE_KEY_PATH=...    # path to the downloaded PEM file (do not commit)
   GITHUB_WEBHOOK_SECRET=...      # random secret used to verify webhook signatures
   LLM_API_KEY=...                # API key for your chosen LLM provider
   GITHUB_TOKEN=...               # optional personal access token, useful for quick local testing
   ```

   Two more variables are optional and enable additional features:

   - `DATABASE_URL` — a SQLAlchemy connection string (SQLite or PostgreSQL). When set, review history, per-repo config, and reaction tracking are persisted, and the admin dashboard and `/config`, `/reviews`, `/runs` endpoints become available. Without it, those endpoints return `501 Not Implemented`.
   - `REDIS_URL` — defaults to `redis://localhost:6379`. Used for the RQ job queue, retry/dead-letter handling, and the `/failed-jobs` endpoints.

3. Run the webhook server locally:

   ```bash
   python -m pr_pilot.server
   ```

4. In a separate terminal, start Redis and the worker (see "Running the worker" below).
5. If testing with real GitHub webhooks, expose the server with a tool like smee or ngrok and point the GitHub App's webhook URL at it.

## Running the worker (dev)

This project uses Redis and RQ for background job processing.

1. Start Redis (for example, via Homebrew):

   ```bash
   brew install redis
   brew services start redis
   ```

2. Start the worker in its own terminal:

   ```bash
   ./scripts/worker.sh
   ```

3. Start the webhook server in another terminal (see step 3 in Quickstart above).

## Admin dashboard

When `DATABASE_URL` is set, an admin dashboard is served at `/dashboard` (the root path `/` redirects there). It lets you:

- View review history and acceptance rate per repo.
- Inspect the comments posted on a specific review run.
- Edit per-repo config (enabled, focus, ignored paths, max comments) without committing a `.reviewbot.yml` change.
- Re-run a review for a given PR.
- List and retry failed background jobs.

The dashboard is a static HTML file (`dashboard/index.html`) served directly by the FastAPI app; it talks to the same API described below.

## Per-repo configuration

Each repo's review behavior (`enabled`, `focus`, `ignore_paths`, `max_comments`) can come from two places:

1. A `RepoConfig` row in the database, edited via the admin dashboard's config panel or the `GET`/`PUT /config/{owner}/{repo}` API.
2. A `.reviewbot.yml` file committed to the repo's default branch.

If `DATABASE_URL` is set and a `RepoConfig` row exists for the repo, it takes precedence over `.reviewbot.yml` — the file is only consulted when no database row exists. If neither is present, built-in defaults apply (`enabled: true`, `focus: all`, `max_comments: 20`, no ignored paths). This lets you override a repo's behavior instantly from the dashboard without needing a commit or PR to change `.reviewbot.yml`. See `_load_config` in `pr_pilot/worker.py` for the exact resolution order.

## Project layout

- `pr_pilot/` — Python package: webhook server, worker, LLM providers, and storage models.
- `dashboard/` — static admin dashboard HTML/JS, served at `/dashboard`.
- `tests/` — pytest test suite.
- `scripts/worker.sh` — convenience script to start the RQ worker locally.
- `pyproject.toml` — project metadata and dependencies.
- `.github/workflows/ci.yml` — CI pipeline that runs `pytest` and `flake8` on every push and pull request.

## Testing and linting

```bash
pytest -q
flake8
```

Both are required to pass in CI before a change can merge.
