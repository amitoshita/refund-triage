"""Refund triage demo: reviewer queue + policy manager.

Run: uv run streamlit run app/streamlit_app.py
All screens are wired to the real engine, rules, preview and decision log.
Demo state (live rules, versions, decisions) lives in out/demo/; the sidebar can reset it.
"""

import random
import shutil
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from refunds import llm, store
from refunds.config import ROOT, load_config
from refunds.engine import decide
from refunds.evaluate import load_cached
from refunds.fields import FIELDS, NOTE_FLAGS, OPERATORS, FieldType
from refunds.ingest import load_cases
from refunds.preview import run_preview
from refunds.rules import Lane, Rule, RuleSet, dump_ruleset, load_ruleset
from refunds.signals import apply_signals
from refunds.suggest import ACTIONS, suggest
from refunds.versions import ensure_seeded, list_versions, publish, rollback

DEMO = ROOT / "out" / "demo"
LIVE, VERSIONS, DB = DEMO / "rules_live.yaml", DEMO / "versions", DEMO / "decisions.db"
SEED = ROOT / "rules" / "rules.yaml"

LANE_LABELS = {
    "fraud": "Fraud team", "data": "Data fix", "notes": "Warning signs in notes",
    "carrier": "Carrier check", "partial": "Full or partial?", "policy": "Policy check",
}  # fmt: skip


# ---------------------------------------------------------------- state & data


def reset_demo():
    shutil.rmtree(DEMO, ignore_errors=True)
    DEMO.mkdir(parents=True)
    shutil.copy(SEED, LIVE)
    ensure_seeded(LIVE, VERSIONS)


if not LIVE.exists():
    reset_demo()

cfg = load_config()


@st.cache_resource
def reader():
    return llm.LLMNoteReader(cfg.llm.model, offline=not llm.has_key())


@st.cache_resource
def load_history():
    return [apply_signals(c, reader()) for c in load_cached("history")]


@st.cache_resource
def load_pending(path: str, mtime: float):
    known = {c.request_id for c in load_history()}
    cases = [apply_signals(c, reader()) for c in load_cases(path, known_ids=known)]
    reader().save()
    return cases


def con():
    if "con" not in st.session_state:
        st.session_state.con = store.connect(DB)
    return st.session_state.con


def money(v) -> str:
    return "?" if v is None else f"${v:,.2f}"


# ---------------------------------------------------------------- sidebar

st.set_page_config(page_title="Refund triage", page_icon="🧾", layout="wide")
with st.sidebar:
    st.title("Refund triage")
    page = st.radio("Screen", ["Reviewer queue", "Policy manager"])
    st.divider()
    reviewer = st.text_input("Your name", "S. Kwan")
    uploaded = st.file_uploader("Requests file (same columns as pending.csv)", type="csv")
    if uploaded:
        up = DEMO / "uploaded.csv"
        up.write_bytes(uploaded.getvalue())
        pending_path = up
    else:
        pending_path = ROOT / "data" / "pending.csv"
    st.caption(f"File: {pending_path.name}")
    mode = "LLM " + cfg.llm.model + ("" if llm.has_key() else " (cached results, no API key)")
    st.caption(f"Note reader: {mode}")
    g = cfg.guardrails
    st.caption(f"Guardrails (engineer-owned): max auto ${g.max_auto_amount_usd:,.0f} · kill switch {'ON' if g.kill_switch else 'off'}")
    if st.button("Reset demo state"):
        reset_demo()
        st.session_state.clear()
        st.rerun()

rules = load_ruleset(LIVE)
history = load_history()
pending = load_pending(str(pending_path), pending_path.stat().st_mtime)
decisions = [(c, decide(c, rules, cfg.guardrails)) for c in pending]


# ---------------------------------------------------------------- reviewer queue


def similar_history(c, n=5):
    lo, hi = (c.amount_usd or 0) * 0.5, (c.amount_usd or 0) * 2
    sims = [h for h in history if h.reason == c.reason and h.category == c.category
            and h.amount_usd is not None and lo <= h.amount_usd <= hi]  # fmt: skip
    sims.sort(key=lambda h: abs(h.amount_usd - (c.amount_usd or 0)))
    return pd.DataFrame([{
        "request": h.request_id, "amount": money(h.amount_usd), "decision": h.raw["decision"],
        "by": h.raw["decided_by"], "what happened after": h.raw["outcome_note"] or "-",
        "notes": " | ".join(x for x in (h.customer_note, h.support_note) if x)[:90],
    } for h in sims[:n]])  # fmt: skip


def case_card(c, d, latest):
    st.subheader(f"{c.request_id} · {money(c.amount_usd)} · {(c.reason or c.raw['stated_reason']).replace('_', ' ')}")
    facts = [
        ("Category", c.category or c.raw["category"] or "?"),
        ("Account age", f"{c.tenure_months} months" if c.tenure_months is not None else "missing"),
        ("Refunds (12 mo)", c.prior_refunds_12m if c.prior_refunds_12m is not None else "missing"),
        ("Days since delivery", c.days_since_delivery if c.days_since_delivery is not None else "missing"),
        ("Fraud flag", c.fraud_flag),
        ("Channel", c.channel or "?"),
        ("Customer", c.customer_id or "missing"),
    ]
    for col, (label, value) in zip(st.columns(len(facts)), facts):
        col.caption(label)
        col.markdown(f"**{value}**")

    left, right = st.columns([3, 2])
    with left:
        st.markdown(f"**Why this came to you** · lane: *{LANE_LABELS.get(str(d.lane), d.lane)}*")
        for r in d.reasons:
            ref = f" (policy #{r.policy_ref})" if r.policy_ref else ""
            st.markdown(f"- {r.text}{ref}")
        for o in d.overridden:
            st.caption(f"Lifted by rule '{o.overridden_by}': {o.text}")

        if c.note_flags:
            st.error("**Warning signs in the notes**\n\n" + "\n".join(
                f"- **{f.replace('_', ' ')}**: {c.note_flag_evidence.get(f, '')}" for f in sorted(c.note_flags)))  # fmt: skip
            st.caption("Two layers check every note: a keyword scan always runs, and the AI reader adds flags on top. "
                       "Neither can remove a flag. Evidence is labelled with its source.")  # fmt: skip
        summary = reader().summaries.get(c.request_id)
        if summary:
            st.info(f"**AI summary (verify against the notes):** {summary}")
        st.markdown("**Customer note** (written by the customer, untrusted)")
        st.code(c.customer_note or "(none)", language=None, wrap_lines=True)
        st.markdown("**Support note** (written by staff)")
        st.code(c.support_note or "(none)", language=None, wrap_lines=True)
        if c.issue_details or c.duplicate_detail:
            st.warning("**Data problems:** " + "; ".join(c.issue_details + ([c.duplicate_detail] if c.duplicate_detail else [])))
            messy = {k: v for k, v in c.raw.items() if k in ("amount_usd", "requested_at", "stated_reason", "fraud_flag", "category")}
            st.caption(f"Raw values as submitted: {messy}")

    with right:
        action, guidance = suggest(c, d)
        st.markdown("**Suggested by policy**")
        st.success(guidance + (f"\n\nSuggested action: **{ACTIONS[action]}**" if action else ""))
        if latest:
            st.warning(f"Last action: **{ACTIONS[latest['action']]}** by {latest['reviewer']} at {latest['decided_at']}"
                       + (f" ({latest['detail']})" if latest['detail'] else ""))  # fmt: skip

        with st.form(f"decide_{c.request_id}_{id(c)}"):
            # Not preselected, so the reviewer makes an active choice (avoids rubber-stamping the suggestion).
            choice = st.radio("Decision", list(ACTIONS), format_func=ACTIONS.get, horizontal=True, index=None)
            amount = st.number_input("Refund amount ($), for approve / partial", min_value=0.0,
                                     value=float(c.amount_usd or 0), step=1.0)  # fmt: skip
            detail = st.text_input("Reject reason / info requested / escalate to",
                                   placeholder="e.g. outside window · photo of the damage · fraud team")  # fmt: skip
            note = st.text_area("Note (required if you go against the suggestion or warning signs)", height=70)
            if st.form_submit_button("Submit decision", type="primary"):
                against = (action and choice != action) or (c.note_flags and choice == "approve_full")
                if choice is None:
                    st.error("Please pick a decision.")
                elif against and not note.strip():
                    st.error("Please add a note: you're going against the suggestion or the warning signs.")
                elif choice == "approve_partial" and not (0 < amount < (c.amount_usd or 0)):
                    st.error("A partial refund must be more than $0 and less than the requested amount.")
                else:
                    store.record(con(), request_id=c.request_id, action=choice,
                                 amount_usd=amount if choice.startswith("approve") else None,
                                 detail=detail or None, note=note or None, reviewer=reviewer, lane=str(d.lane),
                                 suggested=action, rule_version=d.ruleset_version)  # fmt: skip
                    st.toast(f"{c.request_id}: {ACTIONS[choice]} recorded")
                    st.rerun()

    st.markdown("**Similar past requests** (same reason and category, similar amount)")
    sims = similar_history(c)
    if sims.empty:
        st.caption("None found.")
    else:
        st.dataframe(sims, hide_index=True, width="stretch")


def first_reason(rule_ids: list[str]) -> str:
    """Queue cell: short name of the first rule only; the case card lists every reason in full."""
    if not rule_ids:
        return "-"
    return rule_ids[0].replace("_", " ") + (f" (+{len(rule_ids) - 1} more)" if len(rule_ids) > 1 else "")


def reviewer_page():
    latest = store.latest_by_request(con())
    human = [(c, d) for c, d in decisions if d.outcome == "human"]
    auto = [(c, d) for c, d in decisions if d.outcome == "auto_approve"]
    open_ = [(c, d) for c, d in human if c.request_id not in latest or latest[c.request_id]["action"] in ("request_info", "escalate")]
    done = [(c, d) for c, d in human if (c, d) not in open_]

    st.header("Reviewer queue")
    m = st.columns(4)
    m[0].metric("Requests in file", len(decisions))
    m[1].metric("Auto-approved", f"{len(auto)} · {money(sum(c.amount_usd or 0 for c, _ in auto))}")
    m[2].metric("Open in queue", len(open_))
    m[3].metric("Decided by reviewers", len(done))

    incident = [c for c, _ in open_ if "carrier_incident" in c.note_flags]
    if len(incident) >= 3:
        st.warning(f"**Possible carrier incident:** {len(incident)} open cases mention a stuck parcel / depot "
                   f"({', '.join(c.request_id for c in incident)}). Consider handling them together.")  # fmt: skip

    lanes = [l.value for l in [Lane.FRAUD, Lane.DATA, Lane.NOTES, Lane.CARRIER, Lane.PARTIAL, Lane.POLICY]]
    counts = {l: sum(1 for _, d in open_ if str(d.lane) == l) for l in lanes}
    lane_pick = st.radio("Lane", ["all"] + lanes, horizontal=True,
                         format_func=lambda l: f"All ({len(open_)})" if l == "all" else f"{LANE_LABELS[l]} ({counts[l]})")  # fmt: skip
    shown = [(c, d) for c, d in open_ if lane_pick == "all" or str(d.lane) == lane_pick]

    if not shown:
        st.success("Nothing open in this lane.")
    else:
        def status(c):
            a = latest.get(c.request_id, {}).get("action")
            return {"request_info": "waiting for info", "escalate": "escalated"}.get(a, "new")

        rows = [{
            "request": c.request_id, "amount": c.amount_usd, "reason": (c.reason or "?").replace("_", " "),
            "status": status(c), "lane": LANE_LABELS.get(str(d.lane)),
            "warning signs": ", ".join(f.replace("_", " ") for f in sorted(c.note_flags)) or "-",
            "other reasons": first_reason([r.rule_id for r in d.reasons if r.rule_id != "note_warning_signs"]),
        } for c, d in shown]  # fmt: skip
        sel = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", on_select="rerun",
                           selection_mode="single-row", column_config={
                               "amount": st.column_config.NumberColumn(format="$%.2f", width="small"),
                               "request": st.column_config.TextColumn(width="small"),
                               "status": st.column_config.TextColumn(width="small"),
                               "warning signs": st.column_config.TextColumn(width="medium"),
                               "other reasons": st.column_config.TextColumn(
                                   help="First rule that sent it here; open the case for every reason in full.")})  # fmt: skip
        idx = sel.selection.rows[0] if sel.selection.rows else 0
        st.caption("Click a row to open it.")
        st.divider()
        c, d = shown[idx]
        case_card(c, d, latest.get(c.request_id))

    with st.expander(f"Auto-approved ({len(auto)}) · audit sample"):
        rng = random.Random(42)
        st.caption("Every auto-approval is logged with the rule that approved it. A random 10% (100% in the first "
                   "week after launch) is re-checked by a reviewer to measure the error rate.")  # fmt: skip
        st.dataframe(pd.DataFrame([{
            "request": c.request_id, "amount": money(c.amount_usd), "reason": c.reason, "approved by rule": d.approved_by,
            "rule version": d.ruleset_version, "in audit sample": "yes" if rng.random() < 0.10 or len(auto) <= 10 else "",
        } for c, d in auto]), hide_index=True, width="stretch")  # fmt: skip

    with st.expander("Decision log (append-only)"):
        log = store.all_decisions(con())
        if log:
            df = pd.DataFrame(log).drop(columns=["id"])
            df["overrode suggestion"] = df.apply(lambda r: bool(r["suggested"]) and r["suggested"] != r["action"], axis=1)
            st.dataframe(df, hide_index=True, width="stretch")
        else:
            st.caption("No decisions yet.")


# ---------------------------------------------------------------- policy manager

STOLEN = {"id": "stolen_card_confirmed", "kind": "eligible",
          "description": "From now on, stolen-card cases go straight through (fraud team confirmed the card was stolen).",
          "overrides": ["fraud_flag", "never_arrived_check", "amount_cap"],
          "when": {"all": [{"field": "fraud_team_confirmed_stolen", "op": "eq", "value": True}]}}  # fmt: skip
OVER_300 = {"id": "over_300_to_us", "kind": "block", "description": "From now on, anything over $300 comes to us.",
            "lane": "policy", "reason": "Over ${limit}: manager asked to see these.",
            "when": {"all": [{"field": "amount_usd", "op": "gt", "value": 300}]}}  # fmt: skip


def draft_dict() -> dict:
    if "draft" not in st.session_state:
        st.session_state.draft = rules.model_dump(mode="json", by_alias=True)
        st.session_state.gen = 0
    return st.session_state.draft


def set_draft(d: dict):
    st.session_state.draft = d
    st.session_state.gen = st.session_state.get("gen", 0) + 1  # new widget keys so they show the new values
    st.session_state.pop("preview", None)


def find(d: dict, rule_id: str) -> dict | None:
    return next((r for r in d["rules"] if r["id"] == rule_id), None)


def show_preview(p):
    if p.rule_diff:
        st.markdown("**What changes in the rules:**\n" + "\n".join(f"- {line}" for line in p.rule_diff))
    for w in p.warnings:
        st.warning(w)
    for ds in p.datasets:
        box = st.container(border=True)
        if "PROXY" in ds.name:
            box.info("**PROXY VIEW**: history has no structured 'fraud team confirmed' field. This view pretends it "
                     "existed, filled from the outcome notes written after each decision. Use it to size the change, "
                     "not as evidence the rule works today.")  # fmt: skip
        box.markdown(f"**{ds.name}** · {ds.total} requests")
        usd = lambda v: f"${v:,.0f}"
        c = box.columns(2)
        dn, du = ds.auto_after - ds.auto_before, ds.usd_auto_after - ds.usd_auto_before
        c[0].metric("Auto-approved", ds.auto_after, f"{dn:+d} vs live" if dn else None, delta_color="off")
        c[1].metric("$ auto-approved", usd(ds.usd_auto_after), f"{du:+,.0f} vs live" if round(du) else None, delta_color="off")
        if "History" in ds.name:
            c = box.columns(2)
            c[0].metric("Newly auto, went wrong before", len(ds.newly_auto_bad))
            weeks = p.history_weeks
            per_week = f"≈ {ds.minutes_saved / weeks:.0f} min / week" if weeks and ds.minutes_saved else None
            c[1].metric(f"Reviewer minutes saved (≈{weeks:.0f} wks)" if weeks else "Reviewer minutes saved",
                        f"{ds.minutes_saved:.0f}", per_week, delta_color="off", delta_arrow="off")  # fmt: skip
        if ds.changes:
            box.dataframe(pd.DataFrame([{
                "request": ch.request_id, "amount": money(ch.amount_usd),
                "before": "auto" if ch.before == "auto" else LANE_LABELS.get(ch.before, ch.before),
                "after": "auto" if ch.after == "auto" else LANE_LABELS.get(ch.after, ch.after),
                "why (after)": ch.after_reasons[0] if ch.after_reasons else "auto-approved",
                "known problem (history)": ch.bad or "",
            } for ch in ds.changes]), hide_index=True, width="stretch")  # fmt: skip
        else:
            box.caption("No request changes route.")


def labels(d: dict) -> dict[str, str]:
    """Rule id -> short name, for plain-English descriptions."""
    return {x["id"]: x.get("name") or x["id"].replace("_", " ").capitalize() for x in d["rules"]}


def rule_editor(d: dict):
    gen = st.session_state.gen
    for r in d["rules"]:
        rule = Rule.model_validate(r)
        icon = "🔒" if rule.locked else ("✅" if rule.kind == "eligible" else "⛔")
        state = "" if r.get("enabled", True) else " (off)"
        with st.expander(f"{icon} {rule.description}{state}"):
            st.caption(f"id: {rule.id} · {rule.kind}" + (f" · policy #{rule.policy_ref}" if rule.policy_ref else ""))
            from refunds.rule_nl import describe

            st.markdown(describe(rule, labels(d)))
            if rule.locked:
                st.caption("Safety rule: can't be switched off or overridden here.")
                continue
            r["enabled"] = st.checkbox("On", value=r.get("enabled", True), key=f"en_{rule.id}_{gen}")
            for part in ("all", "any"):
                for i, c in enumerate(r["when"].get(part, [])):
                    ftype, _, allowed, label = FIELDS[c["field"]]
                    key = f"{rule.id}_{part}_{i}_{gen}"
                    if ftype is FieldType.NUMBER:
                        c["value"] = st.number_input(f"{label} {c['op']}", value=float(c["value"]), step=1.0, key=key)
                    elif c["op"] in ("in", "not_in", "has_any"):
                        c["value"] = st.multiselect(f"{label} {c['op']}", allowed, default=c["value"], key=key)
            if rule.kind == "eligible":
                blockable = [x["id"] for x in d["rules"] if x["kind"] == "block" and not x.get("locked")]
                r["overrides"] = st.multiselect("Lets through cases blocked by", blockable,
                                                default=r.get("overrides", []), key=f"ov_{rule.id}_{gen}")  # fmt: skip
            if st.button("Remove this rule", key=f"rm_{rule.id}_{gen}"):
                set_draft({**d, "rules": [x for x in d["rules"] if x["id"] != rule.id]})
                st.rerun()


def add_rule_forms(d: dict):
    tab_en, tab_form = st.tabs(["Describe it in English (AI drafts it)", "Build it with a form"])
    with tab_en:
        text = st.text_input("What should change?", placeholder="e.g. From now on, anything over $300 comes to us.")
        if st.button("Draft a rule", disabled=not llm.has_key(), help=None if llm.has_key() else "Needs an API key"):
            from refunds.rule_nl import draft_rule

            with st.spinner("Drafting..."):
                st.session_state.nl = draft_rule(text, load_ruleset_from(d), cfg.llm.model)
        if not llm.has_key():
            st.caption("No API key: the English option is off. Use the form or the quick changes.")
        if st.session_state.get("nl"):
            rule, msg = st.session_state.nl
            if msg:
                st.info(f"**Question from the assistant:** {msg}")
            if rule:
                try:
                    from refunds.rule_nl import describe

                    st.success("**Draft:** " + describe(Rule.model_validate(rule), labels(d)))
                    st.code(yaml.safe_dump(rule, sort_keys=False), language="yaml", wrap_lines=True)
                    if st.button("Add this draft to my changes", type="primary"):
                        add_rule(d, rule)
                except Exception as e:
                    st.error(f"The draft isn't a valid rule: {e}")
    with tab_form:
        kind = st.radio("When it matches", ["block", "eligible"], horizontal=True,
                        format_func={"block": "Send to a person", "eligible": "Allow auto-approval"}.get)  # fmt: skip
        desc = st.text_input("Describe it (shown to everyone)", key="f_desc")
        field = st.selectbox("Field", list(FIELDS), format_func=lambda f: FIELDS[f][3])
        ftype, _, allowed, _ = FIELDS[field]
        ops = [o for o, types in OPERATORS.items() if ftype in types]
        op = st.selectbox("Condition", ops)
        if op in ("is_empty", "not_empty", "is_missing"):
            value = None
        elif ftype is FieldType.NUMBER:
            value = st.number_input("Value", value=0.0, step=1.0)
        elif ftype is FieldType.BOOL:
            value = st.checkbox("Value is true", value=True)
        elif op in ("in", "not_in", "has_any"):
            value = st.multiselect("Values", allowed)
        else:
            value = st.selectbox("Value", allowed)
        rule = {"id": "_".join(desc.lower().split())[:30].strip("_") or "new_rule", "kind": kind,
                "description": desc or "New rule", "when": {"all": [{"field": field, "op": op, "value": value}]}}  # fmt: skip
        if kind == "block":
            rule["lane"] = st.selectbox("Queue lane", [l.value for l in Lane], index=5, format_func=LANE_LABELS.get)
            rule["reason"] = st.text_input("What the reviewer sees", value=desc or "Manager rule")
        else:
            blockable = [x["id"] for x in d["rules"] if x["kind"] == "block" and not x.get("locked")]
            rule["overrides"] = st.multiselect("Lets through cases blocked by", blockable)
        if st.button("Add to my changes"):
            add_rule(d, rule)


def add_rule(d: dict, rule: dict):
    import re

    rule["id"] = re.sub(r"[^a-z0-9_]", "", rule["id"].lower()) or "new_rule"
    if not rule["id"][0].isalpha():
        rule["id"] = "r_" + rule["id"]
    base, n = rule["id"], 2
    while find(d, rule["id"]):  # similar rules are allowed, but ids must stay unique
        rule["id"], n = f"{base}_{n}", n + 1
    set_draft({**d, "rules": d["rules"] + [rule]})
    st.session_state.pop("nl", None)
    st.rerun()


def add_example(d: dict, rule: dict):
    """Quick-change buttons: clicking again must not add a second copy."""
    if find(d, rule["id"]):
        st.info("Already in your changes.")
        return
    add_rule(d, yaml.safe_load(yaml.safe_dump(rule)))


def load_ruleset_from(d: dict) -> RuleSet:
    return RuleSet.model_validate(d)


def policy_page():
    st.header("Policy manager")
    st.caption(f"Live rules: **v{rules.version}** · {rules.author} · {rules.created_at:%Y-%m-%d %H:%M} · “{rules.change_note}”")
    d = draft_dict()

    st.markdown("**Quick changes** (the examples from the brief)")
    q = st.columns(4)
    if q[0].button("Raise auto-approve limit to $100"):
        nd = yaml.safe_load(yaml.safe_dump(d))
        find(nd, "amount_cap")["when"]["all"][0]["value"] = 100
        set_draft(nd)
        st.rerun()
    if q[1].button("Anything over $300 comes to us"):
        add_example(d, OVER_300)
    if q[2].button("Stolen-card cases go straight through"):
        add_example(d, STOLEN)
    if q[3].button("Discard my changes"):
        st.session_state.pop("draft", None)
        st.session_state.pop("preview", None)
        st.rerun()

    left, right = st.columns([2, 3])
    with left:
        st.subheader("1 · Edit the rules")
        rule_editor(d)
        st.subheader("Add a rule")
        add_rule_forms(d)
    with right:
        st.subheader("2 · Preview the impact")
        try:
            draft = load_ruleset_from(d)
        except Exception as e:
            st.error(f"These changes aren't valid yet:\n\n{e}")
            return
        fingerprint = dump_ruleset(draft)
        changed = fingerprint != dump_ruleset(rules)
        if not changed:
            st.caption("No changes yet. Use the quick changes or edit a rule on the left.")
        if st.button("Preview on history and pending", type="primary", disabled=not changed):
            st.session_state.preview = (fingerprint, run_preview(rules, draft, cfg.guardrails, history, pending))
        prev = st.session_state.get("preview")
        if prev and prev[0] == fingerprint:
            show_preview(prev[1])
            st.subheader("3 · Publish")
            note = st.text_input("Why are you making this change?", key="pub_note")
            if st.button(f"Publish as v{max(v.version for v in list_versions(VERSIONS)) + 1}", disabled=not note.strip()):
                new = publish(draft, reviewer, note, LIVE, VERSIONS)
                st.session_state.pop("draft", None)
                st.session_state.pop("preview", None)
                st.toast(f"Published v{new.version}. New requests are decided with it from now on.")
                st.rerun()
        elif prev:
            st.caption("The rules changed since the last preview. Preview again before publishing.")

    st.divider()
    st.subheader("Version history")
    versions = list_versions(VERSIONS)
    st.dataframe(pd.DataFrame([{"version": v.version, "when": f"{v.created_at:%Y-%m-%d %H:%M}", "by": v.author,
                                "why": v.change_note, "live": "●" if v.version == rules.version else ""}
                               for v in reversed(versions)]), hide_index=True, width="stretch")  # fmt: skip
    older = [v.version for v in versions if v.version != rules.version]
    if older:
        c = st.columns([1, 1, 2])
        target = c[0].selectbox("Roll back to", older, index=len(older) - 1)
        if c[1].button("Preview rollback"):
            old = next(v for v in versions if v.version == target)
            st.session_state.rb = (target, run_preview(rules, old, cfg.guardrails, history, pending))
        rb = st.session_state.get("rb")
        if rb and rb[0] == target:
            show_preview(rb[1])
            if st.button(f"Confirm rollback to v{target}", type="primary"):
                rollback(target, reviewer, LIVE, VERSIONS)
                st.session_state.pop("rb", None)
                st.session_state.pop("draft", None)
                st.rerun()


if page == "Reviewer queue":
    reviewer_page()
else:
    policy_page()
