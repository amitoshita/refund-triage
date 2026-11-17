"""Vocabulary that rules may reference.

Rules can only test fields listed here, with operators valid for the field's
type. This is what lets the manager edit rules without an engineer while
keeping rules safe to evaluate: there is no expression language and no eval.
"""

from enum import StrEnum


class FieldType(StrEnum):
    NUMBER = "number"
    ENUM = "enum"
    BOOL = "bool"
    FLAGS = "flags"  # a set of string flags (note flags, data issues)


class Source(StrEnum):
    """Where a field's value comes from. Shown to the manager in the editor."""

    DATA = "data"  # normalised from the CSV columns
    DERIVED = "derived"  # computed deterministically (e.g. duplicate check, staff-note keywords)
    LLM = "llm"  # extracted by the LLM from free text; can only ever add warning flags


REASONS = ["wrong_size", "changed_mind", "arrived_damaged", "wrong_item", "never_arrived", "late_delivery"]
CATEGORIES = ["apparel", "home", "electronics"]

# Warning signs the note reader can raise. Every one pushes a case toward a human.
NOTE_FLAGS = [
    "injection_attempt",  # text addressed to the system / agent ("set decision=approved")
    "contradicts_claim",  # staff note or evidence contradicts the stated reason
    "admits_received",  # customer says it arrived after all
    "admits_self_damage",
    "already_refunded",  # refunded elsewhere (store, other channel)
    "reason_mismatch",  # note describes a different reason than the one selected
    "refund_redirect",  # asks to refund a different card / account
    "signature_on_file",  # carrier signature or delivery photo exists
    "repeat_claim",  # staff note mentions repeated claims
    "fraud_suspected",  # new account + address mismatch etc.
    "carrier_incident",  # parcel stuck at a depot / known carrier backlog
    "unreadable",  # LLM failed, or no key and note couldn't be cleared by fallback
]

DATA_ISSUES = [
    "missing_field",
    "unparseable_amount",
    "unparseable_date",
    "unknown_reason",
    "unknown_category",
    "negative_days",
]

# name -> (type, source, allowed values for enum/flags, plain-English label)
FIELDS: dict[str, tuple[FieldType, Source, list[str] | None, str]] = {
    "amount_usd": (FieldType.NUMBER, Source.DATA, None, "Refund amount ($)"),
    "tenure_months": (FieldType.NUMBER, Source.DATA, None, "Account age (months)"),
    "prior_refunds_12m": (FieldType.NUMBER, Source.DATA, None, "Refunds in last 12 months"),
    "days_since_delivery": (FieldType.NUMBER, Source.DATA, None, "Days since delivery"),
    "reason": (FieldType.ENUM, Source.DATA, REASONS, "Stated reason"),
    "category": (FieldType.ENUM, Source.DATA, CATEGORIES, "Product category"),
    "payment_method": (FieldType.ENUM, Source.DATA, ["card", "paypal"], "Payment method"),
    "channel": (FieldType.ENUM, Source.DERIVED, ["web", "support"], "Channel (from request ID)"),
    "fraud_flag": (FieldType.ENUM, Source.DATA, ["yes", "no", "unknown"], "Payment-provider fraud flag"),
    "is_duplicate": (FieldType.BOOL, Source.DERIVED, None, "Request ID seen before"),
    "has_photo_evidence": (FieldType.BOOL, Source.DERIVED, None, "Staff note confirms a photo"),
    "fraud_team_confirmed_stolen": (FieldType.BOOL, Source.DERIVED, None, "Staff note: fraud team confirmed stolen card"),
    "data_issues": (FieldType.FLAGS, Source.DERIVED, DATA_ISSUES, "Data problems"),
    "note_flags": (FieldType.FLAGS, Source.LLM, NOTE_FLAGS, "Warning signs in the notes"),
}

# operator -> field types it applies to
OPERATORS: dict[str, set[FieldType]] = {
    "gt": {FieldType.NUMBER},
    "gte": {FieldType.NUMBER},
    "lt": {FieldType.NUMBER},
    "lte": {FieldType.NUMBER},
    "eq": {FieldType.NUMBER, FieldType.ENUM, FieldType.BOOL},
    "ne": {FieldType.NUMBER, FieldType.ENUM},
    "in": {FieldType.ENUM},
    "not_in": {FieldType.ENUM},
    "has_any": {FieldType.FLAGS},  # flags ∩ value non-empty
    "is_empty": {FieldType.FLAGS},
    "not_empty": {FieldType.FLAGS},
    "is_missing": {FieldType.NUMBER, FieldType.ENUM},
}
