import os
import time
import jwt
import requests
import pytest


RUN_TEST = os.getenv("RUN_GITHUB_APP_TEST") == "1"


pytestmark = pytest.mark.skipif(not RUN_TEST, reason="Integration test: enable with RUN_GITHUB_APP_TEST=1")


def load_env():
    app_id = os.getenv("GITHUB_APP_ID")
    key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH")
    test_repo = os.getenv("TEST_REPO", "vaish725/pr-pilot")
    assert app_id, "GITHUB_APP_ID must be set in env to run this test"
    assert key_path, "GITHUB_PRIVATE_KEY_PATH must be set in env to run this test"
    assert os.path.exists(key_path), f"private key file not found: {key_path}"
    return app_id, key_path, test_repo


def test_github_app_can_create_installation_token():
    """Generate a JWT from the app private key and exchange it for an installation token.

    This test performs read-only calls to GitHub: it looks up the installation for
    the given repo and requests an installation access token (which GitHub returns).
    It's guarded by RUN_GITHUB_APP_TEST=1 to avoid accidental network calls.
    """
    app_id, key_path, test_repo = load_env()

    with open(key_path, "r") as f:
        private_key = f.read()

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + (9 * 60), "iss": str(app_id)}
    jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

    headers = {"Authorization": f"Bearer {jwt_token}", "Accept": "application/vnd.github+json"}

    owner, repo = test_repo.split("/")
    url = f"https://api.github.com/repos/{owner}/{repo}/installation"
    r = requests.get(url, headers=headers)
    assert r.status_code == 200, f"Failed to find installation for {test_repo}: {r.status_code} {r.text}"
    installation = r.json()
    installation_id = installation.get("id")
    assert installation_id, "installation id missing from response"

    token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
    r2 = requests.post(token_url, headers=headers)
    assert r2.status_code == 201, f"Failed to create installation token: {r2.status_code} {r2.text}"
    data = r2.json()
    assert data.get("token"), "installation access token not returned"
