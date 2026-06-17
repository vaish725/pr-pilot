#!/usr/bin/env python3
"""Check for naive datetime usage in the repository.

Flags prints matches and returns exit code 1 if any naive usage is found.

Patterns checked:
- datetime.utcnow
- datetime.now(  without timezone argument (heuristic)
"""
import re
import sys
from pathlib import Path
from pr_pilot.linters.naive_datetime import check_file

ROOT = Path(__file__).resolve().parents[1]
exclude_dirs = {".git", "venv", "env", "node_modules", "__pycache__", "scripts"}


def walk_files():
    for p in ROOT.rglob("*.py"):
        if any(part in exclude_dirs for part in p.parts):
            continue
        yield p


def main():
    matches = []
    for f in walk_files():
        file_matches = check_file(f)
        for lineno, col, msg in file_matches:
            matches.append((str(f.relative_to(ROOT)), lineno, col, msg))

    if matches:
        print("Naive datetime usage detected:")
        for path, lineno, col, msg in matches:
            print(f"{path}:{lineno}:{col}: {msg}")
        print("\nPlease prefer timezone-aware datetimes, e.g. datetime.now(timezone.utc)")
        return 1

    print("No naive datetime usage found.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
