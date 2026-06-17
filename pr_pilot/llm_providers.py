from typing import Optional
import os
import logging
import time

logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        try:
            import openai
        except Exception:
            openai = None
        self.openai = openai
        self.api_key = api_key or os.getenv('LLM_API_KEY')
        self.model = model or os.getenv('OPENAI_MODEL', 'gpt-4o')

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self.model)
            return len(enc.encode(text))
        except Exception:
            # Fallback heuristic: prefer a word-based estimate and a char-based estimate,
            # then take the max to avoid undercounting. Empirically tokens ~= 3-4 chars
            import re

            words = re.findall(r"\w+", text)
            word_est = len(words)
            char_est = max(1, int(len(text) / 3.5))
            return max(1, max(word_est, char_est))

    def call(self, prompt: str, timeout: int = 30) -> Optional[str]:
        if not self.openai:
            raise RuntimeError('openai package not installed')
        if not self.api_key:
            raise RuntimeError('LLM_API_KEY not set')
        self.openai.api_key = self.api_key
        backoff = 1
        for attempt in range(4):
            try:
                resp = self.openai.ChatCompletion.create(
                    model=self.model,
                    messages=[{"role": "system", "content": "You are a helpful code reviewer."},
                              {"role": "user", "content": prompt}],
                    max_tokens=512,
                    temperature=0.2,
                    request_timeout=timeout,
                )
                choices = resp.get('choices') or []
                if choices:
                    return choices[0].get('message', {}).get('content') or choices[0].get('text')
                return None
            except Exception as e:
                logger.warning('OpenAI attempt %s failed: %s', attempt + 1, e)
                if attempt == 3:
                    logger.exception('OpenAI requests exhausted')
                    raise
                time.sleep(backoff)
                backoff *= 2


class AnthropicClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        try:
            import anthropic
        except Exception:
            anthropic = None
        self.anthropic = anthropic
        self.api_key = api_key or os.getenv('LLM_API_KEY')
        self.model = model or os.getenv('ANTHROPIC_MODEL', 'claude-2.1')

    def count_tokens(self, text: str) -> int:
        # Anthropic often uses the cl100k_base encoding; try tiktoken with that.
        try:
            import tiktoken
            enc = tiktoken.get_encoding('cl100k_base')
            return len(enc.encode(text))
        except Exception:
            # Better fallback heuristic similar to OpenAI's: combine word and char estimates.
            import re

            words = re.findall(r"\w+", text)
            word_est = len(words)
            char_est = max(1, int(len(text) / 3.5))
            return max(1, max(word_est, char_est))

    def call(self, prompt: str, timeout: int = 30) -> Optional[str]:
        if not self.anthropic:
            raise RuntimeError('anthropic package not installed')
        if not self.api_key:
            raise RuntimeError('LLM_API_KEY not set')
        client = self.anthropic.Client(api_key=self.api_key)
        backoff = 1
        for attempt in range(4):
            try:
                resp = client.completions.create(
                    model=self.model,
                    prompt=prompt,
                    max_tokens_to_sample=512,
                    temperature=0.2,
                    stop_sequences=["\n\n"],
                )
                return resp.get('completion')
            except Exception as e:
                logger.warning('Anthropic attempt %s failed: %s', attempt + 1, e)
                if attempt == 3:
                    logger.exception('Anthropic requests exhausted')
                    raise
                time.sleep(backoff)
                backoff *= 2
