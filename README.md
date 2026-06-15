# pr-pilot
A GitHub App that automatically reviews pull requests using a large language model and posts inline review comments on changed lines.

Goals (MVP)
- Post automated inline comments within ~60s of PR open/update
- Surface bugs, security issues, style suggestions, and missing error handling
- Configurable per-repo via `.reviewbot.yml`

Quickstart (developer)
1. Create and install the GitHub App, configure webhook URL and permissions (read code, read/write pull requests).
2. Copy `.env.example` -> `.env` and set GITHUB_APP_ID, GITHUB_PRIVATE_KEY, GITHUB_WEBHOOK_SECRET, and LLM_API_KEY.
3. Run the webhook server locally (uses FastAPI in this scaffold):

```bash
python -m pr_pilot.server
```

Project layout (this scaffold)
- `pr_pilot/` - Python package with webhook server and worker stubs
- `tests/` - pytest tests
- `pyproject.toml` - project metadata and dependencies
- `.github/workflows/ci.yml` - CI to run tests

See `prd.md` for the full Product Requirements Document with design, goals, and milestones.
# pr-pilot
A GitHub App that reviews pull requests automatically using an LLM - posts inline comments on changed lines within 60 seconds.
