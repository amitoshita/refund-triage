from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from refunds.rules import RuleSet, dump_ruleset, load_ruleset

SEED = Path(__file__).parent.parent / "rules" / "rules.yaml"


def seed_dict() -> dict:
    return yaml.safe_load(SEED.read_text())


def with_rule(rule: dict) -> dict:
    d = seed_dict()
    d["rules"].append(rule)
    return d


def test_seed_loads():
    rs = load_ruleset(SEED)
    assert rs.version == 1
    assert {r.id for r in rs.rules if r.locked} == {"bad_data", "duplicate_request", "note_warning_signs"}
    assert rs.get("amount_cap").when.all_[0].value == 75


def test_round_trip():
    rs = load_ruleset(SEED)
    assert RuleSet.model_validate(yaml.safe_load(dump_ruleset(rs))) == rs


BLOCK = {"id": "test_rule", "kind": "block", "description": "d", "lane": "policy", "reason": "r"}


@pytest.mark.parametrize(
    "cond, msg",
    [
        ({"field": "colour", "op": "eq", "value": "red"}, "unknown field"),
        ({"field": "amount_usd", "op": "in", "value": [1]}, "does not apply"),
        ({"field": "amount_usd", "op": "gt", "value": "300"}, "needs a number"),
        ({"field": "amount_usd", "op": "gt", "value": True}, "needs a number"),
        ({"field": "reason", "op": "eq", "value": "stolen"}, "not valid"),
        ({"field": "note_flags", "op": "has_any", "value": ["made_up"]}, "not valid"),
        ({"field": "is_duplicate", "op": "eq", "value": "yes"}, "true/false"),
        ({"field": "note_flags", "op": "not_empty", "value": 1}, "takes no value"),
    ],
)
def test_bad_conditions_rejected(cond, msg):
    with pytest.raises(ValidationError, match=msg):
        RuleSet.model_validate(with_rule({**BLOCK, "when": {"all": [cond]}}))


def test_cannot_override_locked_rule():
    rule = {
        "id": "let_it_through",
        "kind": "eligible",
        "description": "d",
        "overrides": ["note_warning_signs"],
        "when": {"all": [{"field": "amount_usd", "op": "lt", "value": 10}]},
    }
    with pytest.raises(ValidationError, match="locked safety rule"):
        RuleSet.model_validate(with_rule(rule))


def test_cannot_disable_locked_rule():
    d = seed_dict()
    next(r for r in d["rules"] if r["id"] == "bad_data")["enabled"] = False
    with pytest.raises(ValidationError, match="cannot be disabled"):
        RuleSet.model_validate(d)


def test_block_rule_needs_lane_and_reason():
    rule = {**BLOCK, "lane": None, "when": {"all": [{"field": "amount_usd", "op": "gt", "value": 1}]}}
    with pytest.raises(ValidationError, match="needs a lane and a reason"):
        RuleSet.model_validate(with_rule(rule))


def test_reason_placeholders_must_be_fields():
    rule = {**BLOCK, "reason": "Amount {amount} too high", "when": {"all": [{"field": "amount_usd", "op": "gt", "value": 1}]}}
    with pytest.raises(ValidationError, match="unknown placeholders"):
        RuleSet.model_validate(with_rule(rule))


def test_duplicate_ids_rejected():
    d = seed_dict()
    d["rules"].append(dict(d["rules"][-1]))
    with pytest.raises(ValidationError, match="duplicate rule ids"):
        RuleSet.model_validate(d)


def test_needs_an_eligible_rule():
    d = seed_dict()
    d["rules"] = [r for r in d["rules"] if r["kind"] != "eligible"]
    with pytest.raises(ValidationError, match="nothing could ever be auto-approved"):
        RuleSet.model_validate(d)


def test_stolen_card_rule_expressible():
    """The manager's example rule must be expressible in the schema."""
    rule = {
        "id": "stolen_card_confirmed",
        "kind": "eligible",
        "description": "Fraud team confirmed the card was stolen: refund the real cardholder.",
        "overrides": ["fraud_flag", "never_arrived_check"],
        "when": {"all": [{"field": "fraud_team_confirmed_stolen", "op": "eq", "value": True}]},
    }
    rs = RuleSet.model_validate(with_rule(rule))
    assert rs.get("stolen_card_confirmed").overrides == ["fraud_flag", "never_arrived_check"]
