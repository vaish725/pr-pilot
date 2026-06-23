"""Tests for GitHubClient helper methods."""
from unittest import mock
from pr_pilot.github_client import GitHubClient


def test_fetch_file_content_returns_lines():
    client = GitHubClient(token="fake")

    fake_contents = mock.Mock()
    fake_contents.decoded_content = b"line one\nline two\nline three\n"

    fake_repo = mock.Mock()
    fake_repo.get_contents.return_value = fake_contents

    fake_gh = mock.Mock()
    fake_gh.get_repo.return_value = fake_repo

    client._gh = fake_gh
    lines = client.fetch_file_content("owner", "repo", "foo.py", "abc123")

    assert lines == ["line one", "line two", "line three"]
    fake_repo.get_contents.assert_called_once_with("foo.py", ref="abc123")


def test_fetch_file_content_returns_empty_on_error():
    client = GitHubClient(token="fake")

    fake_repo = mock.Mock()
    fake_repo.get_contents.side_effect = Exception("not found")

    fake_gh = mock.Mock()
    fake_gh.get_repo.return_value = fake_repo

    client._gh = fake_gh
    lines = client.fetch_file_content("owner", "repo", "missing.py", "abc123")

    assert lines == []


def test_post_issue_comment():
    client = GitHubClient(token="fake")

    fake_issue = mock.Mock()
    fake_repo = mock.Mock()
    fake_repo.get_issue.return_value = fake_issue

    fake_gh = mock.Mock()
    fake_gh.get_repo.return_value = fake_repo
    client._gh = fake_gh

    client.post_issue_comment("owner", "repo", 7, "hello from bot")

    fake_repo.get_issue.assert_called_once_with(7)
    fake_issue.create_comment.assert_called_once_with("hello from bot")


def test_fetch_pr_diff_caches_head_sha():
    client = GitHubClient(token="fake")

    fake_pr = mock.Mock()
    fake_pr.patch = "diff --git ..."
    fake_pr.head.sha = "deadbeef"

    fake_repo = mock.Mock()
    fake_repo.get_pull.return_value = fake_pr

    fake_gh = mock.Mock()
    fake_gh.get_repo.return_value = fake_repo

    client._gh = fake_gh
    diff = client.fetch_pr_diff("owner", "repo", 42)

    assert diff == "diff --git ..."
    assert client._last_head_sha == "deadbeef"
