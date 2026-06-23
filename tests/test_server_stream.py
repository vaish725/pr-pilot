import asyncio
from fastapi.testclient import TestClient
import pr_pilot.server as server


def _sync_gen():
    yield "a"
    yield "b"
    yield "c"


async def _async_gen():
    for v in ["a", "b", "c"]:
        await asyncio.sleep(0)
        yield v


class DummyOpenAIAsync:
    async def stream(self, prompt):
        # async generator
        for v in ["a", "b", "c"]:
            await asyncio.sleep(0)
            yield v


class DummyOpenAIError:
    async def stream(self, prompt):
        yield "first"
        raise RuntimeError("boom")


class DummyGH:
    def __init__(self, token):
        self.token = token

    def fetch_pr_diff(self, owner, repo, pr_number):
        return "diff --git a/foo.py b/foo.py\n+print('hello')\n"


def parse_sse(body: str):
    # returns list of data lines in order
    out = []
    for line in body.splitlines():
        if line.startswith('data:'):
            out.append(line[len('data:'):].strip())
    return out


def test_stream_ordering_and_completion(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'fake')
    monkeypatch.setattr(server, 'OpenAIClient', lambda: DummyOpenAIAsync())
    monkeypatch.setattr(server, 'GitHubClient', lambda token: DummyGH(token))

    client = TestClient(server.app)
    resp = client.post('/stream_review', json={"owner": "o", "repo": "r", "pr_number": 1})
    assert resp.status_code == 200
    assert resp.headers.get('content-type', '').startswith('text/event-stream')
    data = parse_sse(resp.text)
    assert data == ["a", "b", "c"]


def test_stream_mid_error_emits_sentinel(monkeypatch):
    monkeypatch.setenv('GITHUB_TOKEN', 'fake')
    monkeypatch.setattr(server, 'OpenAIClient', lambda: DummyOpenAIError())
    monkeypatch.setattr(server, 'GitHubClient', lambda token: DummyGH(token))

    client = TestClient(server.app)
    resp = client.post('/stream_review', json={"owner": "o", "repo": "r", "pr_number": 1})
    assert resp.status_code == 200
    data = parse_sse(resp.text)
    # should contain the first chunk and then the error sentinel
    assert data[0] == 'first'
    assert '[error]' in data
