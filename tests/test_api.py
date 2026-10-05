"""API tests using FastAPI's TestClient with a fake Gemini client - no real calls."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.gemini_client import GeminiClient, GeminiError
from app.main import app
from app.schemas import GeminiOrder, GeminiOutput


class FakeGeminiClient:
    """Stand-in for GeminiClient with a scripted list of responses.

    Each response is either a GeminiOutput (success) or an Exception to raise.
    """

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def parse_order(self, prompt: str) -> GeminiOutput:
        self.calls.append(prompt)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def parse_order_with_feedback(
        self, prompt: str, previous: str, errors: list[str]
    ) -> GeminiOutput:
        self.calls.append(f"RETRY with errors: {errors}")
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class _ScriptedSDK:
    """Stand-in for google.genai.Client: scripted JSON payloads or exceptions."""

    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []
        self.models = self

    def generate_content(self, **kwargs):
        self.calls.append(kwargs["contents"])
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return SimpleNamespace(text=result.model_dump_json())


class _TransientError(Exception):
    def __init__(self) -> None:
        super().__init__("503 UNAVAILABLE: the model is overloaded")


def output(**overrides) -> GeminiOutput:
    data = {
        "intent": "order",
        "items": [{"id": "margarita", "quantity": 2}, {"id": "coca_cola", "quantity": 1}],
        "unavailable": [{"text": "hamburger", "quantity": 2}],
        "suggestions": [],
    }
    data.update(overrides)
    return GeminiOutput(order=GeminiOrder(**data))


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def set_gemini(client: TestClient, fake: FakeGeminiClient) -> FakeGeminiClient:
    client.app.state.gemini_client = fake
    return fake


def post_order(client: TestClient, body: dict):
    return client.post("/order", json=body)


class TestOrder:
    def test_basic_order(self, client):
        fake = set_gemini(client, FakeGeminiClient([output()]))
        response = post_order(client, {"text": "dvije margarite i jednu colu"})
        assert response.status_code == 200
        assert response.json() == {
            "items": [
                {"id": "margarita", "quantity": 2},
                {"id": "coca_cola", "quantity": 1},
            ],
            "unavailable": [{"text": "hamburger", "quantity": 2}],
            "suggestions": [],
        }
        assert len(fake.calls) == 1


class TestRecommendation:
    def test_vegetarian_question_returns_bare_ids_no_items(self, client):
        recommendation = output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["vegetariana", "quattro_formaggi"],
        )
        set_gemini(client, FakeGeminiClient([recommendation]))
        response = post_order(client, {"text": "imate li nešto bez mesa za nas dvoje?"})
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["unavailable"] == []
        assert body["suggestions"] == ["vegetariana", "quattro_formaggi"]

    def test_suggestions_deduplicated(self, client):
        # Validation feeds duplicates back once; model then returns unique ids.
        dupes = output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["vegetariana", "vegetariana"],
        )
        fixed = output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["vegetariana"],
        )
        set_gemini(client, FakeGeminiClient([dupes, fixed]))
        response = post_order(client, {"text": "imate li nešto bez mesa?"})
        assert response.status_code == 200
        assert response.json()["suggestions"] == ["vegetariana"]

    def test_unknown_suggestion_id_retried_once_then_502(self, client):
        bad = output(intent="recommendation", items=[], unavailable=[], suggestions=["hamburger"])
        still_bad = output(
            intent="recommendation", items=[], unavailable=[], suggestions=["pizza_hawaii"]
        )
        fake = set_gemini(client, FakeGeminiClient([bad, still_bad]))
        response = post_order(client, {"text": "imate li nešto bez mesa?"})
        assert response.status_code == 502
        assert len(fake.calls) == 2
        assert "hamburger" in fake.calls[1]  # validation error fed back to the model


class TestInputValidation:
    def test_empty_text_rejected_without_model_call(self, client):
        fake = set_gemini(client, FakeGeminiClient([]))
        response = post_order(client, {"text": ""})
        assert response.status_code == 422
        assert fake.calls == []

    def test_whitespace_only_text_rejected_without_model_call(self, client):
        fake = set_gemini(client, FakeGeminiClient([]))
        response = post_order(client, {"text": "   "})
        assert response.status_code == 422
        assert fake.calls == []

    def test_missing_text_rejected(self, client):
        assert post_order(client, {}).status_code == 422

    def test_null_text_rejected(self, client):
        assert post_order(client, {"text": None}).status_code == 422

    def test_too_long_text_rejected(self, client):
        response = post_order(client, {"text": "a" * 1001})
        assert response.status_code == 422

    def test_numeric_text_rejected_without_coercion(self, client):
        # Pydantic must not coerce 123 into "123" and pass it to the model.
        fake = set_gemini(client, FakeGeminiClient([]))
        response = post_order(client, {"text": 123})
        assert response.status_code == 422
        assert fake.calls == []


class TestNoOrderInput:
    def test_gibberish_returns_empty_result(self, client):
        # "a" contains no order; prompt rule 6 answers with an empty result.
        set_gemini(client, FakeGeminiClient([output(items=[], unavailable=[])]))
        response = post_order(client, {"text": "a"})
        assert response.status_code == 200
        assert response.json() == {"items": [], "unavailable": [], "suggestions": []}


class TestGeminiFailures:
    def test_sdk_exception_returns_502(self, client):
        # The real client wraps any SDK failure in GeminiError; simulate that.
        set_gemini(client, FakeGeminiClient([GeminiError("boom")]))
        response = post_order(client, {"text": "jednu margaritu"})
        assert response.status_code == 502

    def test_invalid_id_retried_once_then_502(self, client):
        bad = output(items=[{"id": "hamburger", "quantity": 2}])
        still_bad = output(items=[{"id": "pizza_hawaii", "quantity": 2}])
        fake = set_gemini(client, FakeGeminiClient([bad, still_bad]))
        response = post_order(client, {"text": "dva hamburgera"})
        assert response.status_code == 502
        assert len(fake.calls) == 2

    def test_invalid_id_retried_then_success(self, client):
        bad = output(items=[{"id": "hamburger", "quantity": 2}])
        good = output(
            items=[{"id": "margarita", "quantity": 2}],
            unavailable=[{"text": "hamburger", "quantity": 2}],
        )
        fake = set_gemini(client, FakeGeminiClient([bad, good]))
        response = post_order(client, {"text": "dva hamburgera i dvije margarite"})
        assert response.status_code == 200
        assert len(fake.calls) == 2
        assert "hamburger" in fake.calls[1]  # validation error fed back to the model

    def test_malformed_gemini_output_returns_502(self, client):
        # parse_order raising GeminiError simulates schema-mismatch output.
        set_gemini(client, FakeGeminiClient([GeminiError("parsed is None")]))
        response = post_order(client, {"text": "jednu colu"})
        assert response.status_code == 502


class TestInfrastructure:
    def test_health_endpoint(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_menu_endpoint_returns_menu_items(self, client):
        response = client.get("/menu")
        assert response.status_code == 200
        menu = response.json()
        assert [item["id"] for item in menu] == [
            "margarita",
            "capricciosa",
            "diavola",
            "vegetariana",
            "quattro_formaggi",
            "cezar_salata",
            "mijesana_salata",
            "coca_cola",
            "mineralna_voda",
            "pivo",
        ]
        assert menu[0]["naziv"] == "Pizza Margarita"
        assert menu[0]["cijena_eur"] == 9.0
        assert menu[0]["bez_mesa"] is True

    def test_missing_key_returns_503(self, client):
        # Lifespan sets gemini_client to None when no key; simulate that.
        client.app.state.gemini_client = None
        response = post_order(client, {"text": "jednu margaritu"})
        assert response.status_code == 503


class TestRealGeminiClient:
    """Drives the real GeminiClient over a scripted SDK.

    FakeGeminiClient cannot see bugs inside GeminiClient itself - e.g. the
    regression where parse_order_with_feedback was accidentally nested inside
    _is_transient and every feedback retry raised AttributeError (HTTP 500).
    """

    def test_exposes_feedback_method(self):
        assert hasattr(GeminiClient, "parse_order_with_feedback")

    def test_invalid_first_output_retries_with_real_client(self, monkeypatch, client):
        bad = output(items=[{"id": "hamburger", "quantity": 2}])
        good = output(
            items=[{"id": "margarita", "quantity": 2}],
            unavailable=[{"text": "hamburger", "quantity": 2}],
        )
        sdk = _ScriptedSDK([bad, good])
        monkeypatch.setattr("app.gemini_client.genai.Client", lambda **kwargs: sdk)
        set_gemini(client, GeminiClient(api_key="test-key"))

        response = post_order(client, {"text": "dva hamburgera i dvije margarite"})

        assert response.status_code == 200
        assert len(sdk.calls) == 2
        assert "hamburger" in sdk.calls[1]  # validation errors fed back

    def test_feedback_path_makes_no_transient_retries(self, monkeypatch):
        bad = output(items=[{"id": "hamburger", "quantity": 2}])
        # Three failures: consumed only if the feedback path stacked retries.
        sdk = _ScriptedSDK([bad, _TransientError(), _TransientError(), _TransientError()])
        monkeypatch.setattr("app.gemini_client.genai.Client", lambda **kwargs: sdk)
        monkeypatch.setattr("app.gemini_client.time.sleep", lambda seconds: None)
        real = GeminiClient(api_key="test-key")

        real.parse_order("prompt")
        with pytest.raises(GeminiError):
            real.parse_order_with_feedback("prompt", "previous", ["unknown menu id"])

        assert len(sdk.calls) == 2
