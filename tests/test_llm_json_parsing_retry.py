from pr_pilot.llm import analyze_diff
from pr_pilot.llm_providers import OpenAIClient


def test_retry_flow_returns_valid_json(monkeypatch):
    """Simulate provider returning noisy output first, then valid JSON on retry."""

    noisy = "Here is my review:\n- Looks good.\n(See details above)"
    valid = '[{"line": 4, "message": "found issue", "suggestion": "fix it"}]'

    def fake_call(self, prompt, timeout=30):
        # If the prompt asks to 'Please respond with only a valid JSON array', return valid
        if 'Please respond with only a valid JSON array' in prompt:
            return valid
        # otherwise return noisy first
        return noisy

    monkeypatch.setattr(OpenAIClient, 'call', fake_call)

    suggestions = analyze_diff('file.py', 'a\nb\nc\n+new line\n')
    assert suggestions, "Expected suggestions after retry"
    assert suggestions[0]['line'] == 4
    assert suggestions[0]['message'] == 'found issue'
