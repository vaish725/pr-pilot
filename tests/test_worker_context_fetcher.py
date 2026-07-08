"""Tests for the context_fetcher bound in worker.py, which lets the LLM pull
more of the file it's reviewing via the get_file_lines tool (see pr_pilot/llm.py).
"""
from pr_pilot.worker import _make_context_fetcher


def test_fetches_1_based_inclusive_range():
    file_lines = [f"line{i}" for i in range(1, 21)]  # line1..line20
    fetch = _make_context_fetcher(file_lines)

    assert fetch('f.py', 1, 3) == ['line1', 'line2', 'line3']
    assert fetch('f.py', 5, 5) == ['line5']


def test_clamps_to_file_bounds():
    file_lines = [f"line{i}" for i in range(1, 11)]  # line1..line10
    fetch = _make_context_fetcher(file_lines)

    assert fetch('f.py', 8, 20) == ['line8', 'line9', 'line10']
    assert fetch('f.py', -5, 2) == ['line1', 'line2']


def test_empty_file_lines_returns_empty():
    fetch = _make_context_fetcher([])
    assert fetch('f.py', 1, 5) == []


def test_out_of_range_returns_empty():
    file_lines = ['only line']
    fetch = _make_context_fetcher(file_lines)
    assert fetch('f.py', 5, 10) == []
