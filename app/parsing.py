"""Pure helpers for building the Gemini prompt and validating its output.

No I/O here: both functions are trivially unit-testable without network access.
"""

from app.schemas import GeminiOutput, OrderItem, UnavailableItem

MAX_QUANTITY = 100


def build_prompt(order_text: str, menu: list[dict]) -> str:
    """Build the instruction prompt sent to Gemini together with the menu."""
    menu_lines = [
        f"- {item['id']} | {item['naziv']} | kategorija: {item['kategorija']}"
        f" | bez_mesa: {item['bez_mesa']}"
        for item in menu
    ]
    menu_block = "\n".join(menu_lines)
    return f"""You are an order-taking assistant for a Croatian restaurant.

MENU (id | name | category | meat-free):
{menu_block}

The customer wrote:
"{order_text}"

Interpret the customer's message and produce a structured result. Rules:

1. Map each ordered item to its EXACT id from the MENU above. Never invent ids.
2. Anything the customer asks for that is NOT on the menu must go into
   "unavailable" with the quantity and the item name as the customer said it
   (e.g. "hamburger"). NEVER replace it with a similar menu item and never
   silently drop it.
3. Preserve quantities exactly. Numbers may be written as Croatian words
   ("dva", "dvije", "tri", "jednu"...) - convert them to integers.
4. If the customer corrects themselves ("tri margarite i colu, ma ne, ipak
   dvije margarite"), use only their FINAL intent.
5. If the customer is not ordering but asking a question (e.g. "imate li
   nešto bez mesa za nas dvoje?"), set intent to "recommendation", leave
   "items" empty, and put suitable menu items (e.g. meat-free ones for a
   "bez mesa" question) into "suggestions". The number of people mentioned
   ("za nas dvoje") is not a quantity to order.
6. If the message contains no order at all and no question, return an empty
   result with intent "order" and empty lists."""


def validate_output(raw: dict, menu_ids: set[str]) -> list[str]:
    """Validate a parsed Gemini output against the menu.

    Returns a list of human-readable errors; an empty list means valid.
    """
    try:
        parsed = GeminiOutput.model_validate(raw)
    except Exception as exc:
        return [f"output does not match the expected schema: {exc}"]

    order = parsed.order
    errors: list[str] = []

    for item in order.items:
        if item.id not in menu_ids:
            errors.append(f"unknown menu id '{item.id}' in items")
        if item.quantity > MAX_QUANTITY:
            errors.append(f"unreasonable quantity {item.quantity} for item '{item.id}'")

    for item in order.suggestions:
        if item.id not in menu_ids:
            errors.append(f"unknown menu id '{item.id}' in suggestions")

    for item in order.unavailable:
        if item.quantity > MAX_QUANTITY:
            errors.append(f"unreasonable quantity {item.quantity} for unavailable '{item.text}'")

    if order.intent == "order" and not order.items and not order.unavailable:
        errors.append("intent is 'order' but both items and unavailable are empty")

    if order.intent == "recommendation" and order.items:
        errors.append("intent is 'recommendation' but items is not empty")

    return errors


def to_response(parsed: GeminiOutput) -> dict:
    """Convert a validated GeminiOutput into the API response payload."""
    order = parsed.order
    return {
        "items": [OrderItem(id=i.id, quantity=i.quantity).model_dump() for i in order.items],
        "unavailable": [
            UnavailableItem(text=u.text, quantity=u.quantity).model_dump()
            for u in order.unavailable
        ],
        "suggestions": [
            OrderItem(id=s.id, quantity=s.quantity).model_dump() for s in order.suggestions
        ],
    }
