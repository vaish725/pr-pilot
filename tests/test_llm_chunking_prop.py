try:
    from hypothesis import given, strategies as st
except Exception:  # pragma: no cover - skip when hypothesis isn't installed
    import pytest

    pytest.skip("Hypothesis not installed; skipping property-based chunking tests", allow_module_level=True)

from pr_pilot.llm import _split_into_chunks
from pr_pilot.llm_providers import OpenAIClient
import re


def simple_counter(text: str) -> int:
    return len(re.findall(r"\w+", text))

# avoid control characters which interact badly with splitting; allow printable characters only
safe_text = st.text(min_size=0, max_size=80, alphabet=st.characters(blacklist_categories=('Cc',)))


@given(
    lines=st.lists(safe_text, min_size=1, max_size=200),
    max_tokens=st.integers(min_value=5, max_value=200),
)
def test_chunking_invariants(lines, max_tokens):
    text = "\n".join(lines)
    chunks = _split_into_chunks(text, max_tokens, simple_counter)

    def _norm(s: str):
        parts = s.split('\n')
        while parts and parts[-1] == '':
            parts.pop()
        return parts

    # reassembly should equal original modulo trailing empty lines (splitlines semantics)
    assert _norm("\n".join(chunks)) == _norm(text)

    # each chunk token count must be <= max_tokens unless a single line exceeds max_tokens
    for ch in chunks:
        token_count = sum(simple_counter(line + "\n") for line in ch.splitlines())
        lines_in_chunk = ch.splitlines()
        if any(simple_counter(line + "\n") > max_tokens for line in lines_in_chunk):
            # if a single line is bigger than max_tokens, it's expected we may exceed
            continue
        assert token_count <= max_tokens
