"""Load a refunds CSV and normalise it into Case objects.

Never raises on bad values: anything that can't be parsed becomes a data issue on
the case (which routes it to a person), and the raw value is kept for the reviewer.
"""

import csv
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

from refunds.fields import CATEGORIES, REASONS

COLUMNS = [
    "request_id", "requested_at", "customer_id", "tenure_months", "prior_refunds_12m", "amount_usd",
    "category", "payment_method", "stated_reason", "customer_note", "support_note", "days_since_delivery",
    "fraud_flag", "decision", "decided_by", "outcome_note", "decided_at", "review_minutes",
]  # fmt: skip

REASON_SYNONYMS = {"late": "late_delivery", "damaged": "arrived_damaged"}
FRAUD_VALUES = {"yes": "yes", "y": "yes", "true": "yes", "no": "no", "n": "no", "false": "no"}


@dataclass
class Case:
    request_id: str
    raw: dict[str, str]
    requested_at: date | None = None
    customer_id: str | None = None
    amount_usd: float | None = None
    tenure_months: int | None = None
    prior_refunds_12m: int | None = None
    days_since_delivery: int | None = None
    reason: str | None = None
    category: str | None = None
    payment_method: str | None = None
    channel: str | None = None
    fraud_flag: str = "unknown"
    customer_note: str = ""
    support_note: str = ""
    is_duplicate: bool = False
    duplicate_detail: str = ""
    # filled by signals.py
    has_photo_evidence: bool = False
    fraud_team_confirmed_stolen: bool = False
    note_flags: set[str] = field(default_factory=set)
    note_flag_evidence: dict[str, str] = field(default_factory=dict)  # flag -> why (shown to reviewer)
    data_issues: set[str] = field(default_factory=set)
    issue_details: list[str] = field(default_factory=list)  # human-readable, shown to reviewer

    def get(self, name: str) -> Any:
        return getattr(self, name)

    def issue(self, code: str, detail: str) -> None:
        self.data_issues.add(code)
        self.issue_details.append(detail)


def parse_amount(s: str) -> float | None:
    cleaned = re.sub(r"(?i)usd|\$|,|\s", "", s or "")
    if not re.fullmatch(r"\d+(\.\d+)?", cleaned):
        return None
    return float(cleaned)


def parse_date(s: str) -> date | None:
    s = (s or "").strip()
    if m := re.fullmatch(r"(\d{4}-\d{2}-\d{2})(?:[T ].*)?", s):
        try:
            return date.fromisoformat(m.group(1))
        except ValueError:
            return None
    # Slashed dates are DD/MM/YYYY: confirmed by their position among ISO-dated rows in history.csv.
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def parse_int(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if re.fullmatch(r"-?\d+", s) else None


def normalise_reason(s: str) -> str | None:
    r = re.sub(r"[\s-]+", "_", (s or "").strip().lower())
    r = REASON_SYNONYMS.get(r, r)
    return r if r in REASONS else None


def normalise_row(row: dict[str, str]) -> Case:
    raw = {c: (row.get(c) or "").strip() for c in COLUMNS}
    c = Case(request_id=raw["request_id"], raw=raw)
    c.customer_note, c.support_note = raw["customer_note"], raw["support_note"]

    if not c.request_id:
        c.issue("missing_field", "request_id is missing")
    elif c.request_id.startswith("RF-1"):
        c.channel = "web"
    elif c.request_id.startswith("RF-2"):
        c.channel = "support"

    c.customer_id = raw["customer_id"] or None
    if c.customer_id is None:
        c.issue("missing_field", "customer_id is missing")

    c.requested_at = parse_date(raw["requested_at"])
    if c.requested_at is None:
        c.issue("unparseable_date", f"requested_at '{raw['requested_at']}' is not a date")

    c.amount_usd = parse_amount(raw["amount_usd"])
    if c.amount_usd is None:
        c.issue("unparseable_amount", f"amount '{raw['amount_usd']}' is not a number")

    for name in ("tenure_months", "prior_refunds_12m", "days_since_delivery"):
        v = parse_int(raw[name])
        setattr(c, name, v)
        if v is None:
            c.issue("missing_field", f"{name} is missing or not a whole number ('{raw[name]}')")
        elif v < 0:
            setattr(c, name, None)
            c.issue("negative_days" if name == "days_since_delivery" else "missing_field", f"{name} is negative ({v})")

    c.reason = normalise_reason(raw["stated_reason"])
    if c.reason is None:
        c.issue("unknown_reason", f"reason '{raw['stated_reason']}' is not a known reason")

    cat = raw["category"].lower()
    c.category = cat if cat in CATEGORIES else None
    if c.category is None:
        c.issue("unknown_category", f"category '{raw['category']}' is not a known category")

    pm = raw["payment_method"].lower()
    c.payment_method = pm if pm in ("card", "paypal") else None
    if c.payment_method is None:
        c.issue("missing_field", f"payment_method '{raw['payment_method']}' is missing or unknown")

    # Blank fraud flag means "unknown", never "no". The fraud rule routes unknown to the fraud team.
    c.fraud_flag = FRAUD_VALUES.get(raw["fraud_flag"].lower(), "unknown")
    return c


def mark_duplicates(cases: list[Case], known_ids: Iterable[str] = ()) -> None:
    """Flag every case whose request_id appears more than once in the batch or was already decided.
    All copies are kept and flagged; nothing is dropped silently."""
    counts = Counter(c.request_id for c in cases)
    known = set(known_ids)
    for c in cases:
        if counts[c.request_id] > 1:
            c.is_duplicate = True
            c.duplicate_detail = f"request_id {c.request_id} appears {counts[c.request_id]} times in this file"
        elif c.request_id in known:
            c.is_duplicate = True
            c.duplicate_detail = f"request_id {c.request_id} was already decided earlier"


def read_rows(path: str | Path) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        missing = [c for c in ("request_id", "amount_usd", "stated_reason") if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path}: missing required columns {missing}")
        return list(reader)


def load_cases(path: str | Path, known_ids: Iterable[str] = (), drop_exact_duplicates: bool = False) -> list[Case]:
    """``drop_exact_duplicates`` is for history only (byte-identical rows are export artefacts).
    For new requests, every repeated ID is kept and flagged."""
    rows = read_rows(path)
    if drop_exact_duplicates:
        seen, unique = set(), []
        for r in rows:
            key = tuple(sorted(r.items()))
            if key not in seen:
                seen.add(key)
                unique.append(r)
        rows = unique
    cases = [normalise_row(r) for r in rows]
    mark_duplicates(cases, known_ids)
    return cases
