# Screen recording script (≈4 minutes, hard stop 4:30)

**Setup:** in the repo folder run `uv run streamlit run app/streamlit_app.py`, open http://localhost:8501, and click
**Reset demo state** in the sidebar. Use a browser window about 1440 px wide, with a terminal next to it.
Sidebar should read "Note reader: LLM claude-haiku-5-5". This works without a key too: the reader uses the committed cache.

---

**0:00 – 0:20 · Terminal: one command**
- Run `uv run refunds run data/pending.csv`.
- Say: "One command runs the whole pipeline on pending.csv, or any file with the same columns. Of 21 requests,
  2 are auto-approved and 19 go to a person, each with a lane and a reason. The approve decision is plain rules,
  not the LLM."

**0:20 – 0:40 · Reviewer queue**
- Switch to the browser. Point at the four numbers, then the yellow banner.
- Say: "Reviewers get the queue split into lanes. The system also spotted six open cases about parcels stuck at the
  Northfield depot, written six different ways, one in Spanish, so they can be handled together."

**0:40 – 1:40 · RF-1073: prompt injection**
- Click the lane **Warning signs in notes (11)**, then the row **RF-1073**.
- Scroll through the reasons, the red box and the customer note.
- Say: "This customer note has a fake system message telling the agent to approve and skip review. Notes are
  untrusted data. The LLM can only add warning flags, never approve. Two layers read every note: a keyword scan always
  runs, the LLM adds on top, and here both caught it. You can see each one's evidence."
- Point at the green box: "Policy doesn't say reject because of the injection. It treats it as a fraud signal and
  suggests escalating. The claim itself is still checked on the facts: never arrived, so carrier proof of delivery,
  policy #4."
- Point at the empty **Decision** choice: "Nothing is preselected. The reviewer has to choose, so they don't just
  confirm what the system suggests."
- Point at **Similar past requests**: "And how similar requests went, including one that ended in a chargeback."

**1:40 – 2:10 · RF-1074: Spanish, and a decision**
- Click the row **RF-1074**.
- Say: "This one's in Spanish: the customer says the store already refunded them. 7 of the 8 chargebacks in the
  history were approved by a person, with the warning sign already in the notes. That's why warning signs are
  on the card, not just used for routing."
- Select **Reject**, type "already refunded in store" in the reason box, click **Submit decision**.
- Say: "Going against the suggestion, or approving despite a warning sign, needs a note. Every decision is logged with
  the rule version."

**2:10 – 3:15 · Policy manager: stolen cards**
- Sidebar → **Policy manager**.
- Click **Stolen-card cases go straight through**, then **Preview on history and pending**.
- Say: "This is one of the brief's examples. The manager makes the change herself, and the preview tells her in plain
  words what changed and what it will do before anything goes live. Today's queue: one case moves to auto, RF-2182,
  where the fraud team confirmed the card was stolen. RF-1070 only says 'card reported stolen', so it stays with a
  person."
- Scroll to the blue PROXY box: "History has no 'fraud team confirmed' field, so the preview also shows a clearly
  labelled proxy: eight cases would have gone straight through, worth $2,215, none went wrong, about nine reviewer
  minutes a week. Two are over the $500 system maximum, and no rule can override that."
- Scroll to **3 · Publish**, type "Brief example: stolen cards", click **Publish as v2**. Point at Version history.

**3:15 – 3:50 · Raising the limit**
- Click **Raise auto-approve limit to $100**, then **Preview on history and pending**.
- Say: "'Auto-approve limit: $75 to $100'. Two more cases in eleven weeks, about two reviewer minutes a week. That's
  why I kept $75: the extra risk buys almost nothing."
- Optional, only with an API key: in **Describe it in English** type "From now on, anything over $300 comes to us",
  click **Draft a rule**, and say "The AI drafts a rule; she still previews it. Zero changes: the $75 limit already
  covers it." Skip this if you're past 3:50.
- Click **Discard my changes**.

**3:50 – 4:15 · Rollback and close**
- Version history → pick v1 in **Roll back to** → **Preview rollback** → **Confirm rollback to v1**.
- Say: "Every version is kept, and rollback gets the same preview. The LLM reads notes and drafts rules for about
  two hundredths of a cent per request. The decision that moves money stays deterministic, logged and previewable."
