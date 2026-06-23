import re
from pr_pilot.llm import _split_into_chunks
from pr_pilot.llm_providers import OpenAIClient


def word_counter(text: str) -> int:
    return len(re.findall(r"\w+", text))


def tokens_of_chunk(chunk: str, counter) -> int:
    # sum token counts line-by-line to match how splitting counts tokens
    total = 0
    for line in chunk.splitlines():
        total += counter(line + "\n")
    return total


def _norm(s: str):
    parts = s.split('\n')
    while parts and parts[-1] == '':
        parts.pop()
    return parts


def test_split_with_simple_counter():
    # Create 30 lines, each with 3 words -> 90 words total
    lines = ["one two three" for _ in range(30)]
    text = "\n".join(lines)
    max_tokens = 20
    chunks = _split_into_chunks(text, max_tokens, word_counter)

    assert len(chunks) > 1
    # Each chunk token sum must be <= max_tokens
    for ch in chunks:
        assert tokens_of_chunk(ch, word_counter) <= max_tokens

    # Reassembly should preserve content (ignoring trailing newline differences)
    reassembled = "\n".join(chunks)

    def _norm(s: str):
        parts = s.split('\n')
        while parts and parts[-1] == '':
            parts.pop()
        return parts

    assert _norm(reassembled) == _norm(text)


def test_split_with_provider_counter_fallback():
    client = OpenAIClient(api_key="none", model="gpt-4o")
    # Use content with varying length lines
    lines = ["def foo(): pass" if i % 3 == 0 else "a b c d e f g" for i in range(60)]
    text = "\n".join(lines)
    # Use a small max so multiple chunks are produced
    max_tokens = 50
    chunks = _split_into_chunks(text, max_tokens, client.count_tokens)

    assert len(chunks) > 1
    for ch in chunks:
        assert tokens_of_chunk(ch, client.count_tokens) <= max_tokens

    # Reassembly check
    reassembled = "\n".join(chunks)
    assert _norm(reassembled) == _norm(text)
