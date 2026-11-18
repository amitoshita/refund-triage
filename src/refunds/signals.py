"""Signals derived from free text.

Two kinds, with different trust levels:

* Deterministic facts from the SUPPORT note only (written by staff, trusted):
  ``has_photo_evidence`` and ``fraud_team_confirmed_stolen``. These are the only
  text-derived signals that can move a case toward auto-approval, and only
  through a rule the manager published. Customer notes never set them.
* Warning flags (``note_flags``) from either note. These can only push a case to a
  person. Without an LLM they come from the keyword scan below, and any customer
  note the scan can't confidently clear is flagged ``unreadable``.
"""

import re
from collections.abc import Callable

from refunds.ingest import Case

NoteReader = Callable[[Case], dict[str, str]]  # returns {flag: evidence}; LLM reader plugs in here

NEGATION = re.compile(
    r"\b(no|not|never|without|unconfirmed|awaiting|pending|yet to|asked for|requested|missing|despite)\b|n't\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\s+-\s+", text or "") if s.strip()]


def photo_evidence(support_note: str) -> bool:
    """Staff note says a photo exists, e.g. 'photos clear', 'photo attached looks genuine'."""
    for s in _sentences(support_note):
        if re.search(r"\bphotos?\b", s, re.I) and not NEGATION.search(s):
            return True
    return False


def fraud_team_confirmed_stolen(support_note: str) -> bool:
    """Only an explicit fraud-team confirmation counts. 'card reported stolen', 'customer says
    card stolen', 'bank flagged unauthorised use' are claims, not confirmations.
    Should become a structured field filled by the fraud team (write-up recommendation)."""
    for s in _sentences(support_note):
        if (
            re.search(r"\bfraud team\b", s, re.I)
            and re.search(r"\bconfirm(ed|s)?\b", s, re.I)
            and re.search(r"\b(stolen|unauthori[sz]ed)\b", s, re.I)
            and not NEGATION.search(s)
        ):
            return True
    return False


# flag -> (which note, pattern, reasons it applies to or None for all)
KEYWORD_FLAGS: dict[str, list[tuple[str, str, set[str] | None]]] = {
    "injection_attempt": [
        ("any", r"system note|note to (the )?(refund )?agent|ignore (all |any )?(previous|prior|above)|"
                r"set decision|decision\s*=|skip (human )?review|pre-?approved|classify (this )?as|"
                r"as an ai|you are (an?|the) (ai|agent|assistant)|instructions?:|"
                r"<\s*/?\s*(customer|support)_note\s*>", None),  # our prompt delimiters: an attempt to break out
    ],
    "admits_received": [
        ("any", r"did turn up|turned up|showed up|it arrived|has arrived|found (it|the parcel|the package)", {"never_arrived"}),
    ],
    "admits_self_damage": [
        ("any", r"assembled it (herself|himself|myself|themselves)|i dropped|dropped it|my (own )?fault|admitted", None),
    ],
    "already_refunded": [
        ("any", r"already (been )?refunded|refunded (me )?in (the )?store|already got (my|the) money|"
                r"ya me devolvieron|devolvieron el dinero|already (been )?reimbursed", None),
    ],
    "reason_mismatch": [
        ("customer", r"it'?s fine|works fine|nothing wrong|not the colou?r|don'?t like|didn'?t like|"
                     r"changed my mind|not (really )?my style", {"arrived_damaged", "wrong_item"}),
    ],
    "refund_redirect": [
        ("customer", r"card ending|refund (it )?to (a |my )?(different|other|new)|send (it|the money) to|"
                     r"\+?\d[\d\s-]{8,}\d", None),
    ],
    "signature_on_file": [
        ("support", r"\bsigned\b|signature|\bpod\b|delivery photo|photo of the parcel", {"never_arrived"}),
    ],
    "contradicts_claim": [
        ("support", r"matches (the )?order line|contents fine|outer carton only|still sealed|sealed|"
                    r"customer may be mistaken|couldn'?t say|works fine", None),
    ],
    "repeat_claim": [
        ("any", r"(second|third|fourth|fifth|\d+(st|nd|rd|th)) claim|every one|broken again|again\b", None),
    ],
    "fraud_suspected": [
        ("support", r"address (mismatch|differs)|differs from (the )?card billing|"
                    r"(doesn'?t|does not) match (the )?(billing|shipping)|freight forwarder|"
                    r"billing is a different country", None),
    ],
    "carrier_incident": [
        ("any", r"north\s?field|\bnfd\b|depot|\bhub\b|sort(ing)? cent(re|er)|stuck|"
                r"tracking (hasn'?t moved|stops)|parado", None),
    ],
}  # fmt: skip


def keyword_flags(case: Case) -> dict[str, str]:
    found: dict[str, str] = {}
    for flag, patterns in KEYWORD_FLAGS.items():
        for which, pattern, reasons in patterns:
            if reasons is not None and case.reason not in reasons:
                continue
            notes = []
            if which in ("any", "customer"):
                notes.append(("customer note", case.customer_note))
            if which in ("any", "support"):
                notes.append(("support note", case.support_note))
            for label, text in notes:
                if m := re.search(pattern, text or "", re.I):
                    found.setdefault(flag, f"{label}: '…{m.group(0)}…' (keyword match)")
    return found


def customer_note_cleared(note: str) -> bool:
    """Without an LLM, only short plain-English notes with no numbers are trusted to be benign."""
    return len(note) <= 60 and note.isascii() and not re.search(r"\d", note)


def apply_signals(case: Case, reader: NoteReader | None = None) -> Case:
    case.has_photo_evidence = photo_evidence(case.support_note)
    case.fraud_team_confirmed_stolen = fraud_team_confirmed_stolen(case.support_note)

    # Two layers: the keyword scan always runs; the LLM can add flags on top, never remove them.
    # When both find the same flag, the reviewer sees both pieces of evidence.
    flags = keyword_flags(case)
    if reader is not None:
        try:
            for flag, why in reader(case).items():
                flags[flag] = f"{flags[flag]}; {why}" if flag in flags else why
        except Exception as e:  # any LLM failure -> a person reads it
            flags.setdefault("unreadable", f"note reader failed: {type(e).__name__}: {str(e)[:80]}")
    elif case.customer_note and not customer_note_cleared(case.customer_note):
        flags.setdefault("unreadable", "no LLM available and the customer note is long, non-English, or contains numbers")

    case.note_flags = set(flags)
    case.note_flag_evidence = flags
    return case
