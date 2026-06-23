import re
from collections import Counter
from typing import List

_SEVERITY_RE = re.compile(r'^\[([A-Z]+)\]')
_SEVERITY_ORDER = ['BUG', 'SECURITY', 'STYLE', 'INFO']


def build_review_summary(comments: List[dict], files_reviewed: int) -> str:
    """Return a markdown summary string for the top-level review body.

    comments: list of {'path', 'position', 'body'} dicts (post-cap).
    files_reviewed: number of files that passed the config filter and were analyzed.
    """
    counts: Counter = Counter()
    for c in comments:
        m = _SEVERITY_RE.match(c.get('body', ''))
        if m:
            counts[m.group(1)] += 1

    n_files = files_reviewed
    n_issues = len(comments)
    file_word = 'file' if n_files == 1 else 'files'
    issue_word = 'issue' if n_issues == 1 else 'issues'

    lines = [
        "## PR Pilot Review",
        "",
        f"Reviewed **{n_files} {file_word}** · **{n_issues} {issue_word} found**",
    ]

    if counts:
        lines += ["", "| Severity | Count |", "|---|---|"]
        for sev in _SEVERITY_ORDER:
            if counts[sev]:
                lines.append(f"| {sev} | {counts[sev]} |")
        for sev, cnt in sorted(counts.items()):
            if sev not in _SEVERITY_ORDER:
                lines.append(f"| {sev} | {cnt} |")

    return "\n".join(lines)
