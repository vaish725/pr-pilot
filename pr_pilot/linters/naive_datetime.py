"""AST-based checker for naive datetime usage.

Provides a small API to check a Python source file for usages of:
- datetime.utcnow()
- datetime.now() without keyword tz / timezone (heuristic: no keywords)

This is more robust than regexes and avoids simple false positives.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Tuple


def _is_datetime_name(node: ast.AST) -> bool:
    """Return True if node represents the builtin/stdlib name `datetime`.

This handles patterns like:
- datetime.utcnow
- datetime.now
- when `from datetime import datetime` is used, the name is still `datetime`.
"""
    # Name like `datetime`
    if isinstance(node, ast.Name) and node.id == "datetime":
        return True
    # Attribute like `datetime.datetime` (from `import datetime` then `datetime.datetime.now`)
    if isinstance(node, ast.Attribute):
        # Walk attribute chain and check if the rightmost name is 'datetime'
        # e.g., datetime.datetime -> attr 'datetime' and value Name('datetime')
        attr = node
        # find the last attribute/name in the chain
        while isinstance(attr, ast.Attribute):
            if isinstance(attr.attr, str) and attr.attr == "datetime":
                return True
            attr = attr.value
        if isinstance(attr, ast.Name) and attr.id == "datetime":
            return True
    return False


def check_source(source: str) -> List[Tuple[int, int, str]]:
    """Check Python source for naive datetime usage.

    Returns a list of tuples (lineno, col_offset, message).
    """
    tree = ast.parse(source)
    matches: List[Tuple[int, int, str]] = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # type: ignore[override]
            # func can be an Attribute (e.g., datetime.utcnow) or Name
            func = node.func
            if isinstance(func, ast.Attribute):
                attr = func.attr
                # datetime.utcnow()
                if attr == "utcnow" and _is_datetime_name(func.value):
                    matches.append(
                        (node.lineno, node.col_offset, "Use timezone-aware datetime instead of datetime.utcnow()")
                    )
                # datetime.now(...) with no args -> likely naive
                # If there are any positional or keyword args, assume timezone may be provided
                if attr == "now" and _is_datetime_name(func.value):
                    if not node.keywords and not node.args:
                        matches.append((
                            node.lineno,
                            node.col_offset,
                            "Call datetime.now(...) with explicit timezone, e.g. datetime.now(timezone.utc)",
                        ))

            self.generic_visit(node)

    Visitor().visit(tree)
    return matches


def check_file(path: Path) -> List[Tuple[int, int, str]]:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception:
        return []
    return check_source(src)


def walk_files(root: Path, exclude_dirs=None):
    if exclude_dirs is None:
        exclude_dirs = {".git", "venv", "env", "node_modules", "__pycache__", "scripts"}
    for p in root.rglob("*.py"):
        if any(part in exclude_dirs for part in p.parts):
            continue
        yield p


def main(root: Path | None = None) -> int:
    """CLI entrypoint. Scans repository for naive datetime usage and prints matches.

    Returns 0 when no matches, 1 when matches found.
    """
    if root is None:
        # repo root is two levels up from this file: pr_pilot/linters -> repo_root
        root = Path(__file__).resolve().parents[2]

    matches = []
    for f in walk_files(root):
        file_matches = check_file(f)
        for lineno, col, msg in file_matches:
            matches.append((str(f.relative_to(root)), lineno, col, msg))

    if matches:
        print("Naive datetime usage detected:")
        for path, lineno, col, msg in matches:
            print(f"{path}:{lineno}:{col}: {msg}")
        print("\nPlease prefer timezone-aware datetimes, e.g. datetime.now(timezone.utc)")
        return 1

    print("No naive datetime usage found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
