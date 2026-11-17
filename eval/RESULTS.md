# Note-reader evaluation results (prompt v4, 2026-11-17)

Recall = warning-sign notes where at least one flag was raised (a miss can lead to a wrong approval).
False flags = harmless notes that got a flag (cost: about 2 minutes of review each).

## Labelled set (41 warning, 27 harmless; real notes from history and pending)
| Reader | Recall | Right flag | False flags | Cost |
|---|---|---|---|---|
| Keyword fallback | 36/41 (88%) | 35/41 | 4/27 | $0 |
| claude-haiku-5-5 | 41/41 (100%) | 41/41 | 0/27 | $0.0138 for 67 notes |
| claude-sonnet-5-5 (prompt v3) | 40/41 (98%), missed RF-2111 | 40/41 | 0/27 | $0.2770 for 67 notes |

Fallback misses: RF-2111, RF-1065 (both chargebacks), RF-1047, RF-2082, RF-2020.
Caveats: I wrote the labels, and I tuned the prompt on this set (v1 → v4; v4 removed every example phrase
that appeared in the data). Treat it as a development set.

## Held-out set (12 warning, 7 harmless; written and labelled before running, never seen by the prompt)
| Reader | Recall | Right flag | False flags | Cost |
|---|---|---|---|---|
| Keyword fallback | 10/12 | 4/12 | 7/7 | $0 |
| claude-haiku-5-5 | 12/12 | 12/12 | 0/7 | $0.0040 for 19 notes |

The fallback's held-out recall is mostly the "unreadable" catch-all (non-English, digits, emoji, long), so it
sends almost everything to a person: safe, but not useful. It missed H09 (repeat claim, "fifth claim") and H10
(parcel-forwarding warehouse). Caveats: 19 notes is small, and the held-out notes were written by the same
AI assistant that wrote the prompt, so they are not fully independent. Next step: real notes from production
traffic, labelled by reviewers.

## Model choice
claude-haiku-5-5: passes the recall bar on both sets, about $0.0002 per note (about 2 cents per 100 requests).
Sonnet 5.5 costs about 20 times more and missed a chargeback note.

## Backtest on history (248 decided requests, rules v1)
| | Auto-approved | $ | Would have been wrong to approve |
|---|---|---|---|
| Rules only, no notes check | 111 | $3,606 | 3 (correct rejections) |
| Keyword fallback | 105 | $3,308 | 0 |
| claude-haiku-5-5 | 106 | $3,346 | 0 |

Total API spend on all eval and backtest runs during development: about $0.90.
