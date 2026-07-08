from typing import Callable, Optional
import json
import os
import logging
import time
import asyncio
import threading

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = "You are a helpful code reviewer."


class OpenAIClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv('LLM_API_KEY')
        self.model = model or os.getenv('OPENAI_MODEL', 'gpt-4o')
        self._openai = None

    def _sdk(self):
        if self._openai is None:
            try:
                import openai
                self._openai = openai
            except ImportError:
                pass
        return self._openai

    def _client(self, timeout: int = 30):
        sdk = self._sdk()
        if sdk is None:
            raise RuntimeError('openai package not installed')
        if not self.api_key:
            raise RuntimeError('LLM_API_KEY not set')
        return sdk.OpenAI(api_key=self.api_key, timeout=float(timeout))

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.encoding_for_model(self.model)
            return len(enc.encode(text))
        except Exception:
            import re
            words = re.findall(r"\w+", text)
            word_est = len(words)
            char_est = max(1, int(len(text) / 3.5))
            return max(1, max(word_est, char_est))

    def call(self, prompt: str, timeout: int = 30) -> Optional[str]:
        client = self._client(timeout)
        backoff = 1
        for attempt in range(4):
            try:
                resp = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=512,
                    temperature=0.2,
                )
                return resp.choices[0].message.content
            except Exception as e:
                logger.warning('OpenAI attempt %s failed: %s', attempt + 1, e)
                if attempt == 3:
                    logger.exception('OpenAI requests exhausted')
                    raise
                time.sleep(backoff)
                backoff *= 2
        return None

    @staticmethod
    def to_tool_schema(spec: dict) -> dict:
        """Convert a generic {name, description, parameters} tool spec into the
        OpenAI chat.completions `tools` shape."""
        return {
            'type': 'function',
            'function': {
                'name': spec['name'],
                'description': spec['description'],
                'parameters': spec['parameters'],
            },
        }

    def run_with_tools(
        self, prompt: str, tools: list, tool_executor: Callable[[str, dict], str],
        timeout: int = 30, max_tool_iterations: int = 1,
    ):
        """Run a bounded multi-turn tool-calling loop.

        The model may call a tool instead of answering immediately; when it does,
        tool_executor(name, arguments) is invoked and its string result is fed back
        so the model can re-plan its answer with that extra context. Returns
        (final_text, tool_call_count).
        """
        client = self._client(timeout)
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        tool_call_count = 0
        for _ in range(max_tool_iterations + 1):
            resp = client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                max_tokens=512,
                temperature=0.2,
            )
            msg = resp.choices[0].message
            tool_calls = getattr(msg, 'tool_calls', None)
            if tool_calls and tool_call_count < max_tool_iterations:
                messages.append({
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in tool_calls
                    ],
                })
                for tc in tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or '{}')
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    result = tool_executor(tc.function.name, args)
                    tool_call_count += 1
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue
            return msg.content or '', tool_call_count
        return '', tool_call_count

    async def stream(self, prompt: str, timeout: int = 30):
        """Async generator that yields text chunks from a streaming OpenAI call."""
        try:
            client = self._client(timeout)
            resp_iter = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=512,
                temperature=0.2,
                stream=True,
            )

            q: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _producer():
                try:
                    for chunk in resp_iter:
                        if chunk.choices:
                            content = chunk.choices[0].delta.content
                            if content:
                                loop.call_soon_threadsafe(q.put_nowait, content)
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
            out = self.call(prompt, timeout=timeout)
            if out:
                yield out


class AnthropicClient:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv('LLM_API_KEY')
        self.model = model or os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6')
        self._anthropic = None

    def _sdk(self):
        if self._anthropic is None:
            try:
                import anthropic
                self._anthropic = anthropic
            except ImportError:
                pass
        return self._anthropic

    def _client(self, timeout: int = 30):
        sdk = self._sdk()
        if sdk is None:
            raise RuntimeError('anthropic package not installed')
        if not self.api_key:
            raise RuntimeError('LLM_API_KEY not set')
        return sdk.Anthropic(api_key=self.api_key, timeout=float(timeout))

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding('cl100k_base')
            return len(enc.encode(text))
        except Exception:
            import re
            import math

            if not text:
                return 0

            parts = re.findall(r"\w+|[^\w\s]", text, re.UNICODE)
            tokens = 0
            for p in parts:
                if re.match(r"^\w+$", p):
                    tokens += max(1, math.ceil(len(p) / 6))
                else:
                    tokens += 1

            char_est = max(1, int(len(text) / 3.3))
            return max(1, max(tokens, char_est))

    def call(self, prompt: str, timeout: int = 30) -> Optional[str]:
        client = self._client(timeout)
        backoff = 1
        for attempt in range(4):
            try:
                resp = client.messages.create(
                    model=self.model,
                    max_tokens=512,
                    temperature=0.2,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.content[0].text
            except Exception as e:
                logger.warning('Anthropic attempt %s failed: %s', attempt + 1, e)
                if attempt == 3:
                    logger.exception('Anthropic requests exhausted')
                    raise
                time.sleep(backoff)
                backoff *= 2
        return None

    @staticmethod
    def to_tool_schema(spec: dict) -> dict:
        """Convert a generic {name, description, parameters} tool spec into the
        Anthropic messages `tools` shape."""
        return {
            'name': spec['name'],
            'description': spec['description'],
            'input_schema': spec['parameters'],
        }

    def run_with_tools(
        self, prompt: str, tools: list, tool_executor: Callable[[str, dict], str],
        timeout: int = 30, max_tool_iterations: int = 1,
    ):
        """Run a bounded multi-turn tool-calling loop.

        Mirrors OpenAIClient.run_with_tools but speaks Anthropic's tool_use /
        tool_result content-block protocol. Returns (final_text, tool_call_count).
        """
        client = self._client(timeout)
        messages = [{"role": "user", "content": prompt}]
        tool_call_count = 0
        for _ in range(max_tool_iterations + 1):
            resp = client.messages.create(
                model=self.model,
                max_tokens=512,
                temperature=0.2,
                system=_SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
            tool_use_blocks = [b for b in resp.content if getattr(b, 'type', None) == 'tool_use']
            if tool_use_blocks and tool_call_count < max_tool_iterations:
                messages.append({"role": "assistant", "content": resp.content})
                result_blocks = []
                for block in tool_use_blocks:
                    result = tool_executor(block.name, block.input or {})
                    tool_call_count += 1
                    result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    })
                messages.append({"role": "user", "content": result_blocks})
                continue
            text = ''.join(b.text for b in resp.content if getattr(b, 'type', None) == 'text')
            return text, tool_call_count
        return '', tool_call_count

    async def stream(self, prompt: str, timeout: int = 30):
        """Async generator that yields text chunks from a streaming Anthropic call."""
        try:
            client = self._client(timeout)

            q: asyncio.Queue = asyncio.Queue()
            loop = asyncio.get_running_loop()

            def _producer():
                try:
                    with client.messages.stream(
                        model=self.model,
                        max_tokens=512,
                        system=_SYSTEM_PROMPT,
                        messages=[{"role": "user", "content": prompt}],
                    ) as stream:
                        for text in stream.text_stream:
                            if text:
                                loop.call_soon_threadsafe(q.put_nowait, text)
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
            out = self.call(prompt, timeout=timeout)
            if out:
                yield out
