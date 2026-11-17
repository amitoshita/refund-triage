# Screen recording script (~4 minutes)

**Setup before recording:** `uv run streamlit run app/streamlit_app.py`, browser at http://localhost:8501,
click **Reset demo state** in the sidebar, window ~1440 wide. Terminal open in the repo folder.

---

**0:00 – 0:25 · Terminal: one command**
- Run `uv run refunds run data/pending.csv`.
- Say: "This runs the whole pipeline on pending.csv, or any file with the same columns. 21 requests: 2 are
  auto-approved, 19 go to a person, each with a lane and a reason. The approve decision is plain rules, not the LLM."

**0:25 – 0:50 · Reviewer queue, overview**
- Switch to the browser (Reviewer queue).
- Point at the four numbers, then the yellow banner.
- Say: "Reviewers see the queue split into lanes. The system also noticed six open cases about parcels stuck at the
  Northfield depot, written six different ways, including Spanish, so they can be handled together."

**0:50 – 1:40 · Case card: RF-1073 (prompt injection)**
- Click lane **Warning signs in notes**, click row **RF-1073**.
- Scroll slowly: reasons → red warning box → customer note.
- Say: "This customer note contains a fake system message telling the agent to approve and skip review. Notes are
  untrusted data: the LLM can only add warning flags, never approve, so it lands here flagged as an injection attempt.
  The card shows every reason it wasn't auto-approved, with the policy number, and what policy suggests."
- Point at **Similar past requests**: "And how similar requests went, including one that ended in a chargeback."

**1:40 – 2:10 · Case card: RF-1074 (Spanish) and a decision**
- Click row **RF-1074**.
- Say: "This one is in Spanish: the customer says the store already refunded them. Most chargebacks in the history
  were human approvals where the warning sign was in the notes. So the warning signs are on the card, not just used
  for routing."
- Leave **Reject** selected, type "already refunded in store" in the reason box, **Submit decision**.
- Say: "Approving despite a warning sign would require a note. Every decision is logged with the rule version."

**2:10 – 3:20 · Policy manager: stolen cards**
- Sidebar → **Policy manager**.
- Click **Stolen-card cases go straight through**, then **Preview on history and pending**.
- Say: "The manager can change rules herself. Here's one of the brief's examples. Before anything goes live she
  sees the impact. Pending: one case moves to auto, RF-2182, where the fraud team confirmed the card was stolen.
  RF-1070 says 'card reported stolen', which isn't a confirmation, so it stays with a person."
- Scroll to the blue PROXY box: "History has no structured 'confirmed' field, so we also show a clearly labelled
  proxy: eight cases would have gone straight through, none went wrong, 106 reviewer minutes saved. Two are over the
  $500 system maximum, and that guardrail can't be overridden by any rule."
- Scroll to **Publish**, type "Brief example: stolen cards", click **Publish as v2**. Point at Version history.

**3:20 – 3:50 · Quick changes and English**
- Click **Raise auto-approve limit to $100** → **Preview**: "Two more cases auto-approved, none went wrong before."
- Optional if a key is set: in **Describe it in English**, type "From now on, anything over $300 comes to us",
  click **Draft a rule**. Say: "The AI drafts the rule and asks whether she meant to change the existing limit. She
  confirms and previews before anything happens. Preview shows zero changes: the $75 cap already covers it."

**3:50 – 4:10 · Rollback and close**
- Version history → **Roll back to v1** → **Preview rollback** → **Confirm**.
- Say: "Every version is kept and rollback is previewed too. The LLM reads notes and drafts rules; the money
  decision stays deterministic, auditable and previewable. It costs about two hundredths of a cent per note."
