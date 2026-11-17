# Refund triage

Work in progress. See PLAN.md for the approved plan.

## Run
```bash
uv sync
uv run refunds run data/pending.csv          # decide a file -> out/decisions.csv (any CSV with the same columns)
uv run streamlit run app/streamlit_app.py    # demo: reviewer queue + policy manager
uv run pytest                                # tests
```
Optional: copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. Without a key, the note reader uses the committed
cache of LLM results (`llm_cache/`); notes not in the cache are flagged "unreadable" and go to a person.
Other commands: `refunds models`, `refunds eval-notes [--heldout]`, `refunds backtest`, `refunds run FILE --no-llm`.

## Assumptions
- **Wrong size follows the change-of-mind return window (14 days).** Policy note #2 names only change of mind; we treat wrong size the same. Editable as the `return_window` rule.
- **Late deliveries always go to a person** (policy #6: partials are the reviewer's call).
- **Blank fraud flag = unknown**, routed to the fraud team, never treated as "no".
- **Slashed dates are DD/MM/YYYY**, inferred from their position among ISO-dated rows in history.csv.
- **"Fraud team confirmed stolen"** is read only from the support agent's note (trusted, internal), never from the customer's note or the LLM. It should become a structured field filled by the fraud team.
