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
