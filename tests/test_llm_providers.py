from pr_pilot.llm_providers import OpenAIClient, AnthropicClient


def test_openai_token_count_fallback():
    client = OpenAIClient(api_key="not-used", model="gpt-4o")
    text = "def foo():\n    return 42\n" * 50
    tokens = client.count_tokens(text)
    assert tokens > 0
    # heuristic should be proportional to input size
    assert tokens < len(text)


def test_anthropic_token_count_fallback():
    client = AnthropicClient(api_key="not-used", model="claude-2.1")
    text = "This is a sample sentence. " * 100
    tokens = client.count_tokens(text)
    assert tokens > 0
    assert tokens < len(text)


def test_anthropic_long_identifier_handling():
    client = AnthropicClient(api_key="not-used")
    # long identifier should be chunked into multiple tokens
    long_ident = "a" * 120
    tokens = client.count_tokens(long_ident)
    assert tokens >= 10
