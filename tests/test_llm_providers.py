from unittest import mock
from pr_pilot.llm_providers import OpenAIClient, AnthropicClient


def test_openai_token_count_fallback():
    client = OpenAIClient(api_key="not-used", model="gpt-4o")
    text = "def foo():\n    return 42\n" * 50
    tokens = client.count_tokens(text)
    assert tokens > 0
    assert tokens < len(text)


def test_anthropic_token_count_fallback():
    client = AnthropicClient(api_key="not-used", model="claude-sonnet-4-6")
    text = "This is a sample sentence. " * 100
    tokens = client.count_tokens(text)
    assert tokens > 0
    assert tokens < len(text)


def test_anthropic_long_identifier_handling():
    client = AnthropicClient(api_key="not-used")
    long_ident = "a" * 120
    tokens = client.count_tokens(long_ident)
    assert tokens >= 10


def test_openai_call_uses_chat_completions_api():
    """Verify call() uses the v2 chat.completions.create API and reads choices[0].message.content."""
    client = OpenAIClient(api_key="fake-key", model="gpt-4o")

    fake_message = mock.Mock()
    fake_message.content = "review text"
    fake_choice = mock.Mock()
    fake_choice.message = fake_message
    fake_resp = mock.Mock()
    fake_resp.choices = [fake_choice]

    fake_oai_client = mock.Mock()
    fake_oai_client.chat.completions.create.return_value = fake_resp

    with mock.patch.object(client, '_client', return_value=fake_oai_client):
        result = client.call("some prompt")

    assert result == "review text"
    fake_oai_client.chat.completions.create.assert_called_once()
    call_kwargs = fake_oai_client.chat.completions.create.call_args[1]
    assert call_kwargs['model'] == 'gpt-4o'
    assert any(m['role'] == 'user' for m in call_kwargs['messages'])
    assert any(m['role'] == 'system' for m in call_kwargs['messages'])


def test_openai_call_retries_on_failure():
    """call() retries up to 4 attempts then raises."""
    client = OpenAIClient(api_key="fake-key", model="gpt-4o")

    fake_oai_client = mock.Mock()
    fake_oai_client.chat.completions.create.side_effect = RuntimeError("rate limit")

    with mock.patch.object(client, '_client', return_value=fake_oai_client):
        with mock.patch('time.sleep'):
            try:
                client.call("prompt")
            except RuntimeError:
                pass

    assert fake_oai_client.chat.completions.create.call_count == 4


def test_anthropic_call_uses_messages_api():
    """Verify call() uses the v0.19+ messages.create API and reads content[0].text."""
    client = AnthropicClient(api_key="fake-key", model="claude-sonnet-4-6")

    fake_block = mock.Mock()
    fake_block.text = "anthropic review"
    fake_resp = mock.Mock()
    fake_resp.content = [fake_block]

    fake_anth_client = mock.Mock()
    fake_anth_client.messages.create.return_value = fake_resp

    with mock.patch.object(client, '_client', return_value=fake_anth_client):
        result = client.call("some prompt")

    assert result == "anthropic review"
    fake_anth_client.messages.create.assert_called_once()
    call_kwargs = fake_anth_client.messages.create.call_args[1]
    assert call_kwargs['model'] == 'claude-sonnet-4-6'
    assert 'system' in call_kwargs
    assert any(m['role'] == 'user' for m in call_kwargs['messages'])


def test_anthropic_call_retries_on_failure():
    """call() retries up to 4 attempts then raises."""
    client = AnthropicClient(api_key="fake-key", model="claude-sonnet-4-6")

    fake_anth_client = mock.Mock()
    fake_anth_client.messages.create.side_effect = RuntimeError("overload")

    with mock.patch.object(client, '_client', return_value=fake_anth_client):
        with mock.patch('time.sleep'):
            try:
                client.call("prompt")
            except RuntimeError:
                pass

    assert fake_anth_client.messages.create.call_count == 4
