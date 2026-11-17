# AI coding tool notes

Running log of things the AI coding assistant (Claude Code) produced that I changed or threw away.
The README quotes one of these.

| Date | What the AI produced | What I changed / why |
|---|---|---|
| 2026-11-17 | Plan defaulted the note-reader model to the most capable model (Opus) "at low effort". | Changed to: model is a config value; compare Haiku vs Sonnet on a labelled note set and pick the cheapest that passes the warning-sign recall bar. Cost should be earned by eval, not assumed. |
| 2026-11-17 | Plan treated LLM output as an input to routing only. | Added: the LLM's warning signs must also appear on the reviewer's card, since 7 of 8 historical chargebacks were human approvals with the warning sign already in the notes. |
| 2026-11-17 | Plan left wrong-size vs change-of-mind window implicit. | Made it an explicit, editable rule (`return_window`) and a documented assumption. |
| 2026-11-17 | First rule schema picked the queue lane from the first block rule in file order. | Changed to a fixed lane precedence (fraud > data > notes > carrier > partial > policy), so reordering rules.yaml can't change routing. Test shuffles the file. |
| 2026-11-17 | Schema had no limits above the rule set: an `eligible` rule with overrides could auto-approve any amount. | Added engineer-owned guardrails in config.yaml (global $500 max, kill switch) that no rule or override can bypass. |
| 2026-11-17 | Reason text hard-coded "$75", which would go stale when the manager edits the cap. | Added a `{limit}` placeholder filled from the rule's own threshold. |
| 2026-11-17 | Told me "Haiku 5.5 doesn't exist" from its training data and wanted to compare Haiku 4.5 instead. | I pushed back; `refunds models` against the live API showed claude-haiku-5-5 is available and claude-haiku-4-5 isn't on this key. Lesson: verify model ids against the API, don't trust the assistant's memory. **(README example)** |
| 2026-11-17 | First note-reader prompt (v1) over-flagged `reason_mismatch` on ordinary change-of-mind notes ("not really my style"), even when its own evidence said the note was consistent. Cost 15 history cases of coverage. | Caught by the backtest; tightened the flag definition (v2). Caveat: two benign phrasings in the prompt also appear in the eval negatives, so the 0 false-flag score is optimistic. |
| 2026-11-17 | Prompt v2 defined `fraud_suspected` to include "cardholder disputes the purchase", so genuine stolen-card reports got a locked warning flag and the manager's stolen-card rule could never fire. | Caught while building the preview; narrowed the flag to fraud by the requester (v3). The fraud flag rule already handles stolen-card reports. |
