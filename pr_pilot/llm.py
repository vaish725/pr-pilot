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


def analyze_diff(
    file_path: str,
    diff_text: str,
    timeout: int = 30,
    repo: Optional[str] = None,
    context_before: Optional[List[str]] = None,
    context_after: Optional[List[str]] = None,
    focus_instruction: str = "",
) -> List[Dict]:
    """Call configured LLM provider to analyze a file hunk and return structured suggestions.

    Returns a list of dicts: { file, line, severity, message, suggestion }
    - Uses OPENAI if LLM_PROVIDER=openai (default), else ANTHROPIC if configured.
    - Performs simple chunking when diff_text is large.
    - Enforces a per-repo daily token budget if REDIS_URL and LLM_DAILY_BUDGET_TOKENS are set.
    - context_before/context_after: up to N lines from the real file surrounding this hunk.
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
        "line (1-based index within the DIFF section), severity (INFO|STYLE|BUG|SECURITY), "
        "message (short summary), suggestion (concrete code change or explanation)."
        + (focus_instruction or "")
    )

    prefix_parts = [system, f"\n\nFILE: {file_path}"]
    if context_before:
        prefix_parts.append("\n\nCONTEXT BEFORE HUNK:\n" + "\n".join(context_before))
    prefix_parts.append("\n\nDIFF:\n")
    prompt_prefix = "".join(prefix_parts)

    suffix_parts = []
    if context_after:
        suffix_parts.append("\n\nCONTEXT AFTER HUNK:\n" + "\n".join(context_after))
    suffix_parts.append("\n\nRespond only with valid JSON array.")
    prompt_suffix = "".join(suffix_parts)

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
        prompt = prompt_prefix + chunk + prompt_suffix
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
                    logger.warning(
                        'LLM budget exhausted for %s (needed %s, remaining %s)',
                        repo, total_estimate, remaining,
                    )
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

    def _extract_json_array(resp_text: str) -> Optional[List]:
        """Attempt to extract a JSON array from noisy model output.

        Strategies:
        1. Try json.loads on the whole response.
        2. Find first balanced '[' ... ']' sequence and try to parse that.
        3. Clean common issues: trailing commas, single quotes -> double quotes heuristic.
        4. Fallback to ast.literal_eval on the candidate substring.
        Returns the parsed list or None.
        """
        import re
        import ast

        # 1) direct parse
        try:
            v = json.loads(resp_text)
            if isinstance(v, list):
                return v
        except Exception:
            pass

        # 2) find first balanced bracketed JSON array
        start = resp_text.find('[')
        if start == -1:
            return None

        depth = 0
        end = -1
        for i in range(start, len(resp_text)):
            ch = resp_text[i]
            if ch == '[':
                depth += 1
            elif ch == ']':
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end == -1:
            # no balanced array found
            return None

        candidate = resp_text[start:end+1]

        # try to clean trailing commas like `[{},]` -> `[{}]`
        candidate_clean = re.sub(r',\s*\]', ']', candidate)

        # if single quotes appear more than double quotes, try a conservative replace
        if candidate_clean.count("'") > candidate_clean.count('"'):
            cand2 = candidate_clean.replace("'", '"')
        else:
            cand2 = candidate_clean

        try:
            v = json.loads(cand2)
            if isinstance(v, list):
                return v
        except Exception:
            pass

        # fallback to literal_eval which accepts single quotes and pythonic dicts
        try:
            v = ast.literal_eval(candidate)
            if isinstance(v, list):
                return v
        except Exception:
            pass

        return None

    suggestions: List[Dict] = []
    for resp in responses:
        parsed = _extract_json_array(resp)
        # If parsing failed, attempt one gentle retry by asking the model to return only JSON.
        if parsed is None and 'client' in locals():
            try:
                retry_prompt = (
                    "The previous response included extra text. "
                    "Please respond with only a valid JSON array (e.g. [{{...}}, ...]) and nothing else."
                    "\nPrevious response:\n" + resp
                )
                retry_out = client.call(retry_prompt, timeout=max(5, timeout // 2))
                if retry_out:
                    parsed = _extract_json_array(retry_out)
            except Exception:
                logger.exception('Retry to fetch JSON from LLM failed')

        if not parsed:
            logger.warning('Failed to extract JSON array from LLM response (after retry): %s', resp)
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
    """Parse a unified diff into per-file hunk lists.

    Each hunk dict contains:
      old_start, old_lines, new_start, new_lines — from the @@ header
      lines                                       — body lines (context/+/-)
      position_start                              — GitHub position of the @@ line itself

    GitHub review comment positions are 1-based, counted from the first @@ line
    of each file's diff section. Every line (@@, context, +, -) increments the
    counter; diff --git / index / --- / +++ headers do NOT count.

    To get the GitHub position for body line at 1-based idx:
        position = hunk['position_start'] + idx
    """
    import re
    files = {}
    cur_file = None
    file_position = 0
    # Optional comma+count handles single-line hunks like "@@ -1 +1 @@"
    hunk_re = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith('+++ '):
            raw = ln[4:].strip()
            # Strip the git b/ prefix; ignore /dev/null (pure deletions)
            if raw == '/dev/null':
                cur_file = None
            else:
                cur_file = raw[2:] if raw.startswith('b/') else raw
                if cur_file not in files:
                    files[cur_file] = []
            file_position = 0  # position resets for each file
            i += 1
            continue
        m = hunk_re.match(ln)
        if m and cur_file:
            old_start = int(m.group(1))
            old_len = int(m.group(2)) if m.group(2) is not None else 1
            new_start = int(m.group(3))
            new_len = int(m.group(4)) if m.group(4) is not None else 1
            file_position += 1  # the @@ line counts as one position
            position_start = file_position
            i += 1
            hunk_lines = []
            while i < len(lines) and not lines[i].startswith('@@ ') and not lines[i].startswith('+++ '):
                hunk_lines.append(lines[i])
                file_position += 1
                i += 1
            files[cur_file].append({
                'old_start': old_start,
                'old_lines': old_len,
                'new_start': new_start,
                'new_lines': new_len,
                'lines': hunk_lines,
                'position_start': position_start,
            })
            continue
        i += 1
    return files
