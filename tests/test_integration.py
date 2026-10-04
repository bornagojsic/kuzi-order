"""Optional integration tests against the real Gemini API.

Auto-skipped unless GEMINI_API_KEY is set. Run with:
    GEMINI_API_KEY=... uv run pytest -m integration
"""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="GEMINI_API_KEY not set"),
]

from fastapi.testclient import TestClient  # noqa: E402

from app.gemini_client import GeminiClient  # noqa: E402
from app.main import app  # noqa: E402


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
