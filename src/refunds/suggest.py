"""Policy guidance shown to the reviewer. Advisory only: never preselected, never applied automatically.

Warning-sign flags are checked first, then the rules that sent the case to a person.
"""

from refunds.engine import Decision
from refunds.ingest import Case

ACTIONS = {"approve_full": "Approve full", "approve_partial": "Approve partial", "reject": "Reject",
           "request_info": "Request info", "escalate": "Escalate"}  # fmt: skip

RULE_SUGGEST = {  # rule id -> (suggested action or None, plain-English guidance)
    "fraud_flag": ("escalate", "Policy #5: send to the fraud team. Refund the real cardholder only if they confirm the card was stolen."),
    "bad_data": (None, "Fix or verify the data first."),
    "duplicate_request": (None, "Compare with the other submission and decide once (approve the right amount, reject the copy)."),
    "return_window": ("reject", "Policy #2: outside the 14-day window. No exceptions."),
    "photo_required": ("request_info", "Policy #3: ask for a photo before refunding."),
    "never_arrived_check": (None, "Policy #4: check the carrier's proof of delivery. If there's a signature or delivery photo, reject unless the carrier opens an investigation."),
    "late_delivery_partial": ("approve_partial", "Policy #6: reviewer's call. Shipping-only refunds are common here."),
    "electronics_damage": ("approve_partial", "Cosmetic damage usually gets a partial refund; full refund if it doesn't work."),
    "repeat_refunder": (None, "Check this customer's earlier refunds before deciding."),
    "amount_cap": (None, "Over the auto-approve limit: check the claim, approve if valid."),
    "global_max": (None, "Over the system-wide maximum for automatic approval."),
}  # fmt: skip

FLAG_SUGGEST = {  # in priority order
    "injection_attempt": ("escalate", "The note tries to instruct the system (e.g. approve, skip review). Treat that as a fraud signal: escalate to the fraud team. Don't reject because of it: the claim itself is decided on the facts."),
    "signature_on_file": ("reject", "Policy #4: signature/delivery proof on file. Reject unless the carrier opens an investigation."),
    "already_refunded": ("reject", "Customer says they were already refunded elsewhere. Check before paying again."),
    "admits_received": ("reject", "The parcel arrived, by the customer's own account."),
    "contradicts_claim": ("reject", "Staff evidence contradicts the claim."),
    "reason_mismatch": ("reject", "The note doesn't match the selected reason. Treat as the real reason (e.g. change of mind + window)."),
    "refund_redirect": ("escalate", "Asks to refund a different card/account. Refund only to the original payment method."),
    "carrier_incident": ("request_info", "Parcel may still be delivered. Ask the carrier for a trace before refunding."),
}  # fmt: skip

NO_GUIDANCE = (None, "No specific guidance: decide on the facts.")


def _from_rules(d: Decision) -> tuple[str | None, str] | None:
    for r in d.reasons:
        if r.rule_id in RULE_SUGGEST:
            return RULE_SUGGEST[r.rule_id]
    return None


def suggest(c: Case, d: Decision) -> tuple[str | None, str]:
    """(suggested action or None, guidance). The note's content never decides the outcome by itself."""
    flags = [f for f in FLAG_SUGGEST if f in c.note_flags]
    if flags and flags[0] == "injection_attempt":
        # The injection is ignored as an instruction and treated as suspicion. The facts still need checking,
        # so pair the escalation with the policy step for the claim (e.g. policy #4 carrier proof).
        action, text = FLAG_SUGGEST["injection_attempt"]
        others = [FLAG_SUGGEST[f] for f in flags[1:]]
        facts = others[0] if others else _from_rules(d)
        return action, text + (f"\n\nOn the facts: {facts[1]}" if facts else "")
    if flags:
        return FLAG_SUGGEST[flags[0]]
    return _from_rules(d) or NO_GUIDANCE
