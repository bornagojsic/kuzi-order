"""Pydantic models for the API boundary and the Gemini structured-output schema."""

from typing import Literal

from pydantic import BaseModel, Field


class OrderRequest(BaseModel):
    """POST /order request body."""

    text: str = Field(
        min_length=1, max_length=1000, description="Customer order in natural language"
    )


class OrderItem(BaseModel):
    """A menu item the customer wants, identified by an existing menu id."""

    id: str = Field(description="Menu item id, e.g. 'margarita'")
    quantity: int = Field(ge=1, description="How many the customer wants")


class UnavailableItem(BaseModel):
    """Something the customer asked for that is not on the menu.

    Identified by the customer's own words because no valid menu id exists.
    """

    text: str = Field(
        min_length=1, description="The item as the customer said it, e.g. 'hamburger'"
    )
    quantity: int = Field(ge=1)


class OrderResponse(BaseModel):
    """POST /order response.

    `suggestions` is non-empty only when the customer asked a question instead
    of ordering (e.g. vegetarian recommendations); then `items` is empty.
    Suggestions carry bare menu ids, no quantities.
    """

    items: list[OrderItem] = Field(default_factory=list)
    unavailable: list[UnavailableItem] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class GeminiOrder(BaseModel):
    """Structured output Gemini must produce for a single customer message."""

    intent: Literal["order", "recommendation"] = Field(
        description=(
            "'order' if the customer is ordering food/drinks, "
            "'recommendation' if they are asking a question or asking for suggestions"
        )
    )
    items: list[OrderItem] = Field(default_factory=list, description="Ordered menu items")
    unavailable: list[UnavailableItem] = Field(
        default_factory=list, description="Requested items that are NOT on the menu"
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description=(
            "Only for intent='recommendation': ids of matching menu items, "
            "each at most once, no quantities"
        ),
    )


class GeminiOutput(BaseModel):
    """Top-level structured output returned by Gemini."""

    order: GeminiOrder
