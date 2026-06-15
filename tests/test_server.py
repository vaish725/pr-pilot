from fastapi.testclient import TestClient
from pr_pilot.server import app


def test_webhook_ack():
    client = TestClient(app)
    resp = client.post("/webhook", json={"action": "opened"})
    assert resp.status_code == 200
    assert resp.json().get("status") == "received"
