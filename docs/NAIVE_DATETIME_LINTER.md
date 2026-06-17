# Naive Datetime Linter

This project includes an AST-based linter that detects usages of naive datetime calls which may cause timezone bugs or deprecation warnings.

What it detects
- `datetime.utcnow()` — use timezone-aware alternatives like `datetime.now(timezone.utc)`
- `datetime.now()` with no arguments — likely naive unless you pass a timezone

Where the code lives
- `pr_pilot/linters/naive_datetime.py` — AST-based checker and CLI entrypoint
- `pr_pilot/linters/flake8_naive_datetime.py` — flake8 plugin wrapper (exposes NDT001)

How to run locally

1. Run the linter directly via `python -m`:

```bash
python -m pr_pilot.linters.naive_datetime
```

2. Run via flake8 (after installing the package in editable mode):

```bash
pip install -e .
flake8
```

Pre-commit

This project uses pre-commit to run linters during `git commit`. To enable it locally:

```bash
pip install pre-commit
pre-commit install
```

The repository's `.pre-commit-config.yaml` is configured to run `flake8`, which will pick up the plugin when the package is installed in the environment used by pre-commit.

Notes
- We removed the old `scripts/check_naive_datetime.py` in favor of the packaged module and flake8 plugin. If your workflow depended on the script directly, use the `python -m` entrypoint above.
