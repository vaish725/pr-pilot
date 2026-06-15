from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
import hmac
import hashlib
import os

app = FastAPI(title="pr-pilot webhook")


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

    # Immediately ack the webhook to keep GitHub happy; real work should be enqueued.
    return JSONResponse({"status": "received"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("pr_pilot.server:app", host="127.0.0.1", port=8000, log_level="info")
