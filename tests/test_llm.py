import json
from unittest import mock

from pr_pilot.llm import analyze_diff, _split_into_chunks
from pr_pilot.llm_providers import OpenAIClient


def test_split_into_chunks_small():
    text = "\n".join([f"line {i}" for i in range(10)])

    def counter(s):
        return max(1, len(s) // 4)

    chunks = _split_into_chunks(text, max_tokens=1000, counter=counter)
    assert len(chunks) == 1


def test_analyze_diff_json_parsing(monkeypatch):
    # Provide a small diff text and mock OpenAI call to return JSON
    diff = "+def foo():\n+    return 1\n"

    fake_response = json.dumps([
        {"line": 1, "severity": "INFO", "message": "Nit: add docstring", "suggestion": "Add a docstring."}
    ])

    # Patch the provider client used by analyze_diff: mock OpenAIClient.call
    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.call.return_value = fake_response
    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        suggestions = analyze_diff('file.py', diff_text=diff)
    assert isinstance(suggestions, list)
    assert suggestions and suggestions[0]['line'] == 1


def test_analyze_diff_with_wrapped_text(monkeypatch):
    diff = "+x = 1\n+print(x)\n"
    # Model returns extra commentary before/after JSON
    wrapped = "Here is my analysis:\n" + json.dumps([
        {"line": 2, "severity": "STYLE", "message": "Use f-string", "suggestion": "Use f'{x}'"}
    ]) + "\nThanks!"

    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.call.return_value = wrapped
    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        suggestions = analyze_diff('file.py', diff_text=diff)
    assert len(suggestions) == 1
    assert suggestions[0]['line'] == 2


def test_split_into_chunks_edgecase():
    # Create lines that would trigger chunk splits precisely
    long_line = "a" * 4000
    text = "\n".join([long_line for _ in range(3)])

    def counter(s):
        return max(1, len(s) // 4)

    chunks = _split_into_chunks(text, max_tokens=100, counter=counter)
    assert len(chunks) >= 2


def test_analyze_diff_context_included_in_prompt():
    """context_before/after lines must appear in the prompt sent to the LLM."""
    diff = "+x = 1\n"
    before = ["# imports", "import os"]
    after = ["y = 2", "z = 3"]

    captured_prompts = []

    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.call.side_effect = lambda prompt, **_: (
        captured_prompts.append(prompt) or "[]"
    )

    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        analyze_diff('foo.py', diff_text=diff, context_before=before, context_after=after)

    assert captured_prompts, "LLM call never made"
    prompt = captured_prompts[0]
    assert "CONTEXT BEFORE HUNK" in prompt
    assert "# imports" in prompt
    assert "CONTEXT AFTER HUNK" in prompt
    assert "y = 2" in prompt
    assert "FILE: foo.py" in prompt
    # line index in JSON refers to DIFF section, so the updated label must be present
    assert "DIFF section" in prompt


# ---------------------------------------------------------------------------
# Agentic tool-calling: analyze_diff can let the model pull more file context
# mid-review via a get_file_lines tool, instead of us always guessing a fixed
# context window.
# ---------------------------------------------------------------------------

def test_analyze_diff_uses_tools_when_context_fetcher_given():
    diff = "+result = helper()\n"

    def fetcher(path, start, end):
        return [f"line{i}" for i in range(start, end + 1)]

    final = json.dumps([{"line": 1, "severity": "BUG", "message": "check helper", "suggestion": "verify import"}])

    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.to_tool_schema.return_value = {'type': 'function', 'function': {'name': 'get_file_lines'}}
    fake_client.run_with_tools.return_value = (final, 1)

    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        suggestions = analyze_diff('file.py', diff_text=diff, context_fetcher=fetcher)

    assert suggestions and suggestions[0]['severity'] == 'BUG'
    fake_client.run_with_tools.assert_called_once()
    fake_client.call.assert_not_called()

    kwargs = fake_client.run_with_tools.call_args.kwargs
    assert 'tool_executor' in kwargs
    assert kwargs['max_tool_iterations'] == 1


def test_analyze_diff_without_context_fetcher_uses_plain_call():
    """Backward compatible default: no context_fetcher means no tool loop."""
    diff = "+x = 1\n"
    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.call.return_value = "[]"

    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        analyze_diff('file.py', diff_text=diff)

    fake_client.call.assert_called_once()
    fake_client.run_with_tools.assert_not_called()


def test_analyze_diff_tool_executor_delegates_to_context_fetcher():
    """The tool_executor passed to run_with_tools must call context_fetcher with the
    file path and the requested 1-based line range, and format numbered output."""
    diff = "+x = 1\n"
    file_lines = {i: f"content-{i}" for i in range(1, 51)}
    fetch_calls = []

    def fetcher(path, start, end):
        fetch_calls.append((path, start, end))
        return [file_lines[i] for i in range(start, end + 1)]

    captured = {}

    def fake_run_with_tools(prompt, tools, tool_executor, timeout=30, max_tool_iterations=1):
        captured['result'] = tool_executor('get_file_lines', {'start_line': 5, 'end_line': 7})
        return '[]', 1

    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.to_tool_schema.return_value = {}
    fake_client.run_with_tools.side_effect = fake_run_with_tools

    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        analyze_diff('file.py', diff_text=diff, context_fetcher=fetcher)

    assert fetch_calls == [('file.py', 5, 7)]
    assert captured['result'] == '5: content-5\n6: content-6\n7: content-7'


def test_analyze_diff_tool_executor_clamps_oversized_range():
    diff = "+x = 1\n"
    fetch_calls = []

    def fetcher(path, start, end):
        fetch_calls.append((start, end))
        return [f"l{i}" for i in range(start, end + 1)]

    def fake_run_with_tools(prompt, tools, tool_executor, timeout=30, max_tool_iterations=1):
        tool_executor('get_file_lines', {'start_line': 1, 'end_line': 10000})
        return '[]', 1

    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.to_tool_schema.return_value = {}
    fake_client.run_with_tools.side_effect = fake_run_with_tools

    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        analyze_diff('file.py', diff_text=diff, context_fetcher=fetcher)

    assert fetch_calls == [(1, 200)]


def test_analyze_diff_tool_executor_handles_unknown_tool_and_empty_result():
    diff = "+x = 1\n"

    def fetcher(path, start, end):
        return []

    results = {}

    def fake_run_with_tools(prompt, tools, tool_executor, timeout=30, max_tool_iterations=1):
        results['unknown'] = tool_executor('some_other_tool', {})
        results['empty'] = tool_executor('get_file_lines', {'start_line': 1, 'end_line': 5})
        return '[]', 2

    fake_client = mock.Mock(spec=OpenAIClient)
    fake_client.count_tokens.return_value = 1
    fake_client.to_tool_schema.return_value = {}
    fake_client.run_with_tools.side_effect = fake_run_with_tools

    with mock.patch('pr_pilot.llm.OpenAIClient', return_value=fake_client):
        analyze_diff('file.py', diff_text=diff, context_fetcher=fetcher)

    assert 'Unknown tool' in results['unknown']
    assert 'No content available' in results['empty']


def test_redis_budget_helper():
    from pr_pilot.redis_budget import check_and_decrement_budget

    class FakeRedis:
        def __init__(self):
            self.store = {}

        def eval(self, script, numkeys, key, amount, daily, ttl):
            # naive eval simulation using python
            cur = self.store.get(key)
            if cur is None:
                self.store[key] = int(daily)
                cur = int(daily)
            cur = int(self.store[key])
            if cur < int(amount):
                return -1
            self.store[key] = cur - int(amount)
            return int(self.store[key])

    r = FakeRedis()
    res = check_and_decrement_budget(r, 'testkey', 10, 100)
    assert res == 90
    res2 = check_and_decrement_budget(r, 'testkey', 1000, 100)
    assert res2 == -1 or res2 is None
