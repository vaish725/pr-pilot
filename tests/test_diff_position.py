"""Tests for parse_diff_hunks: path normalisation and GitHub position mapping."""
from pr_pilot.llm import parse_diff_hunks


SINGLE_HUNK_DIFF = """\
diff --git a/foo.py b/foo.py
index abc..def 100644
--- a/foo.py
+++ b/foo.py
@@ -1,4 +1,5 @@
 context
-old line
+new line
 context
+added line
"""

MULTI_HUNK_DIFF = """\
diff --git a/bar.py b/bar.py
index abc..def 100644
--- a/bar.py
+++ b/bar.py
@@ -1,3 +1,3 @@
 context1
-old1
+new1
@@ -10,3 +10,4 @@
 context2
+extra
 end
"""

DELETION_DIFF = """\
diff --git a/gone.py b/gone.py
index abc..def 100644
--- a/gone.py
+++ /dev/null
@@ -1,2 +0,0 @@
-line1
-line2
"""

MULTI_FILE_DIFF = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,2 @@
-old
+new
diff --git a/b.py b/b.py
--- a/b.py
+++ b/b.py
@@ -1,2 +1,2 @@
-old2
+new2
"""


def test_path_strips_b_prefix():
    files = parse_diff_hunks(SINGLE_HUNK_DIFF)
    assert 'foo.py' in files
    assert 'b/foo.py' not in files


def test_single_hunk_position_start_is_one():
    files = parse_diff_hunks(SINGLE_HUNK_DIFF)
    hunk = files['foo.py'][0]
    # First @@ line is always position 1 for the file
    assert hunk['position_start'] == 1


def test_single_hunk_addition_positions():
    """Body line at 1-based idx maps to position_start + idx."""
    files = parse_diff_hunks(SINGLE_HUNK_DIFF)
    hunk = files['foo.py'][0]
    # Lines: ' context', '-old line', '+new line', ' context', '+added line'
    # idx 3 (+new line)  -> position = 1 + 3 = 4
    # idx 5 (+added line) -> position = 1 + 5 = 6
    assert hunk['position_start'] + 3 == 4
    assert hunk['position_start'] + 5 == 6


def test_multi_hunk_second_hunk_position():
    """Second hunk position_start continues counting from where first hunk ended."""
    files = parse_diff_hunks(MULTI_HUNK_DIFF)
    hunks = files['bar.py']
    assert len(hunks) == 2

    h0 = hunks[0]
    h1 = hunks[1]

    # First hunk: @@ at position 1, body has 3 lines -> positions 2,3,4
    assert h0['position_start'] == 1
    # Second @@ should be at 1 + 3 + 1 = 5
    assert h1['position_start'] == 5


def test_deletion_file_excluded():
    """/dev/null target means file was deleted; should not appear in result."""
    files = parse_diff_hunks(DELETION_DIFF)
    assert 'gone.py' not in files
    assert '/dev/null' not in files


def test_multi_file_positions_reset():
    """Each file resets its position counter independently."""
    files = parse_diff_hunks(MULTI_FILE_DIFF)
    assert 'a.py' in files
    assert 'b.py' in files
    # Both files have their first @@ at position 1
    assert files['a.py'][0]['position_start'] == 1
    assert files['b.py'][0]['position_start'] == 1


def test_hunk_header_fields():
    files = parse_diff_hunks(SINGLE_HUNK_DIFF)
    hunk = files['foo.py'][0]
    assert hunk['old_start'] == 1
    assert hunk['new_start'] == 1
    assert hunk['old_lines'] == 4
    assert hunk['new_lines'] == 5


def test_optional_comma_count_in_header():
    """@@ -1 +1 @@ (no comma) is valid and should parse without error."""
    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1 @@\n-old\n+new\n"
    files = parse_diff_hunks(diff)
    assert 'x.py' in files
    assert files['x.py'][0]['position_start'] == 1
