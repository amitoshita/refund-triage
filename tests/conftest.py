from pathlib import Path

import pytest

from refunds.config import Guardrails
from refunds.ingest import normalise_row
from refunds.rules import load_ruleset
from refunds.signals import apply_signals

ROOT = Path(__file__).parent.parent

BASE_ROW = {
    "request_id": "RF-1999", "requested_at": "2026-09-01", "customer_id": "CU-1", "tenure_months": "24",
    "prior_refunds_12m": "0", "amount_usd": "30", "category": "apparel", "payment_method": "card",
    "stated_reason": "wrong_size", "customer_note": "", "support_note": "", "days_since_delivery": "5",
    "fraud_flag": "no",
}  # fmt: skip


def make_case(**overrides):
    """A clean, auto-approvable case unless overridden. Keys are CSV column names."""
    return apply_signals(normalise_row({**BASE_ROW, **{k: str(v) for k, v in overrides.items()}}))


@pytest.fixture
def rules():
    return load_ruleset(ROOT / "rules" / "rules.yaml")


@pytest.fixture
def guards():
    return Guardrails(max_auto_amount_usd=500, kill_switch=False)
