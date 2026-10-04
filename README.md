# kuzi-order

FastAPI service that takes a customer's order in natural Croatian
("dva hamburgera, dvije margarite i jednu colu"), uses a free Gemini model to
map it onto the restaurant menu, and returns ordered menu items and
quantities. Anything the customer asks for that is not on the menu is
returned separately — never silently dropped or replaced by a similar item.

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (or plain pip)
- A Gemini API key ([free tier](https://aistudio.google.com/apikey)), from the `GEMINI_API_KEY` environment variable

## Setup & run

```bash
uv sync                     # install dependencies (pip: pip install -e .)
cp .env.example .env        # then put your key in .env (gitignored)
uv run uvicorn app.main:app --reload
```

The `GEMINI_API_KEY` is read from the environment; if a `.env` file exists in
the project root it is loaded automatically (real environment variables always
take precedence). The key is never committed — `.env` is gitignored.

The model defaults to `gemini-3.5-flash-lite` and can be overridden with
`GEMINI_MODEL` (e.g. in `.env`) without code changes.

The menu is loaded from `jelovnik.json` in the project root at startup; the
service fails to start if the file is missing.

## API

### `POST /order`

Request:

```json
{"text": "dva hamburgera, dvije margarite i jednu colu"}
```

Response:

```json
{
  "items": [
    {"id": "margarita", "quantity": 2},
    {"id": "coca_cola", "quantity": 1}
  ],
  "unavailable": [
    {"text": "hamburger", "quantity": 2}
  ],
  "suggestions": []
}
```

- `items` — menu items the customer ordered, by exact menu `id`.
- `unavailable` — requested things not on the menu, with the customer's own
  wording and quantity.
- `suggestions` — **optional extension** (documented here per the task): only
  non-empty when the customer asked a question instead of ordering. Example:

```json
POST {"text": "imate li nešto bez mesa za nas dvoje?"}
{
  "items": [],
  "unavailable": [],
  "suggestions": [
    {"id": "vegetariana", "quantity": 1},
    {"id": "quattro_formaggi", "quantity": 1}
  ]
}
```

Self-corrections are respected: `"tri margarite i colu, ma ne, ipak dvije
margarite"` yields two margaritas and one cola.

### Errors

| Status | Meaning |
|---|---|
| 422 | Missing/empty/too long (>1000 chars) text, or non-string input |
| 502 | Gemini failed, returned malformed output, or could not be validated after one retry |
| 503 | `GEMINI_API_KEY` not configured |

`GET /health` returns basic status.

### Model output validation

Gemini is called with a Pydantic `response_schema` (structured output), so it
must return JSON of the expected shape. On top of that the service
validates, deterministically and in its own code:

- every item/suggestion `id` must exist in the menu — the model can never
  invent IDs; unknown IDs trigger one retry with feedback, then a 502;
- quantities must be integers ≥ 1 (and ≤ 100);
- an `order` intent with completely empty content, or a `recommendation`
  intent that also contains items, is rejected.

## Tests

```bash
uv run pytest                    # unit + API tests (Gemini fully mocked)
uv run pytest -m integration    # optional real-Gemini tests, needs GEMINI_API_KEY
uv run pytest -m integration --slow  # same, but pauses 30s between API test cases
uv run ruff check . && uv run ruff format --check .
```

## How to evaluate whether it works well

- **Golden test set**: ~30–50 real Croatian order utterances (typos, number
  words, self-corrections, questions) with expected `items`/`unavailable`
  labels; measure per-field exact-match accuracy.
- **Zero-tolerance metric**: any invented menu ID or silently dropped
  unavailable item counts as a hard failure, regardless of overall accuracy.
- **Unit determinism**: the validation layer is pure and fully covered, so
  regressions in the "never invent / never drop" guarantees are caught
  without any model calls.
- **Failure behaviour**: fault injection (SDK exceptions, malformed JSON)
  verifies the API degrades to clean 502s instead of leaking internals.

## Possible improvements

- Persist an evaluation set with expected outputs and run it as a periodic
  CI job (mark it like the integration tests).
- Session/state so a follow-up message ("a dodaj još jednu colu") can amend
  an existing order.
- Stream/queue orders, add idempotency keys, and rate limiting for production.
- Log anonymised failures to build a prompt-improvement feedback loop.
- i18n: menu names and rules are Croatian-specific today; a locale parameter
  would generalise the prompt.
