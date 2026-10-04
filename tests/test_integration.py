"""Optional integration tests against the real Gemini API.

Auto-skipped unless GEMINI_API_KEY is set (in the environment or in .env).
Run with:
    uv run pytest -m integration

Add --slow to pause 30s between test cases (free-tier rate-limit friendly):
    uv run pytest -m integration --slow
"""

import os
import time

import pytest
from dotenv import load_dotenv

# Pick up .env before evaluating the skip condition below.
load_dotenv()

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"),
]

from fastapi.testclient import TestClient  # noqa: E402

from app.gemini_client import GeminiClient  # noqa: E402
from app.main import app  # noqa: E402

SLOW_PAUSE_SECONDS = 30


@pytest.fixture(autouse=True)
def slow_pause_between_api_calls(request: pytest.FixtureRequest):
    """With --slow, sleep 30s before every API test except the first."""
    if request.config.getoption("--slow"):
        if getattr(request.session, "_kuzi_api_tests_run", 0) > 0:
            time.sleep(SLOW_PAUSE_SECONDS)
    request.session._kuzi_api_tests_run = getattr(request.session, "_kuzi_api_tests_run", 0) + 1
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        test_client.app.state.gemini_client = GeminiClient()
        yield test_client


def test_real_happy_path(client):
    response = client.post("/order", json={"text": "dva hamburgera, dvije margarite i jednu colu"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [
        {"id": "margarita", "quantity": 2},
        {"id": "coca_cola", "quantity": 1},
    ]
    assert body["unavailable"] == [{"text": "hamburger", "quantity": 2}]


def test_real_vegetarian_question(client):
    response = client.post("/order", json={"text": "imate li nešto bez mesa za nas dvoje?"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert len(body["suggestions"]) > 0
