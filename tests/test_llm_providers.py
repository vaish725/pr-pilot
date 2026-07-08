import json
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


# ---------------------------------------------------------------------------
# to_tool_schema
# ---------------------------------------------------------------------------

_SPEC = {
    'name': 'get_file_lines',
    'description': 'Fetch more lines of the file.',
    'parameters': {
        'type': 'object',
        'properties': {'start_line': {'type': 'integer'}, 'end_line': {'type': 'integer'}},
        'required': ['start_line', 'end_line'],
    },
}


def test_openai_to_tool_schema_shape():
    schema = OpenAIClient.to_tool_schema(_SPEC)
    assert schema['type'] == 'function'
    assert schema['function']['name'] == 'get_file_lines'
    assert schema['function']['parameters'] == _SPEC['parameters']


def test_anthropic_to_tool_schema_shape():
    schema = AnthropicClient.to_tool_schema(_SPEC)
    assert schema['name'] == 'get_file_lines'
    assert schema['input_schema'] == _SPEC['parameters']


# ---------------------------------------------------------------------------
# run_with_tools — real multi-turn tool-calling loop
# ---------------------------------------------------------------------------

def test_openai_run_with_tools_executes_tool_then_returns_final_text():
    """First turn: model asks for more file context via a tool call.
    Second turn: model answers using the tool result — a genuine re-plan step."""
    client = OpenAIClient(api_key="fake-key", model="gpt-4o")

    tool_call = mock.Mock()
    tool_call.id = "call_1"
    tool_call.function.name = "get_file_lines"
    tool_call.function.arguments = json.dumps({"start_line": 10, "end_line": 15})
    first_message = mock.Mock(content=None, tool_calls=[tool_call])
    first_resp = mock.Mock(choices=[mock.Mock(message=first_message)])

    final_text = json.dumps([{"line": 1, "severity": "BUG", "message": "ok", "suggestion": "fix"}])
    second_message = mock.Mock(content=final_text, tool_calls=None)
    second_resp = mock.Mock(choices=[mock.Mock(message=second_message)])

    fake_oai_client = mock.Mock()
    fake_oai_client.chat.completions.create.side_effect = [first_resp, second_resp]

    executor = mock.Mock(return_value="10: def helper():\n11:    return 1")
    tools = [OpenAIClient.to_tool_schema(_SPEC)]

    with mock.patch.object(client, '_client', return_value=fake_oai_client):
        text, tool_call_count = client.run_with_tools(
            "prompt", tools=tools, tool_executor=executor, max_tool_iterations=1,
        )

    assert tool_call_count == 1
    assert text == final_text
    executor.assert_called_once_with('get_file_lines', {'start_line': 10, 'end_line': 15})
    assert fake_oai_client.chat.completions.create.call_count == 2

    second_call_messages = fake_oai_client.chat.completions.create.call_args_list[1].kwargs['messages']
    assert any(m['role'] == 'tool' and m['content'] == executor.return_value for m in second_call_messages)


def test_openai_run_with_tools_respects_max_iterations():
    """If the model keeps requesting tools past the bound, the loop stops rather than looping forever."""
    client = OpenAIClient(api_key="fake-key", model="gpt-4o")

    def _make_tool_call_resp(call_id):
        tc = mock.Mock()
        tc.id = call_id
        tc.function.name = "get_file_lines"
        tc.function.arguments = json.dumps({"start_line": 1, "end_line": 5})
        return mock.Mock(choices=[mock.Mock(message=mock.Mock(content=None, tool_calls=[tc]))])

    fake_oai_client = mock.Mock()
    fake_oai_client.chat.completions.create.side_effect = [
        _make_tool_call_resp("call_1"), _make_tool_call_resp("call_2"),
    ]

    executor = mock.Mock(return_value="some content")
    tools = [OpenAIClient.to_tool_schema(_SPEC)]

    with mock.patch.object(client, '_client', return_value=fake_oai_client):
        text, tool_call_count = client.run_with_tools(
            "prompt", tools=tools, tool_executor=executor, max_tool_iterations=1,
        )

    assert tool_call_count == 1
    assert fake_oai_client.chat.completions.create.call_count == 2
    executor.assert_called_once()


def test_openai_run_with_tools_no_tool_call_returns_immediately():
    client = OpenAIClient(api_key="fake-key", model="gpt-4o")
    message = mock.Mock(content="no issues found", tool_calls=None)
    resp = mock.Mock(choices=[mock.Mock(message=message)])
    fake_oai_client = mock.Mock()
    fake_oai_client.chat.completions.create.return_value = resp

    executor = mock.Mock()
    with mock.patch.object(client, '_client', return_value=fake_oai_client):
        text, tool_call_count = client.run_with_tools(
            "prompt", tools=[OpenAIClient.to_tool_schema(_SPEC)], tool_executor=executor,
        )

    assert text == "no issues found"
    assert tool_call_count == 0
    executor.assert_not_called()
    assert fake_oai_client.chat.completions.create.call_count == 1


def test_anthropic_run_with_tools_executes_tool_then_returns_final_text():
    client = AnthropicClient(api_key="fake-key", model="claude-sonnet-4-6")

    tool_use_block = mock.Mock(type='tool_use', id='tu_1', input={'start_line': 3, 'end_line': 8})
    tool_use_block.name = 'get_file_lines'
    first_resp = mock.Mock(content=[tool_use_block])

    text_block = mock.Mock(type='text', text='[{"line": 1, "severity": "BUG", "message": "ok", "suggestion": "fix"}]')
    second_resp = mock.Mock(content=[text_block])

    fake_anth_client = mock.Mock()
    fake_anth_client.messages.create.side_effect = [first_resp, second_resp]

    executor = mock.Mock(return_value="3: import os\n4: import sys")
    tools = [AnthropicClient.to_tool_schema(_SPEC)]

    with mock.patch.object(client, '_client', return_value=fake_anth_client):
        text, tool_call_count = client.run_with_tools(
            "prompt", tools=tools, tool_executor=executor, max_tool_iterations=1,
        )

    assert tool_call_count == 1
    assert 'BUG' in text
    executor.assert_called_once_with('get_file_lines', {'start_line': 3, 'end_line': 8})
    assert fake_anth_client.messages.create.call_count == 2

    second_call_messages = fake_anth_client.messages.create.call_args_list[1].kwargs['messages']
    tool_result_msg = next(m for m in second_call_messages if m['role'] == 'user' and isinstance(m['content'], list))
    assert tool_result_msg['content'][0]['tool_use_id'] == 'tu_1'
    assert tool_result_msg['content'][0]['content'] == executor.return_value


def test_anthropic_run_with_tools_no_tool_call_returns_immediately():
    client = AnthropicClient(api_key="fake-key", model="claude-sonnet-4-6")
    text_block = mock.Mock(type='text', text='no issues found')
    resp = mock.Mock(content=[text_block])
    fake_anth_client = mock.Mock()
    fake_anth_client.messages.create.return_value = resp

    executor = mock.Mock()
    with mock.patch.object(client, '_client', return_value=fake_anth_client):
        text, tool_call_count = client.run_with_tools(
            "prompt", tools=[AnthropicClient.to_tool_schema(_SPEC)], tool_executor=executor,
        )

    assert text == 'no issues found'
    assert tool_call_count == 0
    executor.assert_not_called()
