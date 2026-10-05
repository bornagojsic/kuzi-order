"""Optional integration tests against the real Gemini API.

Auto-skipped unless GEMINI_API_KEY is set (in the environment or in .env).
Run with:
    uv run pytest -m integration

Add --slow to pause 5s between test cases (free-tier rate-limit friendly):
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

SLOW_PAUSE_SECONDS = 5

# (order text, expected items as (id, quantity), expected unavailable as
# {(text, quantity)}) - unavailable item ordering is not contractual, so the
# texts are compared as a set.
UTTERANCE_CASES = [
    (
        "dva hamburgera, dvije margarite i jednu colu",
        [("margarita", 2), ("coca_cola", 1)],
        {("hamburger", 2)},
    ),
    ("dvije margarite i jednu colu", [("margarita", 2), ("coca_cola", 1)], set()),
    ("jednu kapričozu i dva piva molim", [("capricciosa", 1), ("pivo", 2)], set()),
    ("dva hamburgera i jednu margaritu", [("margarita", 1)], {("hamburger", 2)}),
    (
        "tri margarite i colu, ma ne, ipak dvije margarite",
        [("margarita", 2), ("coca_cola", 1)],
        set(),
    ),
    ("dvije margarite i još jednu margaritu", [("margarita", 3)], set()),
    ("dvije margarite, ma ne, tri", [("margarita", 3)], set()),
    ("tri margarite, ne dvije, zapravo jednu", [("margarita", 1)], set()),
    ("jednu kapriciozu", [("capricciosa", 1)], set()),
    ("daj jednu coca-colu", [("coca_cola", 1)], set()),
    ("hamburger", [], {("hamburger", 1)}),
    ("hamburger i jednu colu", [("coca_cola", 1)], {("hamburger", 1)}),
    ("hamburger i cheeseburger", [], {("hamburger", 1), ("cheeseburger", 1)}),
]


@pytest.fixture(autouse=True)
def slow_pause_between_api_calls(request: pytest.FixtureRequest):
    """With --slow, sleep 5s before every API test except the first."""
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


VEGETARIAN_FOOD_IDS = {"margarita", "vegetariana", "quattro_formaggi", "mijesana_salata"}


def test_real_vegetarian_question(client):
    response = client.post("/order", json={"text": "imate li nešto bez mesa za nas dvoje?"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == []
    assert set(body["suggestions"]) == VEGETARIAN_FOOD_IDS


def test_real_vegetarian_question_ignores_party_size(client):
    three = client.post("/order", json={"text": "imate li nešto bez mesa za nas troje?"})
    assert three.status_code == 200
    eight = client.post("/order", json={"text": "imate li nešto bez mesa za nas osmero?"})
    assert eight.status_code == 200
    assert (
        set(eight.json()["suggestions"]) == set(three.json()["suggestions"]) == VEGETARIAN_FOOD_IDS
    )


@pytest.mark.parametrize("text,expected_items,expected_unavailable", UTTERANCE_CASES)
def test_real_utterance(client, text, expected_items, expected_unavailable):
    response = client.post("/order", json={"text": text})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [{"id": i, "quantity": q} for i, q in expected_items]
    assert {(u["text"], u["quantity"]) for u in body["unavailable"]} == expected_unavailable
    assert body["suggestions"] == []
