from pr_pilot.llm import analyze_diff
from pr_pilot.llm_providers import OpenAIClient


def test_extract_plain_json_array(monkeypatch):
    resp = '[{"line": 1, "severity": "STYLE", "message": "X", "suggestion": "Y"}]'

    def fake_call(self, prompt, timeout=30):
        return resp

    monkeypatch.setattr(OpenAIClient, 'call', fake_call)
    suggestions = analyze_diff('f.py', 'line1\nline2')
    assert suggestions and suggestions[0]['line'] == 1


def test_extract_wrapped_json(monkeypatch):
    resp = 'Here is my review:\n```json\n[{"line":2, "message": "issue"}]\n```\nThanks'

    monkeypatch.setattr(OpenAIClient, 'call', lambda self, prompt, timeout=30: resp)
    suggestions = analyze_diff('f.py', 'a\nb\nc')
    assert suggestions and suggestions[0]['line'] == 2


def test_extract_single_quotes_and_trailing_commas(monkeypatch):
    resp = "[{'line':3, 'message': 'ok',}, ] extra text"
    monkeypatch.setattr(OpenAIClient, 'call', lambda self, prompt, timeout=30: resp)
    suggestions = analyze_diff('f.py', 'x\ny\nz')
    assert suggestions and suggestions[0]['line'] == 3
