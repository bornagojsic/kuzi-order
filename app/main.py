"""FastAPI application for kuzi-order: POST /order maps natural-language
Croatian order text to menu items via Gemini."""

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from app.gemini_client import GeminiClient, GeminiError
from app.parsing import build_prompt, to_response, validate_output
from app.schemas import OrderRequest

MENU_PATH = Path(__file__).resolve().parent.parent / "jelovnik.json"
INDEX_PATH = Path(__file__).resolve().parent / "static" / "index.html"


def load_menu() -> list[dict]:
    if not MENU_PATH.exists():
        raise RuntimeError(f"Menu file not found: {MENU_PATH}")
    return json.loads(MENU_PATH.read_text(encoding="utf-8"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.menu = load_menu()
    try:
        app.state.gemini_client = GeminiClient()
    except GeminiError:
        app.state.gemini_client = None
    yield


app = FastAPI(title="kuzi-order", lifespan=lifespan)


# Sync endpoint on purpose: the Gemini call blocks (retries with backoff), so
# FastAPI runs it in the threadpool instead of stalling the event loop.
@app.post("/order")
def create_order(request: OrderRequest, fastapi_request: Request) -> dict:
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Order text is empty")

    client: GeminiClient | None = fastapi_request.app.state.gemini_client
    if client is None:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not configured")

    menu = fastapi_request.app.state.menu
    menu_ids = {item["id"] for item in menu}
    prompt = build_prompt(text, menu)

    try:
        parsed = client.parse_order(prompt)
        errors = validate_output(parsed.model_dump(), menu_ids)
        if errors:
            # One retry with validation feedback; still invalid -> give up (502).
            parsed = client.parse_order_with_feedback(prompt, parsed.model_dump_json(), errors)
            errors = validate_output(parsed.model_dump(), menu_ids)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=f"Order could not be processed: {exc}") from exc

    if errors:
        raise HTTPException(
            status_code=502, detail="Order could not be processed: invalid model output"
        )

    result = to_response(parsed)
    if parsed.order.intent == "recommendation":
        # A question, not an order: never create items from a recommendation.
        result["items"] = []
        result["unavailable"] = []
    else:
        result["suggestions"] = []
    return result


@app.get("/app", include_in_schema=False)
async def order_page() -> FileResponse:
    return FileResponse(INDEX_PATH)


@app.get("/menu")
async def menu(fastapi_request: Request) -> list[dict]:
    return fastapi_request.app.state.menu


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "gemini_configured": app.state.gemini_client is not None}
