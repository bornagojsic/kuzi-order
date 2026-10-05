"""Thin wrapper around the Google Gemini SDK - the only boundary to the model.

Everything else in the app depends on this class, so tests can mock it instead
of making real API calls.
"""

import os
import time

from dotenv import load_dotenv
from google import genai
from google.genai import types

from app.schemas import GeminiOutput

# Load .env from the project root (if present) without overriding real env vars.
load_dotenv()

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

TRANSIENT_RETRIES = 2  # extra attempts for overloaded/unavailable model
TRANSIENT_BACKOFF_SECONDS = 2.0


class GeminiError(Exception):
    """Raised when Gemini fails, returns something unusable, or the key is missing."""


class GeminiClient:
    """Sends the order text + prompt to Gemini and returns validated structured output."""

    def __init__(self, api_key: str | None = None) -> None:
        # Read the key at construction time, not at import time, so a key that
        # appears in the environment after this module was imported is picked up.
        key = api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise GeminiError("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=key)

    def parse_order(self, prompt: str, retries: int = TRANSIENT_RETRIES) -> GeminiOutput:
        """Call Gemini with a structured-output schema and return the parsed result.

        The JSON text is parsed against the schema here rather than through the
        SDK's automatic function calling, which is deprecated for generate_content.

        Raises GeminiError on any SDK failure or on output that does not match
        the schema. `retries` bounds the extra attempts made for transient
        (overloaded/unavailable) failures.
        """
        try:
            response = self._generate_with_retry(prompt, retries)
        except Exception as exc:
            raise GeminiError(f"Gemini call failed: {exc}") from exc

        try:
            return GeminiOutput.model_validate_json(response.text)
        except Exception as exc:
            raise GeminiError("Gemini returned output that does not match the schema") from exc

    def parse_order_with_feedback(
        self, prompt: str, previous: str, errors: list[str]
    ) -> GeminiOutput:
        """Retry invalid model output once with validation feedback.

        The feedback call does not perform transient retries, which prevents a
        semantic correction attempt from multiplying the number of model calls.
        """
        feedback = (
            f"{prompt}\n\nYour previous answer was invalid:\n{previous}\n"
            f"Problems to fix:\n- " + "\n- ".join(errors) + "\nAnswer again, correctly."
        )
        return self.parse_order(feedback, retries=0)

    def _generate_with_retry(self, prompt: str, retries: int):
        """Call the model, retrying on transient overload errors.

        Anything else (auth, bad request, not found) fails immediately.
        """
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                return self._client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_schema=GeminiOutput,
                        response_mime_type="application/json",
                        temperature=0,
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )
            except Exception as exc:
                if _is_transient(exc) and attempt < retries:
                    last_exc = exc
                    time.sleep(TRANSIENT_BACKOFF_SECONDS)
                    continue
                raise
        raise last_exc  # unreachable; keeps type checkers happy


def _is_transient(exc: Exception) -> bool:
    """True for overloaded/unavailable model responses worth retrying."""
    code = getattr(exc, "code", None)
    if code in (429, 500, 503):
        return True
    return "UNAVAILABLE" in str(exc) or "high demand" in str(exc)
