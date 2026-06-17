"""Flake8 plugin wrapper for the naive-datetime AST check.

Provides a flake8 extension that emits NDT001 for naive datetime usage.
"""
from __future__ import annotations

from typing import Generator, Tuple
import ast

from pr_pilot.linters.naive_datetime import check_source


class NaiveDatetimeChecker:
    name = "flake8-naive-datetime"
    version = "0.1.0"

    def __init__(self, tree: ast.AST, filename: str = "(none)") -> None:
        self.tree = tree
        self.filename = filename

    def run(self) -> Generator[Tuple[int, int, str, type], None, None]:
        try:
            source = ast.get_source_segment(ast.get_source_segment, self.tree)  # type: ignore[arg-type]
        except Exception:
            source = None

        # Fallback: read the file
        if source is None:
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    source = f.read()
            except Exception:
                source = ""

        matches = check_source(source)
        for lineno, col, msg in matches:
            code = "NDT001"
            yield lineno, col, f"{code} {msg}", type(self)
