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
`items` stays empty and matching menu items are listed there. Self-corrections
("tri margarite i colu, ma ne, ipak dvije margarite") resolve to the final
intent.

Errors: 422 bad input (missing/empty/too long), 502 Gemini failed or its
output failed validation after one retry, 503 key not configured. `GET /health`
shows status.

## Tests

```bash
uv run pytest                  # mocked, no network
uv run pytest -m integration   # real Gemini, skipped without a key
```

## What could be better, and how to check it works

Worth adding: sessions, so a follow-up message ("a dodaj još jednu colu") can
amend an order, and a CI job that replays a labelled set of utterances against
the model on every change. To verify the system works well: keep a golden set
of ~30–50 real Croatian utterances (number words, typos, self-corrections,
questions) with expected `items`/`unavailable` and measure per-field exact
match — treating any invented menu id or dropped item as a hard failure, not
just a lower score. The deterministic parts (prompt rules, validation, error
mapping) are unit-tested without any model calls, and fault injection covers
the 502/503 paths.
