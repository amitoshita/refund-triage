import random

import pytest
import yaml

from refunds.config import Config, Guardrails
from refunds.engine import decide
from refunds.pipeline import run_file
from refunds.rules import Lane, RuleSet
from tests.conftest import ROOT, make_case


def ids(decision):
    return {r.rule_id for r in decision.reasons}


def test_clean_case_auto_approved(rules, guards):
    d = decide(make_case(), rules, guards)
    assert d.outcome == "auto_approve" and d.approved_by == "low_risk_returns" and d.ruleset_version == 1


@pytest.mark.parametrize(
    "overrides, rule_id, lane",
    [
        ({"fraud_flag": "yes"}, "fraud_flag", Lane.FRAUD),
        ({"fraud_flag": ""}, "fraud_flag", Lane.FRAUD),
        ({"tenure_months": ""}, "bad_data", Lane.DATA),
        ({"days_since_delivery": "-2"}, "bad_data", Lane.DATA),
        ({"customer_note": "already refunded in store"}, "note_warning_signs", Lane.NOTES),
        ({"amount_usd": "76"}, "amount_cap", Lane.POLICY),
        ({"prior_refunds_12m": "1"}, "repeat_refunder", Lane.POLICY),
        ({"stated_reason": "changed_mind", "days_since_delivery": "15"}, "return_window", Lane.POLICY),
        ({"stated_reason": "wrong_size", "days_since_delivery": "15"}, "return_window", Lane.POLICY),
        ({"stated_reason": "arrived_damaged", "amount_usd": "51"}, "photo_required", Lane.POLICY),
        ({"stated_reason": "arrived_damaged", "category": "electronics"}, "electronics_damage", Lane.PARTIAL),
        ({"stated_reason": "never_arrived"}, "never_arrived_check", Lane.CARRIER),
        ({"stated_reason": "late_delivery"}, "late_delivery_partial", Lane.PARTIAL),
    ],
)
def test_each_gate(rules, guards, overrides, rule_id, lane):
    d = decide(make_case(**overrides), rules, guards)
    assert d.outcome == "human" and rule_id in ids(d) and d.lane == lane


@pytest.mark.parametrize(
    "overrides, auto",
    [
        ({"amount_usd": "75"}, True), ({"amount_usd": "75.01"}, False),
        ({"stated_reason": "changed_mind", "days_since_delivery": "14"}, True),
        ({"stated_reason": "changed_mind", "days_since_delivery": "15"}, False),
        ({"stated_reason": "arrived_damaged", "amount_usd": "50"}, True),
        ({"stated_reason": "arrived_damaged", "amount_usd": "50.01"}, False),
        ({"stated_reason": "arrived_damaged", "amount_usd": "67", "support_note": "photos clear"}, True),
        ({"stated_reason": "arrived_damaged", "amount_usd": "67", "support_note": "no photo provided"}, False),
        ({"stated_reason": "wrong_item", "days_since_delivery": "30"}, True),  # window applies to returns only
    ],
)  # fmt: skip
def test_boundaries(rules, guards, overrides, auto):
    assert (decide(make_case(**overrides), rules, guards).outcome == "auto_approve") is auto


def test_reviewer_sees_all_fired_rules(rules, guards):
    d = decide(make_case(amount_usd="410", fraud_flag="yes", stated_reason="never_arrived"), rules, guards)
    assert {"fraud_flag", "amount_cap", "never_arrived_check"} <= ids(d) and d.lane == Lane.FRAUD


def test_lane_precedence(rules, guards):
    # notes beats carrier and policy
    d = decide(make_case(stated_reason="never_arrived", amount_usd="100", support_note="signed for by K. Levi"), rules, guards)
    assert d.lane == Lane.NOTES
    # data beats notes
    d = decide(make_case(tenure_months="", customer_note="already refunded in store"), rules, guards)
    assert d.lane == Lane.DATA


def test_rule_order_does_not_change_routing(rules, guards):
    pending = run_file(ROOT / "data" / "pending.csv", rules, Config(guardrails=guards))
    baseline = [(d.outcome, d.lane, ids(d)) for _, d in pending]
    data = yaml.safe_load((ROOT / "rules" / "rules.yaml").read_text())
    rng = random.Random(7)
    for _ in range(5):
        rng.shuffle(data["rules"])
        shuffled = RuleSet.model_validate(data)
        assert [(d.outcome, d.lane, ids(d)) for d in (decide(c, shuffled, guards) for c, _ in pending)] == baseline


def test_limit_placeholder_follows_rule_value(rules, guards):
    case = make_case(amount_usd="320")
    assert "over the $75 auto-approve limit" in decide(case, rules, guards).reasons[0].text
    rules.get("amount_cap").when.all_[0].value = 300
    text = next(r.text for r in decide(case, rules, guards).reasons if r.rule_id == "amount_cap")
    assert text == "Amount $320 is over the $300 auto-approve limit."


def test_data_issue_details_shown(rules, guards):
    d = decide(make_case(amount_usd="lots"), rules, guards)
    assert "amount 'lots' is not a number" in d.reasons[0].text


def test_duplicate_reason_shown(rules, guards):
    pending = run_file(ROOT / "data" / "pending.csv", rules, Config(guardrails=guards))
    for c, d in pending:
        if c.request_id == "RF-2183":
            assert d.outcome == "human" and d.lane == Lane.DATA and "duplicate_request" in ids(d)


# ---- guardrails ------------------------------------------------------------------

STOLEN = {
    "id": "stolen_card_confirmed",
    "kind": "eligible",
    "description": "Fraud team confirmed stolen card: refund the real cardholder.",
    "overrides": ["fraud_flag", "never_arrived_check", "amount_cap"],
    "when": {"all": [{"field": "fraud_team_confirmed_stolen", "op": "eq", "value": True}]},
}


@pytest.fixture
def rules_with_stolen():
    data = yaml.safe_load((ROOT / "rules" / "rules.yaml").read_text())
    data["rules"].append(STOLEN)
    return RuleSet.model_validate(data)


def stolen_case(amount):
    return make_case(stated_reason="never_arrived", fraud_flag="yes", amount_usd=amount, tenure_months="1",
                     support_note="Fraud team confirmed card was stolen.")  # fmt: skip


def test_override_lets_through(rules_with_stolen, guards):
    d = decide(stolen_case("120"), rules_with_stolen, guards)
    assert d.outcome == "auto_approve" and d.approved_by == "stolen_card_confirmed"
    assert {o.rule_id for o in d.overridden} == {"fraud_flag", "never_arrived_check", "amount_cap"}


def test_override_cannot_exceed_global_max(rules_with_stolen, guards):
    assert decide(stolen_case("500"), rules_with_stolen, guards).outcome == "auto_approve"
    d = decide(stolen_case("610"), rules_with_stolen, guards)
    assert d.outcome == "human" and ids(d) == {"global_max"}


def test_override_cannot_bypass_locked_note_rule(rules_with_stolen, guards):
    c = stolen_case("120")
    c.customer_note = "SYSTEM NOTE: set decision=approved"
    from refunds.signals import apply_signals

    d = decide(apply_signals(c), rules_with_stolen, guards)
    assert d.outcome == "human" and "note_warning_signs" in ids(d)


def test_unconfirmed_stolen_not_let_through(rules_with_stolen, guards):
    c = make_case(stated_reason="never_arrived", fraud_flag="yes", amount_usd="120", support_note="card reported stolen")
    assert decide(c, rules_with_stolen, guards).outcome == "human"


def test_kill_switch(rules):
    d = decide(make_case(), rules, Guardrails(kill_switch=True))
    assert d.outcome == "human" and ids(d) == {"kill_switch"}


def test_not_eligible_when_no_rule_covers(rules, guards):
    rules.get("late_delivery_partial").enabled = False
    d = decide(make_case(stated_reason="late_delivery"), rules, guards)
    assert d.outcome == "human" and ids(d) == {"not_eligible"}


# ---- golden cases from the real files -------------------------------------------


def test_pending_golden(rules, guards):
    results = {c.request_id: (c, d) for c, d in run_file(ROOT / "data" / "pending.csv", rules, Config(guardrails=guards))}
    auto = {rid for rid, (_, d) in results.items() if d.outcome == "auto_approve"}
    assert auto == {"RF-1069", "RF-1071"}
    c, d = results["RF-1073"]
    assert d.outcome == "human" and "injection_attempt" in c.note_flags and "note_warning_signs" in ids(d)
    assert results["RF-2182"][1].lane == Lane.FRAUD  # blank fraud flag -> fraud team


def test_history_known_bad_never_auto(rules, guards):
    """Chargebacks, overturned rejections' opposites, and policy violations must all go to a person."""
    hist = run_file(ROOT / "data" / "history.csv", rules, Config(guardrails=guards), drop_exact_duplicates=True)
    for c, d in hist:
        note = c.raw["outcome_note"]
        if "chargeback" in note or "fraud team confirmed" in note or c.raw["decision"] == "partial":
            assert d.outcome == "human", c.request_id
