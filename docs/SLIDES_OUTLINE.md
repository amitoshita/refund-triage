# Write-up outline (8 slides), for review before building

Numbers are from the sample: history.csv (248 decided requests after removing 3 duplicate rows, ~11 weeks) and
pending.csv (21). Sources: PLAN.md §1, eval/RESULTS.md, `refunds backtest`, the preview.

---

## 1 · The process today, and after
**Before:** customer submits (web form RF-1xxx / support desk RF-2xxx) → an old auto-rule nobody remembers
(about: under $55, no prior refunds, account 9+ months, no fraud flag) approves 45% → everything else goes to
one queue → 4 reviewers (S. Kwan 45, R. Mizrahi 41, D. Patel 28, J. Alvarez 24 decisions).
**After:** ingest + data checks → note reader (LLM, flags only) → deterministic rules → auto-approve (logged, audited)
or the queue, split into 6 lanes with the reason → decision log → manager edits rules with preview.
*Visual:* two-row flow diagram, before/after.

## 2 · Where it breaks: money, consistency, messy data
- **8 chargebacks = $2,519** (amount + $25 fee). **7 of 8 were human approvals**, each with a warning sign already
  in the notes or the fraud flag (signature on file, packaging sealed, "she said it did turn up", fraud not confirmed).
- **Reviewers disagree on the same policy:** change of mind after 14 days ("no exceptions"): R. Mizrahi approved
  4 of 4; S. Kwan and D. Patel rejected 5 of 5. → *Recommendation: clarify policy #2 with the manager.*
- 15 approvals of damage claims over $50 with no photo ($2,521), against policy #3. 3 wrong rejections overturned
  on appeal (one customer closed their account).
- The old auto-rule approved damage > $50 without photos, and one $49 electronics claim became a chargeback.
- Messy data: amounts like "USD 120.00" and "$1,150.00", DD/MM dates, 11 spellings of the reason, blank fraud flags,
  a duplicate request ID, a fake "system note" in a customer note.
- Reviewer time: 1,119 logged minutes; never-arrived claims take 450 (median 9 min each).
**Takeaway:** history isn't ground truth, and the money leaks in the queue as much as in the auto-rule.

## 3 · The line: what the system handles alone
- Auto-approve only: wrong size / change of mind within 14 days, wrong item, damaged (not electronics, photo if
  > $50), **≤ $75**, no prior refunds, fraud flag "no", clean data, no warning signs in notes.
- Everything else to a person, in a lane: fraud > data > notes > carrier > partial > policy.
- Guardrails above the rules: $500 max for any auto-approval, kill switch.

| Backtest, 248 decided requests | Auto | $ | Went wrong before |
|---|---|---|---|
| Old rule (actual) | 111 | $3,377 | 4 |
| Rules only, no notes check | 111 | $3,606 | 3 |
| **Proposed line (LLM note reader)** | **106 (43%)** | **$3,346** | **0** |
| Same line, keyword fallback | 105 | $3,308 | 0 |

- Pending: 2 of 21 auto-approved (RF-1069 $25, RF-1071 $67); 19 to a person.
- Honest caveat: 0 of 106 still allows up to ~2.8% error (rule of three), and auto-approved history was never
  reviewed. Hence shadow mode first.

## 4 · Reviewer mechanism
*Screenshot:* `02_case_RF-1073_injection.png` (or 03, Spanish "already refunded").
- Work lands in 6 lanes with counts; carrier-incident banner groups the 6 Northfield cases.
- The case card shows **why it wasn't auto-approved** (every reason, with policy number), **warning signs from the
  notes with evidence**, an AI summary labelled "verify", the customer note marked untrusted, data problems with raw
  values, the policy-suggested action, and similar past requests with what happened after.
- Actions: approve full / partial / reject / request info / escalate. Going against the suggestion or approving
  despite warning signs requires a note.
- After: append-only log with rule version and the suggested action → override rates per rule feed the manager.
**Key point:** warning signs on the card target where 7 of 8 chargebacks came from.

## 5 · Manager mechanism
*Screenshot:* `05_policy_stolen_card_preview.png`.
- Three ways to change a rule: quick edits (thresholds, on/off), a form builder, or English → AI draft she confirms.
- Preview before publish, on history and pending:
  - "Raise the limit to $100": +2 auto-approved, 0 went wrong before, 18 reviewer minutes saved.
  - "Anything over $300 comes to us": 0 changes. The $75 cap already covers it.
  - "Stolen-card cases go straight through": strict = history 0, pending RF-2182. **Labelled proxy** (as if the
    fraud team had a structured field): 8 move to auto (+$2,215, 106 minutes saved, 0 went wrong); 2 over $500 stay
    with a person because of the guardrail. RF-1070 ("card reported stolen", not confirmed) stays with a person.
- Publish needs a reason; every version is kept; rollback is previewed too. Locked safety rules can't be switched off.
**Recommendation:** make "fraud team confirmed" a structured field filled by the fraud team.

## 6 · How we'd know if it's wrong: measuring and rolling back
- **Before:** backtest (above), labelled note eval, then **2 weeks of shadow mode** (system decides, people still
  decide). Go-live: 0 auto-approvals that a reviewer rejected for a policy reason; auto share ≥ 30%.
- **After, the few numbers to watch:**

| Metric | Good | Roll back / tighten |
|---|---|---|
| Audit sample error rate (10% of auto-approvals re-checked; 100% in week 1) | < 2% | ≥ 1 clear policy violation a week, or > 3% |
| Chargebacks on auto-approved refunds | ≈ 0 | any → suspend the rule that approved it |
| Auto share of volume | 35–50% | jump of > 15 points (rule or data drift) |
| Reviewer override rate per rule | informative | rule overridden ~100% → candidate to relax |
| Queue age | < 1 business day | backlog |

- Rollback = republish the previous version (one click, previewed) or flip the kill switch.

## 7 · Where AI is used, and where it isn't
| LLM | No LLM |
|---|---|
| Notes → warning flags (any language) | The approve / route decision |
| Manager's English → draft rule (confirmed + previewed) | Amounts, dates, reasons, flags |
| One-line summary for the reviewer | Anything that can approve money |

- **Safety:** strict JSON schema with no "approve" option; LLM can only add flags; notes are untrusted data
  (RF-1073's fake system note → injection flag); any failure → a person reads it; runs without a key.
- **Model:** `claude-haiku-5-5`, **~$0.0002 per note** (~2 cents per 100 requests).
- **Evaluation:**

| | Dev set (41 warning / 27 harmless) | Held-out (12 / 7, labelled before running) |
|---|---|---|
| Keyword fallback | 36/41, 4 false flags | 10/12 (4 with the right flag), 7/7 false flags |
| Haiku 5.5 | **41/41, 0 false flags** | **12/12, 0 false flags** |
| Sonnet 5.5 | 40/41 (missed a chargeback note), ~20x cost | not run |

- **The LLM's value is catching risk, not coverage:** coverage is almost the same (106 vs 105). It catches the 5 dev
  notes the fallback misses, incl. 2 chargebacks, and doesn't send every non-English note to a person.
- Honest caveats: small sets; I wrote the labels; the prompt was tuned on the dev set; one known false flag
  (RF-2007), in the safe direction. Total API spend during development ≈ $0.90.

## 8 · What I deferred, and what's next
- **Deferred:** auth/roles; real notifications for request info / escalate; an audit screen; structured photo and
  fraud-team fields (today read from staff notes); partial-amount suggestions; cross-channel customer history;
  scheduled rule changes.
- **Next:**
  1. Shadow mode for 2 weeks; reviewers label notes as they go → a real eval set.
  2. Make fraud-team confirmation and photo evidence structured fields.
  3. Clarify policy #2 (reviewer disagreement) and the wrong-size assumption with the manager.
  4. Carrier-incident handling (Northfield): hold and auto-recheck instead of refund-then-arrives.
  5. Drop LLM flags whose own evidence negates them (the RF-2007 pattern).
