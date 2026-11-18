# Speaker notes for `docs/slides.pdf`

Source: `docs/slides/slides.html` (rebuild with `python docs/slides/build_pdf.py`). Every number on the slides comes
from the code: `refunds backtest`, `refunds eval-notes [--heldout]`, and the Policy manager preview (LLM note reader).

## 1 · Today a refund passes through many hands
- Customers submit through two channels: the web form (RF-1xxx) and the support desk (RF-2xxx), where an agent writes the support note.
- The old auto-rule is approximately: under $55, no refunds in the last 12 months, account 9+ months old, fraud flag "no". It approved 111 of 248 (45%).
- Reviewer decisions: S. Kwan 45, R. Mizrahi 40, D. Patel 28, J. Alvarez 24. Never-arrived claims take the most time (450 of 1,119 minutes, median 9 minutes each).
- After the change, each lane points at its owner: the fraud lane goes to the fraud team (policy #5), the carrier lane needs carrier proof of delivery (policy #4).

## 2 · Most money is lost in the queue
- 8 chargebacks cost $2,519 in total (order amount + $25 fee each). The one auto-approved case is RF-2074: a $49 damaged electronics item, approved by the old rule.
- Warning signs in the 7 reviewer-approved chargebacks, all in the notes before the decision: "signature on file", "outer packaging still sealed", "she said it did turn up", plus fraud flags that were never confirmed.
- Reviewer inconsistency: late change of mind ("no exceptions" per policy #2). R. Mizrahi approved 4 of 4; S. Kwan and D. Patel rejected 5 of 5. Recommendation: clarify policy #2 with the manager.
- 15 approvals of damage claims over $50 with no photo ($2,521): 3 by the old rule, 12 by reviewers. Separately, 3 wrong rejections were overturned on appeal, and one of those customers closed their account.

## 3 · The line
- Rules without the note check would auto-approve 3 cases that reviewers correctly rejected (RF-1006, RF-1021, RF-2059). The note reader catches them.
- The old rule's 4 bad approvals: RF-2037, RF-2046, RF-2121 (damage over $50 with no photo) and RF-2074 (chargeback). Together $205.
- Keyword scan alone (no API key): 105 auto, $3,308, 0 went wrong. The LLM's value is catching risk, not coverage.
- Time-to-refund: measured from the request date (date only) to `decided_at`. Human-reviewed: median 40 hours (≈1.7 days). The old rule's batch: median 15 hours. Of the requests the new line auto-approves, 24 went to reviewers before (≈2 a week, median wait 36 hours).
- Money: the old rule made 4 wrong approvals: 1 chargeback ($74: RF-2074, $49 + $25 fee) and 3 refunds against policy ($156: RF-2037 $52, RF-2046 $53, RF-2121 $51.26, damage over $50 paid with no photo, policy #3). Only the chargeback is a known loss; the 3 no-photo refunds broke policy but may have been genuine claims. Rules without the note check: RF-1006 $32, RF-1021 $58, RF-2059 $72 = $162 (all correctly rejected by reviewers).
- Reviewer hours: 106 auto in 11.3 weeks ≈ 9.4 a week × 8.2 min average review ≈ 1.3 hours a week at the sample's volume (22 a week), against reviewing everything. The brief says "a few hundred refund requests a week" and the files are a sample: at ~300 a week, 43% ≈ 128 auto-approvals × 8.2 min ≈ 17 hours a week. Against today's rule the workload is about flat: 24 requests leave the queue (55 logged minutes); 29 the old rule approved now go to a person (no logged time; ≈145 minutes at the 5-minute median). Net ≈ +8 reviewer minutes a week, in exchange for the 4 bad approvals. The 300/week figure is a linear extrapolation of the 43% share.
- Why $75: the preview for $100 adds RF-2140 ($82) and RF-2165 ($90.56). Neither went wrong, but 2 cases in 11 weeks is too small to justify the extra risk.
- Rule of three: 0 errors in 106 means the error rate is below ≈3/106 ≈ 2.8% with 95% confidence.

## 4 · Reviewer queue
- Lanes are in fixed precedence: fraud > data > notes > carrier > partial > policy. The order of rules in the file can't change routing.
- The card shows: the reason in the policy's words with the policy number; warning signs with evidence labelled by source (keyword scan or LLM; both always run); an AI summary labelled "verify"; the customer note marked untrusted; data problems with raw values; the policy-suggested action; similar past requests with what happened next.
- Carrier-incident banner: 6 open cases mention the Northfield depot, written 6 different ways (including Spanish).
- Actions: approve full / partial / reject / request info / escalate. A note is required when going against the suggestion or approving despite warning signs.

## 5 · Policy manager
- English → draft: the LLM can only produce a rule in the fixed schema. It's shown back as a sentence and must be previewed before publishing. Without an API key, the form builder and quick edits still work.
- Stolen-card proxy: RF-1023, RF-1037, RF-1043, RF-1052, RF-2129, RF-2131, RF-2138, RF-2146 move to auto; 106 reviewer minutes saved (≈9 a week). RF-1030 ($520) and RF-2019 ($610) stay with a person because of the $500 guardrail. RF-2007 stays because of a note warning sign. RF-1070 ("card reported stolen", not confirmed) stays with a person.
- Recommendation: make "fraud team confirmed" a structured field filled by the fraud team.

## 6 · Measuring success
- Shadow mode: 2 weeks, with the system's decision logged next to the human's.
- The audit sample is drawn from auto-approvals: 100% in week 1, 10% after that.

## 7 · AI
- Cost: dev set $0.0138 for 67 requests with Haiku 5.5 ≈ $0.00021 per request with notes. 17% of requests have no notes and skip the call, so the average is ≈ $0.00017. At ~300 requests a week: ≈ $0.05 a week, ≈ $3 a year. Sonnet 5.5: $0.277 for the same set.
- Prompt history: v1 over-flagged reason_mismatch; v2's fraud_suspected blocked genuine stolen-card reports; v4 removed every example phrase that overlapped the eval. Details are in `AI_NOTES.md` and `eval/RESULTS.md`.
- The "unreadable" fallback without an LLM: 20 customer notes (long, non-English or containing digits) go to a person.

## 8 · Deferred and next
- Also next: drop LLM flags whose own evidence negates them (the RF-2007 pattern).
