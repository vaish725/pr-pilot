"""Tests for build_review_summary."""
from pr_pilot.review_summary import build_review_summary


def _comment(severity, msg="msg", path="foo.py", pos=1):
    return {"path": path, "position": pos, "body": f"[{severity}] {msg}\n\nSuggestion: fix it"}


def test_empty_comments():
    out = build_review_summary([], files_reviewed=0)
    assert "0 issues found" in out
    assert "0 files" in out


def test_singular_file_and_issue():
    comments = [_comment("BUG")]
    out = build_review_summary(comments, files_reviewed=1)
    assert "1 file" in out
    assert "1 issue found" in out
    assert "files" not in out.split("1 file")[1].split("\n")[0]


def test_severity_counts_in_table():
    comments = [
        _comment("BUG"), _comment("BUG"),
        _comment("SECURITY"),
        _comment("STYLE"), _comment("STYLE"), _comment("STYLE"),
        _comment("INFO"),
    ]
    out = build_review_summary(comments, files_reviewed=3)
    assert "| BUG | 2 |" in out
    assert "| SECURITY | 1 |" in out
    assert "| STYLE | 3 |" in out
    assert "| INFO | 1 |" in out
    assert "7 issues found" in out
    assert "3 files" in out


def test_severity_order_bug_before_style():
    comments = [_comment("STYLE"), _comment("BUG")]
    out = build_review_summary(comments, files_reviewed=1)
    bug_pos = out.index("BUG")
    style_pos = out.index("STYLE")
    assert bug_pos < style_pos


def test_unknown_severity_included():
    comments = [_comment("PERF")]
    out = build_review_summary(comments, files_reviewed=1)
    assert "PERF" in out


def test_no_severity_table_when_no_comments():
    out = build_review_summary([], files_reviewed=2)
    assert "---|" not in out


def test_summary_header_present():
    out = build_review_summary([], files_reviewed=0)
    assert out.startswith("## PR Pilot Review")
