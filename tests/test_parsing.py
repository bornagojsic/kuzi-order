"""Unit tests for output validation and response mapping - no network, no mocks."""

from app.parsing import to_response, validate_output
from app.schemas import GeminiOrder, GeminiOutput

MENU_IDS = {"margarita", "capricciosa", "coca_cola", "vegetariana"}


def valid_output(**overrides) -> dict:
    order = GeminiOrder(
        intent="order",
        items=[{"id": "margarita", "quantity": 2}],
        unavailable=[{"text": "hamburger", "quantity": 2}],
        suggestions=[],
    )
    parsed = GeminiOutput(order=order).model_dump()
    parsed["order"].update(overrides)
    return parsed


class TestValidateOutput:
    def test_accepts_valid_output(self):
        assert validate_output(valid_output(), MENU_IDS) == []

    def test_rejects_unknown_menu_id_in_items(self):
        raw = valid_output(items=[{"id": "hamburger", "quantity": 2}])
        errors = validate_output(raw, MENU_IDS)
        assert any("hamburger" in e for e in errors)

    def test_rejects_zero_quantity(self):
        # Schema-level check: quantity >= 1 must fail schema validation.
        raw = valid_output()
        raw["order"]["items"] = [{"id": "margarita", "quantity": 0}]
        assert validate_output(raw, MENU_IDS) != []

    def test_accepts_empty_order_for_gibberish(self):
        # "a" contains no order; the prompt tells the model to answer with an
        # empty result, which validation accepts as an honest response.
        raw = valid_output(items=[], unavailable=[])
        assert validate_output(raw, MENU_IDS) == []

    def test_rejects_items_in_recommendation_intent(self):
        raw = valid_output(intent="recommendation")
        errors = validate_output(raw, MENU_IDS)
        assert any("recommendation" in e for e in errors)

    def test_accepts_recommendation_with_suggestions(self):
        raw = valid_output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["vegetariana"],
        )
        assert validate_output(raw, MENU_IDS) == []

    def test_rejects_unknown_id_in_suggestions(self):
        raw = valid_output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["hamburger"],
        )
        errors = validate_output(raw, MENU_IDS)
        assert any("suggestions" in e for e in errors)

    def test_rejects_completely_malformed_output(self):
        assert validate_output({"foo": "bar"}, MENU_IDS) != []

    def test_rejects_unreasonable_quantity(self):
        raw = valid_output(items=[{"id": "margarita", "quantity": 1000}])
        assert validate_output(raw, MENU_IDS) != []

    def test_rejects_duplicate_ids_in_items(self):
        raw = valid_output(
            items=[{"id": "margarita", "quantity": 1}, {"id": "margarita", "quantity": 2}]
        )
        errors = validate_output(raw, MENU_IDS)
        assert any("duplicate" in e.lower() for e in errors)

    def test_rejects_duplicate_ids_in_suggestions(self):
        raw = valid_output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["vegetariana", "margarita", "vegetariana"],
        )
        errors = validate_output(raw, MENU_IDS)
        assert any("duplicate" in e.lower() and "suggestions" in e for e in errors)


class TestToResponse:
    def test_converts_valid_output(self):
        parsed = GeminiOutput.model_validate(valid_output())
        result = to_response(parsed)
        assert result["items"] == [{"id": "margarita", "quantity": 2}]
        assert result["unavailable"] == [{"text": "hamburger", "quantity": 2}]
        assert result["suggestions"] == []

    def test_suggestions_are_bare_ids(self):
        raw = valid_output(
            intent="recommendation",
            items=[],
            unavailable=[],
            suggestions=["vegetariana", "margarita"],
        )
        parsed = GeminiOutput.model_validate(raw)
        assert to_response(parsed)["suggestions"] == ["vegetariana", "margarita"]

    def test_intent_is_required(self):
        raw = valid_output()
        del raw["order"]["intent"]
        assert validate_output(raw, MENU_IDS) != []

    def test_list_fields_have_defaults(self):
        # items/unavailable/suggestions may be absent; validation fills them
        # with empty lists and only flags a fully empty 'order' intent.
        raw = valid_output()
        del raw["order"]["suggestions"]
        assert validate_output(raw, MENU_IDS) == []
