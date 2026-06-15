from typing import List, Dict
import re


def analyze_diff(file_path: str, diff_text: str) -> List[Dict]:
    """Return dummy suggestions for each added line in the unified diff.

    This function looks for lines starting with '+' in the diff hunk bodies and emits
    a suggestion recommending review of the new line.
    """
    suggestions: List[Dict] = []
    # Split into lines and scan for hunk bodies. We won't compute exact GitHub 'position' here;
    # that mapping happens in the server layer which has access to the parsed hunks.
    for i, line in enumerate(diff_text.splitlines(), start=1):
        if line.startswith('+') and not line.startswith('+++'):
            suggestions.append({
                "file": file_path,
                "line": i,
                "severity": "STYLE",
                "message": "Please double-check this added line for style/clarity.",
                "suggestion": line[1:].strip(),
            })
    return suggestions


def parse_diff_hunks(diff_text: str):
    """Parse a unified diff into hunks. Yields tuples (file_path, hunks) where hunks is a list of dicts.

    Each hunk dict contains: { 'old_start', 'old_lines', 'new_start', 'new_lines', 'lines' }
    This is a minimal parser sufficient for position mapping in the scaffold.
    """
    files = {}
    cur_file = None
    hunk_re = re.compile(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@")
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith('+++ '):
            cur_file = l[4:].strip()
            files[cur_file] = []
            i += 1
            continue
        m = hunk_re.match(l)
        if m and cur_file:
            old_start, old_len, new_start, new_len = map(int, m.groups())
            i += 1
            hunk_lines = []
            # collect hunk body until next hunk header or file marker
            while i < len(lines) and not lines[i].startswith('@@ ') and not lines[i].startswith('+++ '):
                hunk_lines.append(lines[i])
                i += 1
            files[cur_file].append({
                'old_start': old_start,
                'old_lines': old_len,
                'new_start': new_start,
                'new_lines': new_len,
                'lines': hunk_lines,
            })
            continue
        i += 1
    return files

