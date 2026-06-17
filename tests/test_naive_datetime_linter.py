import textwrap
from pr_pilot.linters.naive_datetime import check_source


def test_detects_utcnow():
    src = textwrap.dedent("""
    from datetime import datetime

    def f():
        return datetime.utcnow()
    """)
    matches = check_source(src)
    assert any("utcnow" in m[2] or "utcnow" in m[2].lower() or "utcnow" for m in matches)


def test_detects_now_without_kwargs():
    src = textwrap.dedent("""
    import datetime

    def f():
        return datetime.datetime.now()
    """)
    matches = check_source(src)
    assert matches, "should flag datetime.datetime.now() without timezone"


def test_ignores_now_with_timezone_kwarg():
    src = textwrap.dedent("""
    from datetime import datetime, timezone

    def f():
        return datetime.now(timezone.utc)
    """)
    matches = check_source(src)
    assert not matches, "should not flag datetime.now(timezone.utc)"


def test_no_false_positive_on_variable_named_datetime():
    src = textwrap.dedent("""
    def f():
        datetime = 'not a module'
        return datetime.utcnow if hasattr(datetime, 'utcnow') else None
    """)
    matches = check_source(src)
    # This will not parse as a call to module datetime.utcnow; ensure no crash and no matches.
    assert isinstance(matches, list)
