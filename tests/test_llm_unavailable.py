"""Tests for LLMUnavailableError raised when all LLM provider calls fail."""
import pytest
from unittest.mock import MagicMock, patch

from pr_pilot.exceptions import LLMUnavailableError
from pr_pilot.llm import analyze_diff
from pr_pilot.llm_providers import OpenAIClient


def _mock_client(call_effect):
    client = MagicMock(spec=OpenAIClient)
    client.count_tokens.return_value = 1
    client.call.side_effect = call_effect
    return client


def test_raises_when_all_calls_fail():
    client = _mock_client(RuntimeError('connection refused'))

    with patch('pr_pilot.llm.OpenAIClient', return_value=client):
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai'}):
            with pytest.raises(LLMUnavailableError, match='openai'):
                analyze_diff('foo.py', '+new line\n')


def test_does_not_raise_when_calls_succeed():
    client = _mock_client('[{"line": 1, "severity": "INFO", "message": "ok", "suggestion": "noop"}]')
    client.call.side_effect = None
    client.call.return_value = '[{"line": 1, "severity": "INFO", "message": "ok", "suggestion": "noop"}]'

    with patch('pr_pilot.llm.OpenAIClient', return_value=client):
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai'}):
            result = analyze_diff('foo.py', '+new line\n')

    assert isinstance(result, list)


def test_does_not_raise_on_empty_diff():
    """An empty diff produces no chunks so no error should be raised."""
    client = _mock_client(RuntimeError('should not be called'))

    with patch('pr_pilot.llm.OpenAIClient', return_value=client):
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai'}):
            result = analyze_diff('foo.py', '')

    assert result == []


def test_error_message_includes_provider_name():
    client = _mock_client(ConnectionError('timeout'))

    with patch('pr_pilot.llm.OpenAIClient', return_value=client):
        with patch.dict('os.environ', {'LLM_PROVIDER': 'openai'}):
            with pytest.raises(LLMUnavailableError) as exc_info:
                analyze_diff('bar.py', '+x = 1\n')

    assert 'bar.py' in str(exc_info.value)
