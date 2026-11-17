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
