import pytest

from refunds.config import Guardrails
from refunds.evaluate import load_cached
from refunds.llm import CACHE_PATH, LLMNoteReader
from refunds.preview import run_preview
from refunds.rules import Rule, RuleSet, load_ruleset
from refunds.signals import apply_signals
from refunds.versions import list_versions, publish, rollback
from tests.conftest import ROOT

G = Guardrails()


@pytest.fixture(scope="module")
def data():
    return [apply_signals(c) for c in load_cached("history")], [apply_signals(c) for c in load_cached("pending")]


def draft(rules: RuleSet, fn) -> RuleSet:
    d = rules.model_copy(deep=True)
    fn(d)
    return RuleSet.model_validate(d.model_dump(by_alias=True))


def add(rule: dict):
    return lambda d: d.rules.append(Rule.model_validate(rule))


OVER_300 = {"id": "over_300_to_us", "kind": "block", "description": "Anything over $300 comes to us",
            "lane": "policy", "reason": "Over ${limit}", "when": {"all": [{"field": "amount_usd", "op": "gt", "value": 300}]}}  # fmt: skip
STOLEN = {"id": "stolen_card_confirmed", "kind": "eligible", "description": "Fraud team confirmed stolen card",
          "overrides": ["fraud_flag", "never_arrived_check", "amount_cap"],
          "when": {"all": [{"field": "fraud_team_confirmed_stolen", "op": "eq", "value": True}]}}  # fmt: skip


def test_no_change_preview_is_empty(rules, data):
    p = run_preview(rules, rules, G, *data)
    assert p.rule_diff == [] and all(not d.changes for d in p.datasets)


def test_over_300_is_redundant_today(rules, data):
    p = run_preview(rules, draft(rules, add(OVER_300)), G, *data)
    assert p.rule_diff == ["+ added 'over_300_to_us': Anything over $300 comes to us"]
    assert all(not d.changes for d in p.datasets)


def test_lowering_cap_moves_exactly_the_band(rules, data):
    hist, _ = data
    p = run_preview(rules, draft(rules, lambda d: setattr(d.get("amount_cap").when.all_[0], "value", 50)), G, *data)
    h = p.datasets[0]
    assert h.to_auto == [] and h.to_human
    assert all(50 < c.amount_usd <= 75 and c.after == "policy" for c in h.to_human)
    assert h.auto_before - h.auto_after == len(h.to_human)
    assert h.usd_auto_before - h.usd_auto_after == pytest.approx(sum(c.amount_usd for c in h.to_human))


def test_stolen_card_strict_and_proxy(rules, data):
    p = run_preview(rules, draft(rules, add(STOLEN)), G, *data)
    hist, pend, proxy = p.datasets
    assert hist.changes == []  # strict: no history support note says "fraud team confirmed"
    assert [c.request_id for c in pend.to_auto] == ["RF-2182"]  # RF-1070 'card reported stolen' stays
    assert "PROXY" in proxy.name
    assert len(proxy.to_auto) == 9 and proxy.newly_auto_bad == []
    # the two confirmed cases over the $500 global max stay with a person
    assert {c.request_id for c in proxy.lane_moves} == {"RF-1030", "RF-2019"}
    assert any("not a structured field" in w for w in p.warnings)
    assert any("lets through" in w for w in p.warnings)


def test_proxy_only_when_rule_uses_confirmation(rules, data):
    assert len(run_preview(rules, draft(rules, add(OVER_300)), G, *data).datasets) == 2


def test_minutes_saved_from_history(rules, data):
    p = run_preview(rules, draft(rules, add(STOLEN)), G, *data)
    assert p.datasets[2].minutes_saved == 124


@pytest.mark.skipif(not CACHE_PATH.exists(), reason="no LLM cache")
def test_llm_cache_recovers_notes_fallback_cannot_read(rules):
    reader = LLMNoteReader("claude-haiku-5-5", offline=True)
    hist = [apply_signals(c, reader) for c in load_cached("history")]
    p = run_preview(rules, draft(rules, lambda d: setattr(d.get("amount_cap").when.all_[0], "value", 100)), G, hist, [])
    assert {c.request_id for c in p.datasets[0].to_auto} == {"RF-2140", "RF-2165"}


def test_publish_and_rollback(tmp_path):
    live, versions = tmp_path / "rules.yaml", tmp_path / "versions"
    live.write_text((ROOT / "rules" / "rules.yaml").read_text())
    v1 = load_ruleset(live)
    v2 = publish(draft(v1, add(OVER_300)), "manager", "big refunds to us", live, versions)
    assert v2.version == 2 and load_ruleset(live).get("over_300_to_us")
    v3 = rollback(1, "manager", live, versions)
    assert v3.version == 3 and v3.change_note == "Rollback to v1"
    assert v3.rules == v1.rules and [v.version for v in list_versions(versions)] == [1, 2, 3]


def test_publish_rejects_invalid(tmp_path):
    live, versions = tmp_path / "rules.yaml", tmp_path / "versions"
    live.write_text((ROOT / "rules" / "rules.yaml").read_text())
    bad = load_ruleset(live).model_copy(deep=True)
    bad.get("bad_data").enabled = False
    with pytest.raises(ValueError):
        publish(bad, "manager", "try to disable a safety rule", live, versions)
    assert load_ruleset(live).get("bad_data").enabled
