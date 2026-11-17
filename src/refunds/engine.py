"""Deterministic decision engine. Pure: same case + rules + guardrails -> same decision.

Order of evaluation:
1. Evaluate every enabled rule against the case.
2. A case is auto-approvable if some matching eligible rule overrides every block rule
   that fired (locked rules can't be overridden; the schema enforces that).
3. System guardrails sit above the rules: the kill switch and the global max amount
   send the case to a person regardless of rules or overrides.
4. A case going to a person lands in the highest-precedence lane among what fired.
"""

from dataclasses import dataclass, field
from typing import Literal

from refunds.config import Guardrails
from refunds.fields import FIELDS, FieldType
from refunds.ingest import Case
from refunds.rules import Condition, Lane, Rule, RuleSet

LANE_PRECEDENCE = [Lane.FRAUD, Lane.DATA, Lane.NOTES, Lane.CARRIER, Lane.PARTIAL, Lane.POLICY]


@dataclass
class FiredRule:
    rule_id: str
    lane: Lane | None
    text: str  # reviewer-facing reason
    policy_ref: int | None = None
    overridden_by: str | None = None  # eligible rule that let this block through
    system: bool = False  # guardrail, not a policy rule


@dataclass
class Decision:
    request_id: str
    outcome: Literal["auto_approve", "human"]
    lane: Lane | None
    reasons: list[FiredRule] = field(default_factory=list)  # blocks still in force (why it's not auto)
    overridden: list[FiredRule] = field(default_factory=list)  # blocks lifted by an eligible rule
    approved_by: str | None = None  # eligible rule id
    ruleset_version: int | None = None


def _eval(cond: Condition, case: Case) -> bool:
    v = case.get(cond.field)
    ftype = FIELDS[cond.field][0]
    if cond.op == "is_missing":
        return v is None
    if cond.op == "is_empty":
        return not v
    if cond.op == "not_empty":
        return bool(v)
    if cond.op == "has_any":
        return bool(set(v) & set(cond.value))
    if v is None:  # missing values never satisfy a comparison; bad_data catches them
        return False
    match cond.op:
        case "gt":
            return v > cond.value
        case "gte":
            return v >= cond.value
        case "lt":
            return v < cond.value
        case "lte":
            return v <= cond.value
        case "eq":
            return v == cond.value
        case "ne":
            return v != cond.value
        case "in":
            return v in cond.value
        case "not_in":
            return v not in cond.value
    raise ValueError(f"unhandled operator {cond.op} for {ftype}")


def matches(rule: Rule, case: Case) -> bool:
    w = rule.when
    return all(_eval(c, case) for c in w.all_) and (not w.any_ or any(_eval(c, case) for c in w.any_))


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.0f}" if v.is_integer() else f"{v:,.2f}"
    if isinstance(v, (set, list)):
        return ", ".join(sorted(str(x).replace("_", " ") for x in v)) or "none"
    return "missing" if v is None else str(v)


def render_reason(rule: Rule, case: Case) -> str:
    values = {name: _fmt(case.get(name)) for name in FIELDS}
    if case.issue_details:
        values["data_issues"] = "; ".join(case.issue_details)
    limit = next(
        (c.value for c in rule.when.all_ + rule.when.any_ if FIELDS[c.field][0] is FieldType.NUMBER), None
    )
    values["limit"] = _fmt(float(limit)) if limit is not None else "?"
    return rule.reason.format(**values)


def _lane(fired: list[FiredRule]) -> Lane:
    lanes = {f.lane for f in fired if f.lane is not None}
    return next((l for l in LANE_PRECEDENCE if l in lanes), Lane.POLICY)


def decide(case: Case, rules: RuleSet, guardrails: Guardrails) -> Decision:
    active = [r for r in rules.rules if r.enabled]
    blocks = [r for r in active if r.kind == "block" and matches(r, case)]
    eligibles = [r for r in active if r.kind == "eligible" and matches(r, case)]
    fired = {r.id: FiredRule(r.id, r.lane, render_reason(r, case), r.policy_ref) for r in blocks}

    # Pick the eligible rule that leaves the fewest blocks in force (ties: file order, irrelevant to outcome).
    best, remaining = None, list(fired)
    for e in eligibles:
        left = [b for b in fired if b not in e.overrides]
        if best is None or len(left) < len(remaining):
            best, remaining = e, left

    overridden = []
    if best is not None:
        for b in fired:
            if b not in remaining:
                fired[b].overridden_by = best.id
                overridden.append(fired[b])
    reasons = [fired[b] for b in remaining]

    if best is None and not reasons:  # only when no block rule already explains it
        reasons.append(FiredRule("not_eligible", Lane.POLICY, "Not covered by any auto-approve rule.", system=True))

    g = guardrails
    if case.amount_usd is not None and case.amount_usd > g.max_auto_amount_usd:
        reasons.append(FiredRule("global_max", Lane.POLICY,
                                 f"Over the system-wide auto-approval maximum of ${_fmt(float(g.max_auto_amount_usd))}.",
                                 system=True))  # fmt: skip
    if g.kill_switch:
        reasons.append(FiredRule("kill_switch", Lane.POLICY, "Kill switch is on: every case goes to a person.", system=True))

    if reasons:
        reasons.sort(key=lambda r: LANE_PRECEDENCE.index(r.lane) if r.lane in LANE_PRECEDENCE else len(LANE_PRECEDENCE))
        return Decision(case.request_id, "human", _lane(reasons), reasons, overridden, None, rules.version)
    return Decision(case.request_id, "auto_approve", None, [], overridden, best.id, rules.version)
