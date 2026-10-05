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

Other endpoints: `GET /menu` returns the raw `jelovnik.json` menu; `/app`
serves a small web UI for typing orders and shows the menu beside the order
form; `/docs` has the interactive schema.

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

Worth adding: sessions, so a follow-up message ("a dodaj još jednu colu") can
amend an order, and a CI job that replays a labelled set of utterances against
the model on every change. To verify the system works well: keep a golden set
of ~30–50 real Croatian utterances (number words, typos, self-corrections,
questions) with expected `items`/`unavailable` and measure per-field exact
match — treating any invented menu id or dropped item as a hard failure, not
just a lower score. A starter table already lives in
`tests/test_integration.py` (`UTTERANCE_CASES`) and runs against the real
model with `uv run pytest -m integration`. The deterministic parts (prompt
rules, validation, error mapping) are unit-tested without any model calls, and
fault injection covers the 502/503 paths. Once running, the biggest practical
risk is the silent wrong 200: the model can return plausible but wrong JSON
(a real order parsed as empty, a misaggregated quantity), which no single
request can detect — only replaying a golden set several times and requiring
5/5 exact matches measures it. Second is latency collapse: Gemini calls have
no per-call timeout and concurrency is unbounded, so a slow model can exhaust
the request threadpool and stall the entire service — add a call timeout and
a concurrency limit, then verify with a parallel load probe that p95 stays
bounded. Third, recoverable failures are fatal today: fenced or truncated
JSON and free-tier 429s become hard 502s instead of using the existing
feedback retry and smarter backoff. Finally, none of this is visible in
production — log intent, feedback-retry rate, latency and empty-result rate
per request, and alert on spikes.
