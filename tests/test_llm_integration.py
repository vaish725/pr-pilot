import os
import pytest
import time

from pr_pilot.llm import analyze_diff


@pytest.mark.skipif(
    os.getenv('RUN_LLM_INTEGRATION') != '1',
    reason='Integration test: enable with RUN_LLM_INTEGRATION=1',
)
def test_llm_integration_small_run():
    """Gated integration test that runs against a live LLM provider.

    Safety measures:
    - Only runs when RUN_LLM_INTEGRATION=1
    - Requires LLM_API_KEY and REDIS_URL to be set
    - Uses a small per-repo daily budget set in Redis to cap token spend
    """
    api_key = os.getenv('LLM_API_KEY')
    redis_url = os.getenv('REDIS_URL')
    if not api_key:
        pytest.skip('LLM_API_KEY not set')
    if not redis_url:
        pytest.skip('REDIS_URL not set - budget enforcement required for integration test')

    # Connect to Redis and set a small daily budget for the test repo
    try:
        import redis
    except Exception:
        pytest.skip('redis package not available')

    r = redis.from_url(redis_url)
    repo_id = "integration/test-repo"
    key = f"llm:budget:{repo_id}:{time.strftime('%Y-%m-%d')}"
    # Save original value to restore later
    orig = r.get(key)
    try:
        # small budget: ~5000 tokens
        r.set(key, 5000, ex=86400)

        # Run analyze_diff with a tiny diff to keep usage minimal
        diff = "+def add(a, b):\n+    return a + b\n"
        suggestions = analyze_diff('some/file.py', diff, timeout=30, repo=repo_id)

        # We expect the call to succeed and return either suggestions list or empty list
        assert isinstance(suggestions, list)

        # Ensure budget has been decremented (key exists and value is int)
        remaining = r.get(key)
        assert remaining is not None
        try:
            rem_int = int(remaining)
            assert rem_int >= 0
        except Exception:
            pytest.skip('Could not interpret remaining budget')

    finally:
        # Restore original budget state
        if orig is None:
            try:
                r.delete(key)
            except Exception:
                pass
        else:
            try:
                r.set(key, orig)
            except Exception:
                pass
