"""Tests for ReviewConfig: parsing, file filtering, focus instructions."""
from pr_pilot.config import ReviewConfig


def test_defaults():
    cfg = ReviewConfig()
    assert cfg.enabled is True
    assert cfg.focus == 'all'
    assert cfg.ignore_paths == []
    assert cfg.languages == []
    assert cfg.max_comments == 20


def test_from_dict_full():
    cfg = ReviewConfig.from_dict({
        'enabled': False,
        'focus': 'bugs',
        'ignore_paths': ['vendor/*', '*.pb.go'],
        'languages': ['python', 'go'],
        'max_comments': 5,
    })
    assert cfg.enabled is False
    assert cfg.focus == 'bugs'
    assert cfg.ignore_paths == ['vendor/*', '*.pb.go']
    assert cfg.languages == ['python', 'go']
    assert cfg.max_comments == 5


def test_from_dict_defaults_on_empty():
    cfg = ReviewConfig.from_dict({})
    assert cfg.enabled is True
    assert cfg.focus == 'all'
    assert cfg.max_comments == 20


def test_from_dict_invalid_focus_falls_back_to_all():
    cfg = ReviewConfig.from_dict({'focus': 'performance'})
    assert cfg.focus == 'all'


def test_should_review_file_no_filters():
    cfg = ReviewConfig()
    assert cfg.should_review_file('src/foo.py') is True
    assert cfg.should_review_file('vendor/bar.go') is True


def test_should_review_file_ignore_paths():
    cfg = ReviewConfig.from_dict({'ignore_paths': ['vendor/*', 'generated/*']})
    assert cfg.should_review_file('vendor/dep.go') is False
    assert cfg.should_review_file('generated/schema.py') is False
    assert cfg.should_review_file('src/main.py') is True


def test_should_review_file_ignore_by_basename():
    cfg = ReviewConfig.from_dict({'ignore_paths': ['*.pb.go']})
    assert cfg.should_review_file('proto/foo.pb.go') is False
    assert cfg.should_review_file('proto/foo.go') is True


def test_should_review_file_language_filter():
    cfg = ReviewConfig.from_dict({'languages': ['python']})
    assert cfg.should_review_file('app.py') is True
    assert cfg.should_review_file('app.go') is False
    assert cfg.should_review_file('app.ts') is False


def test_should_review_file_multi_language():
    cfg = ReviewConfig.from_dict({'languages': ['python', 'typescript']})
    assert cfg.should_review_file('src/app.py') is True
    assert cfg.should_review_file('src/app.ts') is True
    assert cfg.should_review_file('src/app.tsx') is True
    assert cfg.should_review_file('src/app.go') is False


def test_focus_instruction_bugs():
    cfg = ReviewConfig.from_dict({'focus': 'bugs'})
    instr = cfg.focus_instruction()
    assert 'bug' in instr.lower() or 'logic' in instr.lower()
    assert 'style' in instr.lower()  # says to skip style


def test_focus_instruction_security():
    cfg = ReviewConfig.from_dict({'focus': 'security'})
    assert 'security' in cfg.focus_instruction().lower()


def test_focus_instruction_style():
    cfg = ReviewConfig.from_dict({'focus': 'style'})
    assert 'style' in cfg.focus_instruction().lower()


def test_focus_instruction_all_is_empty():
    cfg = ReviewConfig.from_dict({'focus': 'all'})
    assert cfg.focus_instruction() == ""


def test_fetch_reviewbot_config_from_valid_yaml():
    from unittest import mock
    from pr_pilot.github_client import GitHubClient

    client = GitHubClient(token="fake")
    yaml_lines = [
        "enabled: true",
        "focus: security",
        "ignore_paths:",
        "  - vendor/*",
        "max_comments: 10",
    ]

    with mock.patch.object(client, 'fetch_file_content', return_value=yaml_lines):
        cfg = client.fetch_reviewbot_config('owner', 'repo', 'abc123')

    assert cfg.enabled is True
    assert cfg.focus == 'security'
    assert cfg.ignore_paths == ['vendor/*']
    assert cfg.max_comments == 10


def test_fetch_reviewbot_config_missing_file_returns_defaults():
    from unittest import mock
    from pr_pilot.github_client import GitHubClient

    client = GitHubClient(token="fake")

    with mock.patch.object(client, 'fetch_file_content', return_value=[]):
        cfg = client.fetch_reviewbot_config('owner', 'repo', 'abc123')

    assert cfg.enabled is True
    assert cfg.max_comments == 20


def test_fetch_reviewbot_config_invalid_yaml_returns_defaults():
    from unittest import mock
    from pr_pilot.github_client import GitHubClient

    client = GitHubClient(token="fake")
    bad_yaml = [": not valid yaml :::"]

    with mock.patch.object(client, 'fetch_file_content', return_value=bad_yaml):
        cfg = client.fetch_reviewbot_config('owner', 'repo', 'abc123')

    assert cfg.enabled is True
