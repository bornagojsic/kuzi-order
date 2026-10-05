# kuzi-order

FastAPI service that takes a Croatian order in natural language ("dvije
margarite i jednu colu"), maps it onto `jelovnik.json` using a free Gemini
model, and returns JSON with menu ids and quantities. Items not on the menu
come back separately under `unavailable` — never dropped or replaced.

## Run

```bash
uv sync
cp .env.example .env   # put your key in it (free: https://aistudio.google.com/apikey)
uv run uvicorn app.main:app --reload
```

The key is read once at startup from the environment (or `.env`, which is
gitignored). The model defaults to `gemini-3.5-flash-lite` and can be changed
via `GEMINI_MODEL`.

## API

`POST /order` with `{"text": "dva hamburgera, dvije margarite i jednu colu"}`:

```json
{
  "items": [
    {"id": "margarita", "quantity": 2},
    {"id": "coca_cola", "quantity": 1}
  ],
  "unavailable": [{"text": "hamburger", "quantity": 2}],
  "suggestions": []
}
```

One extension to the suggested format: `suggestions`. When the customer asks a
question instead of ordering (e.g. "imate li nešto bez mesa za nas dvoje?"),
`items` stays empty and `suggestions` lists the id of every matching menu item
(bare ids, no quantities, in menu order). For a "bez mesa" question drinks are
excluded unless the question is about drinks, and the number of people
mentioned never changes the suggestions:

```json
{"items": [], "unavailable": [], "suggestions": ["margarita", "vegetariana", "quattro_formaggi", "mijesana_salata"]}
```

Self-corrections ("tri margarite i
colu, ma ne, ipak dvije margarite") resolve to the final intent. A message
with no order at all ("a") returns empty lists.

Other endpoints: `/app`
serves a small web UI for typing orders; `/docs` has the interactive schema.

Errors: 422 bad input (missing, null, non-string, empty, whitespace-only or
too long text), 502 Gemini failed or its
output failed validation after one retry, 503 key not configured. `GET /health`
shows status.

## Tests

```bash
uv run pytest                        # mocked, no network
uv run pytest -m integration         # real Gemini, skipped without a key

uv run pytest -m integration --slow  # real Gemini, runs at 12 RPM
```

## What could be better, and how to check it works

The current implementation covers the main parsing, validation, retry, and error-handling requirements, while further improvements would mostly depend on the expected production usage. A natural next step would be to evaluate the parser on a larger and more varied set of Croatian utterances and measure exact-match accuracy for items, unavailable, and suggestions; tests/test_integration.py already provides a small real-model evaluation set. Depending on business requirements, this could then be extended with stricter latency targets, additional fallback behavior, or domain-specific handling based on the kinds of failures seen in real usage.
