from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
import hmac
import hashlib
import logging
import os
import threading
import time
import uuid
from pydantic import BaseModel

try:
    from rq import Queue, Retry
    from redis import Redis
    RQ_AVAILABLE = True
except Exception:
    Queue = None
    Retry = None
    Redis = None
    RQ_AVAILABLE = False

from pr_pilot.exceptions import LLMUnavailableError
from pr_pilot.github_client import GitHubClient
from pr_pilot.llm import analyze_diff, parse_diff_hunks
from pr_pilot.llm_providers import OpenAIClient, AnthropicClient
from pr_pilot.logging_config import configure_logging, reset_request_id, set_request_id
from pr_pilot.retry import review_failure_callback, MAX_RETRIES, RETRY_INTERVALS
from pr_pilot.review_summary import build_review_summary
from pr_pilot.worker import process_pr_job

_server_logger = logging.getLogger(__name__)
# SimulateRequest is defined later in this module; do not import it from elsewhere
try:
    import importlib
    _prom = importlib.import_module('prometheus_client')
    generate_latest = getattr(_prom, 'generate_latest')
    CONTENT_TYPE_LATEST = getattr(_prom, 'CONTENT_TYPE_LATEST', 'text/plain; version=0.0.4; charset=utf-8')
except Exception:
    generate_latest = None
    CONTENT_TYPE_LATEST = 'text/plain; version=0.0.0; charset=utf-8'

_REACTION_BODIES = {'+1', '-1', '👍', '👎'}
_POSITIVE_REACTIONS = {'+1', '👍'}


@asynccontextmanager
async def _lifespan(application: FastAPI):
    configure_logging()
    if os.getenv('DATABASE_URL'):
        try:
            from pr_pilot.db import init_db
            init_db()
        except Exception:
            _server_logger.exception('DB init failed on startup')
    yield


app = FastAPI(title="pr-pilot webhook", lifespan=_lifespan)


@app.middleware('http')
async def _request_id_middleware(request: Request, call_next):
    request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
    token = set_request_id(request_id)
    start = time.monotonic()
    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        _server_logger.info(
            '%s %s', request.method, request.url.path,
            extra={'duration_ms': duration_ms, 'status_code': response.status_code},
        )
        response.headers['X-Request-ID'] = request_id
        return response
    except Exception as exc:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        _server_logger.error(
            '%s %s failed', request.method, request.url.path,
            extra={'duration_ms': duration_ms, 'error': str(exc)},
            exc_info=True,
        )
        raise
    finally:
        reset_request_id(token)


class SimulateRequest(BaseModel):
    owner: str
    repo: str
    pr_number: int


@app.get('/metrics')
async def metrics_endpoint():
    if not generate_latest:
        return JSONResponse({'error': 'metrics not available'}, status_code=501)
    data = generate_latest()
    return JSONResponse(content=data.decode('utf-8'), media_type=CONTENT_TYPE_LATEST)


@app.post('/stream_review')
async def stream_review(req: SimulateRequest):
    """Stream the LLM review output for a single hunk as SSE (text/event-stream).

    This is a demo endpoint for local testing. It streams the provider.stream() output.
    """
    # choose provider
    provider_name = os.getenv('LLM_PROVIDER', os.getenv('PROVIDER', 'openai'))
    if provider_name and provider_name.lower().startswith('anthropic'):
        client = AnthropicClient()
    else:
        client = OpenAIClient()

    # build prompt from PR diff
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise HTTPException(status_code=400, detail="GITHUB_TOKEN not set in env")

    gh = GitHubClient(token=token)
    diff = gh.fetch_pr_diff(req.owner, req.repo, req.pr_number)
    if not diff:
        raise HTTPException(status_code=400, detail="empty diff")

    # For demo: stream the whole diff as prompt
    prompt = (
        "You are a code reviewer. Return short textual review comments as you generate them."
        "\n\nDIFF:\n" + diff
    )

    async def event_stream():
        # Providers now expose async generators; consume them with async for.
        try:
            async for part in client.stream(prompt):
                yield f"data: {part}\n\n"
        except Exception:
            # emit an error sentinel for clients to observe
            yield "data: [error]\n\n"

    return StreamingResponse(event_stream(), media_type='text/event-stream')


def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not signature:
        return False
    sha_name, signature = signature.split('=', 1)
    if sha_name != 'sha256':
        return False
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)


@app.post("/webhook")
async def webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
):
    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        if not verify_signature(secret, x_hub_signature_256 or "", body):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        payload = {}

    repo_info = payload.get('repository') or {}
    owner = repo_info.get('owner', {}).get('login')
    repo_name = repo_info.get('name')

    # Handle reaction replies on review comments for acceptance rate tracking
    if x_github_event == 'pull_request_review_comment' and os.getenv('DATABASE_URL'):
        action = payload.get('action')
        comment = payload.get('comment', {})
        comment_body = comment.get('body', '').strip()
        in_reply_to_id = comment.get('in_reply_to_id')
        user_login = comment.get('user', {}).get('login')
        pr_number_rc = (payload.get('pull_request') or {}).get('number')

        if action == 'created' and in_reply_to_id and comment_body in _REACTION_BODIES:
            reaction_str = '+1' if comment_body in _POSITIVE_REACTIONS else '-1'
            try:
                from pr_pilot.db import get_session, init_db
                from pr_pilot.models import CommentReaction
                init_db()
                with get_session() as session:
                    rec = CommentReaction(
                        owner=owner or '',
                        repo=repo_name or '',
                        pr_number=pr_number_rc or 0,
                        github_comment_id=in_reply_to_id,
                        reaction=reaction_str,
                        user_login=user_login,
                    )
                    session.merge(rec)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('Failed to record reaction for comment %s', in_reply_to_id)
        return JSONResponse({"status": "received"})

    # Handle pull_request events — enqueue a review job
    pr = payload.get('pull_request') or {}
    pr_number = pr.get('number')

    if owner and repo_name and pr_number:
        if RQ_AVAILABLE:
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            redis_conn = Redis.from_url(redis_url)
            q = Queue('pr-jobs', connection=redis_conn)
            q.enqueue(
                process_pr_job,
                {"owner": owner, "repo": repo_name, "pr_number": pr_number},
                retry=Retry(max=MAX_RETRIES, interval=RETRY_INTERVALS),
                on_failure=review_failure_callback,
            )
        else:
            # Fallback: run in background thread (no persistence)
            def _bg():
                try:
                    process_pr_job({"owner": owner, "repo": repo_name, "pr_number": pr_number})
                except Exception:
                    logger = __import__('logging').getLogger(__name__)
                    logger.exception('Background job failed')

            t = threading.Thread(target=_bg, daemon=True)
            t.start()

    return JSONResponse({"status": "received"})


@app.post("/simulate_review")
async def simulate_review(req: SimulateRequest):
    """Fetch PR diff, run dummy LLM, map suggestions to GitHub positions, and optionally post.

    This endpoint is for local testing and demo only.
    """
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise HTTPException(status_code=400, detail="GITHUB_TOKEN not set in env")

    gh = GitHubClient(token=token)
    diff = gh.fetch_pr_diff(req.owner, req.repo, req.pr_number)
    if not diff:
        return JSONResponse({"error": "empty diff"}, status_code=400)

    files = parse_diff_hunks(diff)
    head_sha = getattr(gh, '_last_head_sha', None)
    _CONTEXT_LINES = int(os.getenv('LLM_CONTEXT_LINES', '20'))

    cfg = gh.fetch_reviewbot_config(req.owner, req.repo, head_sha) if head_sha else None
    if cfg is None:
        from pr_pilot.config import ReviewConfig
        cfg = ReviewConfig()

    if not cfg.enabled:
        return JSONResponse({"skipped": "disabled", "comments": []})

    comments = []
    file_lines_cache: dict = {}
    files_reviewed = 0
    for file_path, hunks in files.items():
        if not cfg.should_review_file(file_path):
            continue
        files_reviewed += 1

        if head_sha and file_path not in file_lines_cache:
            file_lines_cache[file_path] = gh.fetch_file_content(req.owner, req.repo, file_path, head_sha)
        file_lines = file_lines_cache.get(file_path, [])

        for hunk in hunks:
            hunk_text = "\n".join(hunk['lines'])

            ctx_before: list = []
            ctx_after: list = []
            if file_lines:
                new_start_idx = hunk['new_start'] - 1
                new_end_idx = new_start_idx + hunk['new_lines']
                ctx_before = file_lines[max(0, new_start_idx - _CONTEXT_LINES):new_start_idx]
                ctx_after = file_lines[new_end_idx:new_end_idx + _CONTEXT_LINES]

            try:
                suggestions = analyze_diff(
                    file_path, hunk_text,
                    context_before=ctx_before or None,
                    context_after=ctx_after or None,
                    focus_instruction=cfg.focus_instruction(),
                )
            except LLMUnavailableError as exc:
                return JSONResponse(
                    {"error": "LLM unavailable", "detail": str(exc), "retryable": True},
                    status_code=503,
                )
            position_start = hunk['position_start']
            for idx, line in enumerate(hunk['lines'], start=1):
                if line.startswith('+') and not line.startswith('+++'):
                    github_position = position_start + idx
                    for s in suggestions:
                        if s.get('line') == idx:
                            comments.append({
                                'path': file_path,
                                'position': github_position,
                                'body': (
                                    f"[{s.get('severity')}] {s.get('message')}"
                                    f"\n\nSuggestion: {s.get('suggestion')}"
                                ),
                            })

    comments = comments[:cfg.max_comments]
    summary = build_review_summary(comments, files_reviewed)

    # If DO_POST=1 then post to GitHub, otherwise return the comments for inspection
    if os.getenv('DO_POST') == '1' and comments:
        review = gh.post_review(req.owner, req.repo, req.pr_number, comments, body=summary)
        return {"posted": True, "review_id": getattr(review, 'id', None), "summary": summary}

    return {"posted": False, "comments": comments, "summary": summary}


@app.get('/stats/{owner}/{repo}')
async def repo_stats(owner: str, repo: str):
    """Return aggregated review history and acceptance rate for a repo."""
    if not os.getenv('DATABASE_URL'):
        return JSONResponse({'error': 'DATABASE_URL not configured'}, status_code=501)
    try:
        from pr_pilot.db import get_session, init_db
        from pr_pilot.models import ReviewRun, ReviewComment, CommentReaction
        from sqlalchemy import func, select
        init_db()
        with get_session() as session:
            total_reviews = session.scalar(
                select(func.count()).select_from(ReviewRun).where(
                    ReviewRun.owner == owner, ReviewRun.repo == repo,
                )
            ) or 0

            total_comments = session.scalar(
                select(func.count()).select_from(ReviewComment)
                .join(ReviewRun)
                .where(ReviewRun.owner == owner, ReviewRun.repo == repo)
            ) or 0

            severity_rows = session.execute(
                select(ReviewComment.severity, func.count())
                .join(ReviewRun)
                .where(ReviewRun.owner == owner, ReviewRun.repo == repo)
                .group_by(ReviewComment.severity)
            ).all()
            severity_breakdown = {sev: cnt for sev, cnt in severity_rows if sev}

            reaction_rows = session.execute(
                select(CommentReaction.reaction, func.count())
                .where(CommentReaction.owner == owner, CommentReaction.repo == repo)
                .group_by(CommentReaction.reaction)
            ).all()
            reaction_counts = {r: cnt for r, cnt in reaction_rows}
            positive = reaction_counts.get('+1', 0)
            negative = reaction_counts.get('-1', 0)
            total_reactions = positive + negative
            acceptance_rate = round(positive / total_reactions, 3) if total_reactions > 0 else None

        return {
            'owner': owner,
            'repo': repo,
            'total_reviews': total_reviews,
            'total_comments': total_comments,
            'total_reactions': total_reactions,
            'acceptance_rate': acceptance_rate,
            'severity_breakdown': severity_breakdown,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pr_pilot.server:app", host="127.0.0.1", port=8000, log_level="info")
