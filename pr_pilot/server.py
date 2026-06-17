from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import hmac
import hashlib
import os
from pydantic import BaseModel
try:
    from rq import Queue
    from redis import Redis
    RQ_AVAILABLE = True
except Exception:
    Queue = None
    Redis = None
    RQ_AVAILABLE = False
    import threading

from pr_pilot.github_client import GitHubClient
from pr_pilot.llm import analyze_diff, parse_diff_hunks
from pr_pilot.worker import process_pr_job
try:
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
except Exception:
    generate_latest = None
    CONTENT_TYPE_LATEST = 'text/plain; version=0.0.4; charset=utf-8'

app = FastAPI(title="pr-pilot webhook")


@app.get('/metrics')
async def metrics_endpoint():
    if not generate_latest:
        return JSONResponse({'error': 'metrics not available'}, status_code=501)
    data = generate_latest()
    return JSONResponse(content=data.decode('utf-8'), media_type=CONTENT_TYPE_LATEST)


def verify_signature(secret: str, signature: str, payload: bytes) -> bool:
    if not signature:
        return False
    sha_name, signature = signature.split('=', 1)
    if sha_name != 'sha256':
        return False
    mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)


@app.post("/webhook")
async def webhook(request: Request, x_hub_signature_256: str | None = Header(None)):
    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret:
        if not verify_signature(secret, x_hub_signature_256 or "", body):
            raise HTTPException(status_code=401, detail="Invalid signature")

    # Immediately ack the webhook and enqueue work to Redis/RQ.
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    # Extract repo and PR number if present
    action = payload.get('action')
    pr = payload.get('pull_request') or {}
    repo = payload.get('repository') or {}
    owner = repo.get('owner', {}).get('login')
    repo_name = repo.get('name')
    pr_number = pr.get('number')

    # Enqueue job if we have required info
    if owner and repo_name and pr_number:
        if RQ_AVAILABLE:
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            redis_conn = Redis.from_url(redis_url)
            q = Queue('pr-jobs', connection=redis_conn)
            q.enqueue(process_pr_job, {"owner": owner, "repo": repo_name, "pr_number": pr_number})
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


class SimulateRequest(BaseModel):
    owner: str
    repo: str
    pr_number: int


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
    comments = []
    # For each file, call the dummy analyzer on the hunk text and map results.
    for file_path, hunks in files.items():
        for hunk in hunks:
            hunk_text = "\n".join(hunk['lines'])
            suggestions = analyze_diff(file_path, hunk_text)
            # Map suggestion 'line' (which is index in hunk_text) to GitHub 'position' as offset in the hunk
            pos = 0
            for idx, line in enumerate(hunk['lines'], start=1):
                # GitHub position counts lines in the diff hunk body; we use idx as a proxy
                if line.startswith('+') and not line.startswith('+++'):
                    # Create a comment for this position if any suggestion matches this hunk index
                    for s in suggestions:
                        # s['line'] is the index in the hunk_text; compare to idx
                        if s.get('line') == idx:
                            comments.append({
                                'path': file_path,
                                'position': idx,
                                'body': f"[{s.get('severity')}] {s.get('message')}\n\nSuggestion: {s.get('suggestion')}",
                            })

    # If DO_POST=1 then post to GitHub, otherwise return the comments for inspection
    if os.getenv('DO_POST') == '1' and comments:
        review = gh.post_review(req.owner, req.repo, req.pr_number, comments)
        return {"posted": True, "review_id": getattr(review, 'id', None)}

    return {"posted": False, "comments": comments}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pr_pilot.server:app", host="127.0.0.1", port=8000, log_level="info")
