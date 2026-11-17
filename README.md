# Refund triage

Work in progress. See PLAN.md for the approved plan.

## Assumptions
- **Wrong size follows the change-of-mind return window (14 days).** Policy note #2 names only change of mind; we treat wrong size the same. Editable as the `return_window` rule.
- **Late deliveries always go to a person** (policy #6: partials are the reviewer's call).
- **Blank fraud flag = unknown**, routed to the fraud team, never treated as "no".
- **Slashed dates are DD/MM/YYYY**, inferred from their position among ISO-dated rows in history.csv.
- **"Fraud team confirmed stolen"** is read only from the support agent's note (trusted, internal), never from the customer's note or the LLM. It should become a structured field filled by the fraud team.
