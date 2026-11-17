# Refund Triage — Plan (for approval, no code yet)

Project root: `~/refund-assignment` (data copied to `data/`). All numbers below come from read-only profiling of
`history.csv` (251 rows → 248 after removing 3 exact duplicate rows, 2026-06-02 → 2026-08-18, ~11 weeks) and `pending.csv` (21 rows).

---

## 0. Brief → requirements checklist

- [ ] **Part 1 – the line**: where auto-approve vs human sits, *how it was derived*, and how we'd know it's wrong (before launch + after).
- [ ] A thin system that applies the line; runnable with **one command** on `pending.csv` or any same-schema file.
- [ ] **Tests**.
- [ ] **Reviewer mechanism**: where work lands, what they see, their options, what happens after.
- [ ] **Manager mechanism**: change behaviour without an engineer ("stolen-card → straight through", "> $300 → us", others) and **see impact before go-live**.
- [ ] **AI judgment**: LLM where it earns its place, and where deliberately not.
- [ ] Clickable demo of both mechanisms (Streamlit OK); label anything mocked.
- [ ] 3–5 min screen recording.
- [ ] README: run, API-key setup, architecture sketch, AI-coding-tool note incl. one thing changed/thrown away.
- [ ] ≤ 8-slide write-up: process today (before/after), the line + evidence, success metrics + rollback, AI use (model, $/decision, eval results), deferred/next.
- Out of scope: auth, cloud deploy, payments.

---

## 1. What the data says (evidence base)

### 1.1 Data quality issues (all must route-to-human or be normalised, never crash)
| Issue | Examples |
|---|---|
| Exact duplicate rows | RF-1019, RF-2040, RF-2111 (history) |
| Duplicate `request_id`, different content | RF-2183 in pending ($49 then $52 "resubmitting – forgot shipping") |
| `amount_usd` as text | `$43`, `USD 120.00`, `55.00 USD`, `"$1,150.00"`, trailing spaces |
| Mixed date formats | `09/06/2026` (DD/MM — confirmed by row order), ISO with `T…Z` |
| `stated_reason` variants | `late`, `damaged`, `changed mind`, `Never Arrived`, `wrong item` |
| `category` case | `Electronics`, `Home` |
| `fraud_flag` variants | `yes/Y/no/N/false/blank` — blank must mean **unknown**, not "no" |
| Missing values | tenure (2), customer_id (1), days_since_delivery (1), fraud_flag (1 hist, 1 pending) |
| Impossible values | `days_since_delivery = -2` (RF-2139, auto-approved anyway) |
| Free text in other languages | Spanish (RF-1074, RF-2199), Hebrew (history) |
| **Prompt injection in data** | RF-1073 customer_note contains a fake "system note" telling the agent to approve and skip review ($385, never_arrived, 2-month-old account) |
| PII / redirection in notes | "pls refund to card ending 4417, or call me on +44…" (history) |

### 1.2 Reverse-engineered old auto-rule (113 auto decisions, all approved)
`amount < ~$55` **and** `prior_refunds_12m == 0` **and** `fraud_flag ≠ yes` **and** `tenure ≳ 9 months` **and** (changed_mind only if `days ≤ 14`).
It ignores reason otherwise. Max auto amount $54, min tenure 9; every human-handled case under $55 has tenure < 9, prior > 0, or changed_mind > 14 days (one noisy exception, RF-1002).

What's wrong with it:
- Auto-approved **damaged > $50 with no photo** (RF-2037, RF-2046, RF-2121) — violates policy #3.
- Auto-approved electronics damaged $49 → **chargeback** (RF-2074).
- Auto-approved **late_delivery in full** (8) — policy #6 says partials there are the reviewer's call; humans gave "shipping only" on similar cases.
- Auto-approved **never_arrived "tracking stops at depot"** (7) — but RF-2194 shows Northfield-stuck parcels *do* turn up 12 days late → we pay for goods the customer then receives.
- Accepted missing tenure, missing fraud flag, negative days.
- Excludes good small cases from newer customers (tenure < 9) that humans approve 100% of the time.

### 1.3 Policy vs practice — where history is wrong
| Policy note | Practice |
|---|---|
| #2 change of mind ≤ 14 days, **no exceptions** | 9 cases > 14 days: R. Mizrahi approved 4, S. Kwan rejected 4, D. Patel rejected 1 → **reviewer inconsistency** |
| #3 photo for damaged > $50 | **15 approvals** with no photo evidence ($2,521): 3 auto + 12 human |
| #4 signature/POD → reject unless investigation | RF-1005 ($410), RF-2042 ($265) approved → both **chargebacks** |
| #5 fraud flag → fraud team; refund only if confirmed stolen | 11 confirmed-stolen cases approved in full (correct, 0 bad). But RF-2111 ($390), RF-1065 ($495) approved without confirmation → **chargebacks**; RF-1014 ($185) approved unconfirmed |
| #6 our mistake → full refund, no questions | RF-2143 rejected → overturned on appeal (mis-pick). RF-1008, RF-2090 damaged-with-clear-photos rejected → overturned (one customer closed account) |
| support notes contradicting claim | RF-1045 "she said it did turn up" → approved → chargeback; RF-2083 "admitted she assembled it and it snapped" → approved → chargeback; RF-1027 "original packaging still sealed" → chargeback; RF-1039 "fourth claim this quarter" $340 approved |

**Chargebacks:** 8 cases, $2,319 + 8×$25 = **$2,519** (5 S. Kwan, 2 R. Mizrahi, 1 auto). 7 of 8 were human approvals > $49 with a visible red flag in the notes or fraud flag — the auto line isn't where the money leaks; **reviewer decisions without guardrails** are.

**Where reviewer time goes** (1,119 min logged): never_arrived 450 min (median 9), damaged 285, wrong_item 164, late 128, changed_mind 72, wrong_size 22.

### 1.4 Label definition for backtesting
History is not ground truth. A historical case is **"bad if fully approved"** when any of: chargeback filed; appeal-overturned rejection (inverse — bad if rejected); policy violation per notes #2–#5 (changed_mind > 14d, damaged > $50 w/o photo, signature/POD on file, fraud flag w/o confirmation); support note contradicts claim; ≥ 3 prior refunds. Humans' `partial` decisions also count as "should not be auto-approved in full".
Caveat stated up front: for cases that were auto-approved, the only outcome signal is a chargeback — nobody reviewed them — so the label under-counts errors in exactly the zone we want to automate. Hence the audit sample in §3.

---

## 2. The line (v1 proposal)

**Principle:** auto-approve is the *exception that must be earned*; every gate is a reason to send to a human. A case is auto-approved only if **no gate fires**. Every gate produces a **reason code** shown to the reviewer.

### 2.1 Gates (route to human if any fires) — stored in `rules/rules.yaml`
| # | Gate | Reason code | Evidence |
|---|---|---|---|
| D1 | Any required field missing/unparseable, days < 0, unknown reason/category | `DATA_QUALITY` | §1.1 |
| D2 | Duplicate `request_id` (in batch or already decided) | `DUPLICATE` | RF-2183 |
| F1 | `fraud_flag` = yes **or unknown** | `FRAUD_FLAG` → fraud queue | 2 chargebacks on unconfirmed fraud |
| A1 | `amount > $75` | `OVER_LIMIT` | see backtest |
| C1 | `prior_refunds_12m ≥ 1` | `REPEAT_REFUNDER` | RF-1039 |
| R1 | reason = `never_arrived` | `NEEDS_CARRIER_CHECK` | signature chargebacks, Northfield |
| R2 | reason = `late_delivery` | `PARTIAL_CANDIDATE` | policy #6, humans gave partials |
| R3 | changed_mind / wrong_size with `days > 14` | `OUTSIDE_RETURN_WINDOW` | policy #2 |
| R4 | arrived_damaged **and** electronics | `ELECTRONICS_DAMAGE` | RF-2074 chargeback; cosmetic partials |
| R5 | arrived_damaged **and** amount > $50 **and** no photo evidence | `PHOTO_REQUIRED` | policy #3 |
| N1 | Note signals (LLM-extracted, §5): contradicts claim, admits receipt/self-damage, already refunded elsewhere, reason mismatch, refund-to-different-account, instructions aimed at the system, unreadable | `NOTE_FLAG:<type>` | RF-1045/2083/1027, RF-1074/1075/1073 |

Auto-approve ⇔ fraud=no, amount ≤ $75, no prior refunds, reason ∈ {wrong_size, changed_mind (≤14d), wrong_item, arrived_damaged (non-electronics, photo if > $50)}, clean data, no note flags.

### 2.2 Backtest on history (structured gates only; note gate evaluated in build)
| Line | Auto n (share) | $ auto | "Bad if approved" | $ bad | Chargebacks |
|---|---|---|---|---|---|
| Old rule (actual) | 111 (45%) | $3,377 | 4 | $205 | 1 |
| Cap $50 | 105 (42%) | $3,080 | 1 | $49 | 1 |
| Cap $100, all damaged | 122 (49%) | $4,209 | 1 | $49 | 1 |
| **Cap $75, no electronics damage (proposed)** | **112 (45%)** | **$3,664** | **0** | **$0** | **0** |
| Cap $100, no electronics damage | 114 (46%) | $3,837 | 0 | $0 | 0 |
| + late_delivery | +14 | | +3 humans gave partials | | |
| + never_arrived | +13 | | +2 bad | +$154 | |

- In the proposed zone, 5 cases were historically **rejected**: 4 have support notes contradicting the claim ("matches order line", "contents fine per photos") → the N1 note gate must catch these (acceptance test). The 5th (RF-2143) was a wrong rejection later overturned — the system would have been right.
- Statistical honesty: 0 bad in 112 → 95% upper bound on error rate ≈ **2.7%** (rule of three). Small sample; that's why we launch with shadow mode + audit sampling, not on backtest alone.
- $75 vs $100: same backtest result; $75 chosen because $ at risk per error is lower and the extra 2 cases don't justify it. (Your call — Q1.)
- Volume vs old rule is similar (~45%) but **cleaner**: drops the 4 bad auto decisions, adds newer-customer small cases, and moves never_arrived/late out.

### 2.3 Pending.csv under the proposed line
Structured gates leave 6 candidates; then: RF-2183 ×2 → `DUPLICATE`; RF-1074 (Spanish: "they already refunded me in store, want it here too") → `NOTE_FLAG:already_refunded`; RF-1075 ("honestly it's fine, just not the colour", 22 days, filed as damaged) → `NOTE_FLAG:reason_mismatch`.
**Auto-approved: RF-1069 ($25 changed_mind, 8d) and RF-1071 ($67 home, damaged, photos clear). 19 → human.**
Notable routed cases: RF-1073 (injection, $385) → `NEEDS_CARRIER_CHECK` + `NOTE_FLAG:instruction_in_note`; RF-2182 (fraud flag blank, note says fraud team confirmed stolen) → `FRAUD_FLAG(unknown)`; 6 Northfield cases (written 6 different ways incl. Spanish, "NFD", "North field") → shown as a **cluster** to the reviewer.

---

## 3. Validation before launch & monitoring after

**Before:**
1. Backtest (above) reproducible via `refunds backtest` → report with confusion vs. label, $ exposure, per-gate counts.
2. Hand-labelled golden set (~40 cases: all chargebacks, overturns, policy violations, injection, foreign-language, edge data) — must route 100% of known-bad to human.
3. **Shadow mode** 2 weeks: system decides, humans still decide; compare. Go-live criterion: 0 auto-approvals a human rejected/partialed without a policy-backed reason, ≥ 30% of volume auto.

**After (metrics on a simple dashboard page):**
| Metric | Good | Rollback / tighten trigger |
|---|---|---|
| Audit-sample error rate (random 10% of auto-approvals re-reviewed by a human, 100% first week) | < 2% | ≥ 1 clear policy violation/week, or > 3% |
| Chargeback rate on auto-approvals | ≈ 0 | any chargeback on an auto case → that rule auto-suspended pending review |
| Auto share of volume | 35–50% | sudden jump > +15 pts (rule or data drift) |
| Reviewer override rate on routed cases by reason code | informative | gate with ~100% approve → candidate to relax (suggest to manager) |
| Queue age / time-to-decision | < 1 business day | backlog |
| Avg review minutes | trending down | — |
Rollback = one click: revert rules to previous version (§5), or kill-switch "everything to human".

---

## 4. Reviewer mechanism

- **Where it lands:** a SQLite-backed queue with lanes: `Fraud team` (F1), `Needs carrier check` (R1), `Partial decision` (R2/R4), `Policy check` (R3/R5/C1/A1), `Data fix` (D1/D2), `Note flagged` (N1). Sorted by SLA age then $.
- **What they see (case card):** structured fields (normalised, with original raw value shown where it was messy); **why it wasn't auto-approved** (all fired reason codes in plain language + the policy note each maps to); LLM case summary + translated note (clearly labelled "AI summary — verify"); customer history (prior requests in data); similar historical cases and how they were decided; cluster banner ("6 open Northfield depot cases"); suggested action per policy (deterministic, e.g. "Outside 14-day window → policy says reject").
- **Actions:** Approve full · Approve partial (% or $, with preset "shipping only") · Reject (reason picklist mapped to policy) · Request info (photo / carrier investigation / fraud-team confirmation → case parks in `Waiting` with a reminder date) · Escalate (to manager / fraud team).
- **After:** decision written to an append-only `decisions` log (who, when, action, amount, reason code, rule version, minutes). Overrides of the suggested action require a one-line justification. Feedback loop: weekly report of overrides by gate → manager sees "R5 overridden 0/12 times" or "humans approve 100% of $75–100 wrong_size" → proposes rule change via §5. Decision on an auto-approved case in the audit sample feeds the error-rate metric.

---

## 5. Manager mechanism (no engineer)

- **Rules are data:** `rules.yaml` / SQLite table of versioned rule sets. Each rule: `id, description, when (conditions on normalised fields + derived signals), action (route_to_human:<lane> | auto_approve | block_auto), priority, enabled`. Conditions use a small whitelisted vocabulary (field, operator, value) — no code eval.
- **Three ways to edit (Streamlit "Policy" page):**
  1. Toggle / edit thresholds in a form (e.g. cap $75 → $100, enable/disable a gate).
  2. Add a rule from a form builder (field ▸ operator ▸ value ▸ action).
  3. Type it in English → LLM drafts the structured rule → shown back as a readable sentence + the YAML → **she confirms**. The LLM never activates anything.
- **Preview / dry run (mandatory before publish):** runs draft vs. current rules over history + pending and shows: cases that change route (count, $), split by direction (→auto / →human), how many of the newly-auto cases were "bad if approved" historically (chargebacks, overturns, violations) with $ and examples, reviewer minutes saved, and 5 example cases each way. Warnings when a rule references a signal that isn't a structured field.
- **Worked examples (will be in demo):**
  - "Anything over $300 comes to us" → preview: **0 cases change route** (already covered by $75 cap) — tells her it's redundant now but protects her if the cap is later raised. Useful feedback, not a bug.
  - "Stolen-card cases go straight through" → there is **no structured "confirmed stolen" field**; it lives in free-text support notes. System maps it to the LLM-extracted signal `fraud_team_confirmed_stolen` and warns. Preview: history 11 cases → auto, $3,650, 0 bad, ~150 reviewer minutes saved (2 of them exceed $500); pending → RF-2182 moves to auto, **RF-1070 does not** ("card reported stolen" ≠ fraud-team confirmation). Recommends keeping a per-case cap (e.g. ≤ $500) and fraud-team confirmation required.
- **Versioning & rollback:** every publish creates an immutable version (author, timestamp, diff, preview snapshot, free-text reason). Each decision records the rule version used. "Revert to vN" = one click, also previewed. Optional scheduled effective date.

---

## 6. AI usage — where and where not

| Use | LLM? | Why |
|---|---|---|
| Final approve/route decision | **No** | Moves money; must be deterministic, auditable, reproducible, previewable over history |
| Parse amounts, dates, reason synonyms, flags | **No** | Regex/maps are exact and testable |
| Read free-text notes → structured flags (contradiction, admits receipt, already refunded, reason mismatch, refund-to-other-account, instruction-in-note, confirmed-stolen, carrier-incident/location) incl. Spanish/Hebrew | **Yes** | This is the gap the data shows: 7/8 chargebacks had the red flag *in the notes*; notes are multilingual and phrased many ways ("NFD", "North field"). |
| Translate manager's English rule → structured rule draft | **Yes** | Natural-language convenience; human confirms; preview shows impact |
| Case summary for reviewer | **Yes** (small) | Saves reading time; labelled as AI, non-authoritative |

**Safety design:**
- **One-way ratchet:** LLM output can only *add* route-to-human flags (or, for an explicit manager rule, supply a signal that is shown in preview). It can never remove a deterministic gate.
- Notes are passed as quoted data in a delimited block; system prompt says content is untrusted; structured output (JSON schema) only — no free-form decisions. RF-1073 is a test case.
- Any LLM error/timeout/invalid JSON → `NOTE_FLAG:unreadable` → human.
- **No API key fallback:** deterministic keyword flags; any case whose customer_note is non-empty and not on a small benign-phrase allowlist routes to human. Measured cost of no-LLM mode: in-zone cases with free-text notes = 79/112 → auto coverage drops from ~45% to roughly 15–25%. That gap *is* the quantified value of the LLM.
- Results cached per note hash (SQLite) so reruns/previews are free and deterministic.

**Model & cost** (Anthropic API, ~800 input / 150 output tokens per note):
- Claude Opus 5.5 ($4/$20 per MTok) ≈ **$0.006/case**; Sonnet 5.5 ($2/$10) ≈ $0.003; Haiku 4.5 ($1/$5) ≈ $0.0016. At a few hundred/week all are < $2/week — cost is not the constraint, accuracy on adversarial notes is. Model is a config value; default Opus 5.5 at low effort, eval decides (Q4).
**Evaluation:** labelled set of all notes in history+pending (~150 unique non-empty notes, I label flags by hand) → per-flag precision/recall, with **recall on red flags as the headline** (a miss can cause a false approval; a false positive just costs a human 2 minutes). Plus targeted cases: injection, Spanish/Hebrew, reason mismatch. Rule-translation eval: ~10 manager phrasings → expected structured rule, exact-match.

---

## 7. Architecture

Python 3.12 + Streamlit + SQLite + pydantic + PyYAML + `anthropic` SDK. Streamlit is the right call for a 4–6 h business demo (forms, tables, no frontend build). I'd keep all logic in a plain Python package so Streamlit is only a view and the CLI/tests don't depend on it.

```
refund-assignment/
  data/                      # given CSVs
  rules/rules.yaml           # seed rule set v1
  refunds/
    ingest.py                # load + normalise + data-quality issues
    signals.py               # note flags: LLM extractor + keyword fallback + cache
    engine.py                # evaluate rules → decision + reason codes (pure, deterministic)
    rules.py                 # schema, load/save, versions, diff
    backtest.py              # labels, metrics, preview(draft vs current)
    store.py                 # SQLite: cases, queue, decisions, rule_versions, llm_cache
    llm.py                   # Anthropic client, prompts, JSON schema, fallback
    cli.py                   # `refunds run FILE`, `refunds backtest`
  app/streamlit_app.py       # pages: Queue · Case · Policy (edit+preview+versions) · Monitoring
  tests/
  README.md  PLAN.md  slides/
```
One command: `make demo` (or `uv run refunds run data/pending.csv && uv run streamlit run app/streamlit_app.py`). `refunds run any.csv` writes `out/decisions.csv` + loads the queue.

Flow: CSV → ingest/normalise → signals (LLM or fallback, cached) → engine(rules vN) → auto-approved log | reviewer queue → reviewer decision log → monitoring/feedback → manager rule edit → preview → publish vN+1.

---

## 8. Tests (pytest)
- **Ingest:** every messy format in §1.1 parses or yields a `DATA_QUALITY` issue (amount variants, DD/MM dates, reason/flag synonyms, blank fraud = unknown, negative days, duplicate IDs).
- **Engine:** one test per gate; boundary tests ($75.00 vs $75.01, day 14 vs 15, $50 photo threshold); priority/conflict behaviour; ratchet (LLM flags can't create an approval).
- **Golden cases:** all 8 chargebacks, 3 overturns, and every policy violation route to human; pending result = exactly {RF-1069, RF-1071} auto (with stubbed signals).
- **Backtest numbers:** proposed line reproduces 112 / $3,664 / 0 bad (fixture-locked).
- **Preview:** ">$300 to human" = 0 changes; cap 75→100 changes exactly the expected IDs; stolen-card rule moves RF-2182 not RF-1070; rollback restores prior results.
- **LLM layer:** no-key fallback path; malformed JSON → unreadable flag; injection note never yields approval (stubbed + one live smoke test if key present).

---

## 9. Deliverables map
| Deliverable | Where |
|---|---|
| Code + one-command run + tests | `refunds/`, `tests/`, `Makefile` |
| Clickable demo | Streamlit: Queue, Case, Policy+Preview, Monitoring (all wired; any mock labelled, e.g. "Request info" notifications) |
| Screen recording | 4 min: pending run → queue → case card → manager adds stolen-card rule → preview → publish → rollback |
| README | run, API key (`ANTHROPIC_API_KEY` in `.env`, optional), architecture, AI-tool note |
| Write-up (≤ 8 slides) | 1 Process today & before/after map · 2 What the data showed (messy data, wrong decisions, $2.5k chargebacks) · 3 The line + backtest · 4 Validation, metrics, rollback · 5 Reviewer mechanism · 6 Manager mechanism + preview · 7 AI: where/where not, model, $/decision, eval results · 8 Deferred & next |

---

## 10. Build order (≈ 5.5 h)
| # | Step | Time |
|---|---|---|
| 1 | Ingest/normalise + data-quality issues + tests | 45 min |
| 2 | Rules schema + engine + seed YAML + gate tests | 45 min |
| 3 | Labels + backtest + preview function + tests | 45 min |
| 4 | Keyword fallback signals, then LLM signal extractor w/ cache + note eval set | 60 min |
| 5 | SQLite store, CLI `run`/`backtest` | 30 min |
| 6 | Streamlit: Queue + Case card + actions + decision log | 45 min |
| 7 | Streamlit: Policy page (form edit, NL→rule, preview, versions, rollback) | 45 min |
| 8 | README, slides outline, recording | 30 min (+ outside budget polish) |

**Deferred / cut (explicitly):** auth & roles; real notifications for "request info"; fraud-team/carrier integrations (photo/POD/investigation are inferred from notes, not real systems); monitoring page with live data beyond computed metrics on the log; partial-amount recommendation model; customer-level velocity across channels; scheduled rule activation; multi-rule conflict editor beyond priority order; LLM case summary (cut first if time is short); Hebrew/Spanish UI translation beyond the note itself.
