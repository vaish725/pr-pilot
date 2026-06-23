from typing import Optional
import os
import logging
import time
import asyncio
import threading

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

    async def stream(self, prompt: str, timeout: int = 30):
        """Async generator that yields partial output chunks if streaming supported, else yields full output once.

        If the underlying SDK provides a synchronous iterator, we run it in a background thread
        and push items onto an asyncio.Queue so we can yield them asynchronously.
        """
        if not self.openai:
            raise RuntimeError('openai package not installed')

        try:
            self.openai.api_key = self.api_key
            resp_iter = self.openai.ChatCompletion.create(
                model=self.model,
                messages=[{"role": "system", "content": "You are a helpful code reviewer."},
                          {"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.2,
                stream=True,
            )

            q: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _producer():
                try:
                    for event in resp_iter:
                        try:
                            if isinstance(event, dict):
                                choices = event.get('choices') or []
                                for c in choices:
                                    delta = c.get('delta') or {}
                                    if isinstance(delta, dict):
                                        content = delta.get('content')
                                        if content:
                                            loop.call_soon_threadsafe(q.put_nowait, content)
                        except Exception:
                            continue
                except Exception:
                    loop.call_soon_threadsafe(q.put_nowait, '[error]')
                finally:
                    loop.call_soon_threadsafe(q.put_nowait, None)

            t = threading.Thread(target=_producer, daemon=True)
            t.start()

            while True:
                part = await q.get()
                if part is None:
                    break
                yield part
        except Exception:
            # Fallback to single call
            out = self.call(prompt, timeout=timeout)
            if out:
                yield out


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
            # Better fallback heuristic approximating cl100k_base behavior.
            # Strategy:
            # - Split on word-like tokens and punctuation; count each as ~1 token.
            # - For long alphanumeric runs (like long identifiers), approximate BPE by
            #   splitting into chunks (~6 chars/token).
            # - Use a char-based lower bound to avoid undercounting for dense scripts.
            import re
            import math

            if not text:
                return 0

            # split into words and punctuation
            parts = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
            tokens = 0
            for p in parts:
                if re.match(r"^\w+$", p):
                    # alphanumeric run: approximate tokens by chunking into ~6-char pieces
                    tokens += max(1, math.ceil(len(p) / 6))
                else:
                    # punctuation or symbol -> count as single token
                    tokens += 1

            # char-based estimate (cl100k roughly 3-4 chars/token depending on language)
            char_est = max(1, int(len(text) / 3.3))

            return max(1, max(tokens, char_est))

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

    async def stream(self, prompt: str, timeout: int = 30):
        """Async stream: yield chunks for Anthropic if streaming supported; otherwise yield the full output once."""
        if not self.anthropic:
            raise RuntimeError('anthropic package not installed')

        try:
            client = self.anthropic.Client(api_key=self.api_key)
            try:
                # If the SDK exposes a synchronous streaming iterator, wrap it similar to OpenAI.
                resp_iter = client.completions.stream(model=self.model, prompt=prompt, max_tokens_to_sample=512)

                q: asyncio.Queue = asyncio.Queue()
                loop = asyncio.get_running_loop()

                def _producer():
                    try:
                        for evt in resp_iter:
                            try:
                                if isinstance(evt, dict):
                                    part = evt.get('completion')
                                    if part:
                                        loop.call_soon_threadsafe(q.put_nowait, part)
                            except Exception:
                                continue
                    except Exception:
                        loop.call_soon_threadsafe(q.put_nowait, '[error]')
                    finally:
                        loop.call_soon_threadsafe(q.put_nowait, None)

                t = threading.Thread(target=_producer, daemon=True)
                t.start()

                while True:
                    part = await q.get()
                    if part is None:
                        break
                    yield part
            except Exception:
                # Fallback to non-streaming
                out = client.completions.create(model=self.model, prompt=prompt, max_tokens_to_sample=512)
                if out:
                    yield out.get('completion')
        except Exception:
            out = self.call(prompt, timeout=timeout)
            if out:
                yield out
