from typing import List, Dict, Optional
import os
import logging
import json

from datetime import datetime, timezone
from pr_pilot.llm_providers import OpenAIClient, AnthropicClient
from pr_pilot import metrics

logger = logging.getLogger(__name__)


def _split_into_chunks(text: str, max_tokens: int, counter) -> List[str]:
    """Split text into chunks using a provider token counter callable.

    counter: callable(text)->int
    """
    lines = text.splitlines()
    chunks: List[str] = []
    cur: List[str] = []
    cur_tokens = 0
    for line in lines:
        t = counter(line + "\n")
        if cur_tokens + t > max_tokens and cur:
            chunks.append("\n".join(cur))
            cur = [line]
            cur_tokens = t
        else:
            cur.append(line)
            cur_tokens += t
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def analyze_diff(file_path: str, diff_text: str, timeout: int = 30, repo: Optional[str] = None) -> List[Dict]:
    """Call configured LLM provider to analyze a file hunk and return structured suggestions.

    Returns a list of dicts: { file, line, severity, message, suggestion }
    - Uses OPENAI if LLM_PROVIDER=openai (default), else ANTHROPIC if configured.
    - Performs simple chunking when diff_text is large.
    - Enforces a per-repo daily token budget if REDIS_URL and LLM_DAILY_BUDGET_TOKENS are set.
    """
    provider_name = os.getenv('LLM_PROVIDER', os.getenv('PROVIDER', 'openai'))
    if provider_name and provider_name.lower().startswith('anthropic'):
        client = AnthropicClient()
        max_input_tokens = int(os.getenv('LLM_MAX_INPUT_TOKENS_ANTHROPIC', os.getenv('LLM_MAX_INPUT_TOKENS', '1500')))
    else:
        client = OpenAIClient()
        max_input_tokens = int(os.getenv('LLM_MAX_INPUT_TOKENS', '2000'))

    system = (
        "You are a code review assistant. Given a unified diff for a single file hunk, "
        "return a JSON array of review suggestions. Each suggestion must be an object with keys: "
        "line (1-based index within the provided hunk text), severity (INFO|STYLE|BUG|SECURITY), "
        "message (short summary), suggestion (concrete code change or explanation)."
    )

    prompt_prefix = system + "\n\nDIFF:\n"

    chunks = _split_into_chunks(diff_text, max_input_tokens, client.count_tokens)
    responses: List[str] = []

    # prepare redis if budgeting enabled
    redis_url = os.getenv('REDIS_URL')
    redis_conn = None
    if redis_url and repo:
        try:
            import redis
            redis_conn = redis.from_url(redis_url)
        except Exception:
            logger.exception('Failed to connect to Redis for budget enforcement')

    for chunk in chunks:
        prompt = prompt_prefix + chunk + "\n\nRespond only with valid JSON array."
        input_tokens = client.count_tokens(prompt)
        output_estimate = int(os.getenv('LLM_OUTPUT_ESTIMATE_TOKENS', '512'))
        total_estimate = input_tokens + output_estimate

        if redis_conn and repo:
            key = f"llm:budget:{repo}:{datetime.now(timezone.utc).date().isoformat()}"
            daily_budget = int(os.getenv('LLM_DAILY_BUDGET_TOKENS', '200000'))
            current = redis_conn.get(key)
            if current is None:
                try:
                    redis_conn.set(key, daily_budget, ex=86400)
                    remaining = daily_budget
                except Exception:
                    remaining = daily_budget
            else:
                remaining = int(current)

            # Use atomic check-and-decrement helper
            try:
                from pr_pilot.redis_budget import check_and_decrement_budget
                new_remaining = check_and_decrement_budget(redis_conn, key, total_estimate, daily_budget)
                if new_remaining == -1:
                    logger.warning('LLM budget exhausted for %s (needed %s, remaining %s)', repo, total_estimate, remaining)
                    try:
                        metrics.budget_exhausted.labels(repo=repo).inc()
                        metrics.budget_remaining.labels(repo=repo).set(0)
                    except Exception:
                        pass
                    continue
            except Exception:
                logger.exception('Failed to perform atomic budget decrement for key %s', key)

        try:
            out = client.call(prompt, timeout=timeout)
            if out:
                responses.append(out)
            # emit metrics for estimated tokens and call success
            try:
                metrics.tokens_used.labels(provider=type(client).__name__, repo=repo or 'unknown').inc(total_estimate)
                metrics.llm_calls.labels(provider=type(client).__name__, result='success').inc()
            except Exception:
                pass
        except Exception:
            logger.exception('LLM call failed for %s (provider=%s)', file_path, provider_name)
            try:
                metrics.llm_calls.labels(provider=type(client).__name__, result='failure').inc()
            except Exception:
                pass
            continue

    suggestions: List[Dict] = []
    for resp in responses:
        parsed = None
        try:
            parsed = json.loads(resp)
        except Exception:
            try:
                start = resp.index('[')
                end = resp.rindex(']')
                parsed = json.loads(resp[start:end+1])
            except Exception:
                logger.exception('Failed to extract JSON array from LLM response: %s', resp)
                continue

        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict) and 'line' in item:
                    item.setdefault('file', file_path)
                    item.setdefault('severity', 'STYLE')
                    item.setdefault('message', '')
                    item.setdefault('suggestion', '')
                    suggestions.append(item)

    return suggestions


def parse_diff_hunks(diff_text: str):
    """Parse a unified diff into hunks. Yields tuples (file_path, hunks) where hunks is a list of dicts.

    Each hunk dict contains: { 'old_start', 'old_lines', 'new_start', 'new_lines', 'lines' }
    This is a minimal parser sufficient for position mapping in the scaffold.
    """
    import re
    files = {}
    cur_file = None
    hunk_re = re.compile(r"@@ -(\d+),(\d+) \+(\d+),(\d+) @@")
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        l = lines[i]
        if l.startswith('+++ '):
            cur_file = l[4:].strip()
            files[cur_file] = []
            i += 1
            continue
        m = hunk_re.match(l)
        if m and cur_file:
            old_start, old_len, new_start, new_len = map(int, m.groups())
            i += 1
            hunk_lines = []
            # collect hunk body until next hunk header or file marker
            while i < len(lines) and not lines[i].startswith('@@ ') and not lines[i].startswith('+++ '):
                hunk_lines.append(lines[i])
                i += 1
            files[cur_file].append({
                'old_start': old_start,
                'old_lines': old_len,
                'new_start': new_start,
                'new_lines': new_len,
                'lines': hunk_lines,
            })
            continue
        i += 1
    return files


