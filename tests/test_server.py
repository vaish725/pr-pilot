from fastapi.testclient import TestClient
from pr_pilot.server import app
import os
import hmac
import hashlib


def test_webhook_ack():
    client = TestClient(app)
    payload = b"{\"action\": \"opened\"}"
    headers = {"Content-Type": "application/json"}
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if secret:
        mac = hmac.new(secret.encode(), msg=payload, digestmod=hashlib.sha256)
        headers["X-Hub-Signature-256"] = "sha256=" + mac.hexdigest()
    resp = client.post("/webhook", data=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json().get("status") == "received"
