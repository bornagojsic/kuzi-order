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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

TRANSIENT_RETRIES = 2  # extra attempts for overloaded/unavailable model
TRANSIENT_BACKOFF_SECONDS = 2.0


class GeminiError(Exception):
    """Raised when Gemini fails, returns something unusable, or the key is missing."""


class GeminiClient:
    """Sends the order text + prompt to Gemini and returns validated structured output."""

    def __init__(self, api_key: str | None = None) -> None:
        key = api_key if api_key is not None else GEMINI_API_KEY
        if not key:
            raise GeminiError("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=key)

    def parse_order(self, prompt: str) -> GeminiOutput:
        """Call Gemini with a structured-output schema and return the parsed result.

        Raises GeminiError on any SDK failure or on output that does not match
        the schema (parsed == None).
        """
        try:
            response = self._generate_with_retry(prompt)
        except Exception as exc:
            raise GeminiError(f"Gemini call failed: {exc}") from exc

        if response.parsed is None:
            raise GeminiError("Gemini returned output that does not match the schema")
        return response.parsed

    def _generate_with_retry(self, prompt: str):
        """Call the model, retrying a couple of times on transient overload errors.

        Anything else (auth, bad request, not found) fails immediately.
        """
        last_exc: Exception | None = None
        for attempt in range(TRANSIENT_RETRIES + 1):
            try:
                return self._client.models.generate_content(
                    model=MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_schema=GeminiOutput,
                        response_mime_type="application/json",
                        temperature=0,
                    ),
                )
            except Exception as exc:
                if _is_transient(exc) and attempt < TRANSIENT_RETRIES:
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

    def parse_order_with_feedback(
        self, prompt: str, previous: str, errors: list[str]
    ) -> GeminiOutput:
        """Retry a failed attempt, feeding the validation errors back to the model."""
        feedback = (
            f"{prompt}\n\nYour previous answer was invalid:\n{previous}\n"
            f"Problems to fix:\n- " + "\n- ".join(errors) + "\nAnswer again, correctly."
        )
        return self.parse_order(feedback)
