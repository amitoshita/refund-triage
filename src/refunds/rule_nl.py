"""Manager's English -> a DRAFT structured rule, plus plain-English rendering of rules.

The LLM only drafts. The draft is validated against the rule schema, shown back as a
sentence, and must be added to the draft rule set and previewed before it can be published.
"""

import json

from refunds.fields import FIELDS, OPERATORS
from refunds.llm import client, has_key
from refunds.rules import Lane, Rule, RuleSet

OP_WORDS = {"gt": ">", "gte": "≥", "lt": "<", "lte": "≤", "eq": "is", "ne": "is not", "in": "is one of",
            "not_in": "is not one of", "has_any": "has any of", "is_empty": "is empty", "not_empty": "is not empty",
            "is_missing": "is missing"}  # fmt: skip


def describe(rule: Rule) -> str:
    def cond(c):
        label = FIELDS[c.field][3]
        if c.value is None:
            return f"{label} {OP_WORDS[c.op]}"
        v = ", ".join(map(str, c.value)) if isinstance(c.value, list) else c.value
        if c.field == "amount_usd":
            v = f"${v:,.0f}" if float(v).is_integer() else f"${v:,.2f}"
        return f"{label} {OP_WORDS[c.op]} {v}"

    parts = [" and ".join(cond(c) for c in rule.when.all_)] if rule.when.all_ else []
    if rule.when.any_:
        parts.append("(" + " or ".join(cond(c) for c in rule.when.any_) + ")")
    when = " and ".join(p for p in parts if p)
    if rule.kind == "block":
        return f"If {when} → send to a person ({rule.lane.value} lane). Reviewer sees: \"{rule.reason}\""
    extra = f", even if blocked by: {', '.join(rule.overrides)}" if rule.overrides else ""
    return f"If {when} → may be auto-approved{extra} (guardrails still apply)."


def _schema(rules: RuleSet) -> dict:
    block_ids = [r.id for r in rules.rules if r.kind == "block" and not r.locked]
    return {
        "type": "object",
        "properties": {
            "understood": {"type": "boolean"},
            "question": {"type": "string"},
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": ["block", "eligible"]},
            "description": {"type": "string"},
            "conditions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": list(FIELDS)},
                        "op": {"type": "string", "enum": list(OPERATORS)},
                        "number": {"type": ["number", "null"]},
                        "boolean": {"type": ["boolean", "null"]},
                        "items": {"type": "array", "items": {"type": "string"}},
                        "text": {"type": ["string", "null"]},
                    },
                    "required": ["field", "op", "number", "boolean", "items", "text"],
                    "additionalProperties": False,
                },
            },
            "lane": {"type": "string", "enum": [l.value for l in Lane] + ["none"]},
            "reason": {"type": "string"},
            "overrides": {"type": "array", "items": {"type": "string", "enum": block_ids}},
        },
        "required": ["understood", "question", "id", "kind", "description", "conditions", "lane", "reason", "overrides"],
        "additionalProperties": False,
    }


def _system(rules: RuleSet) -> str:
    fields = {k: {"type": v[0].value, "allowed": v[2], "meaning": v[3]} for k, v in FIELDS.items()}
    current = [{"id": r.id, "kind": r.kind, "description": r.description, "locked": r.locked} for r in rules.rules]
    return f"""You translate a refund-operations manager's policy change into ONE draft rule for a rules engine.
The manager will review and preview it before anything goes live. Never invent fields.

Rule kinds:
- "block": cases matching the conditions go to a human. Needs lane ({[l.value for l in Lane]}) and a short
  reviewer-facing reason; the reason may use {{field}} placeholders and {{limit}} (the rule's first numeric threshold).
- "eligible": cases matching may be auto-approved. If they would normally be blocked by existing block rules,
  list those rule ids in overrides (only non-locked block rules). Global guardrails still apply.

Fields: {json.dumps(fields)}
Operators per type: {json.dumps({k: sorted(t.value for t in v) for k, v in OPERATORS.items()})}
For eligible rules use lane "none" and reason "". Put the condition value in `number`, `boolean`, or `items` (list, for in/not_in/has_any) or `text` (enum eq/ne).
Current rules: {json.dumps(current)}

If the request is ambiguous or can't be expressed with these fields, set understood=false and ask one short question.
Prefer changing an existing rule's threshold when that is what the manager means: say so in `question` and still
draft the closest new rule. id: lower_snake_case, unique."""


def draft_rule(text: str, rules: RuleSet, model: str) -> tuple[dict | None, str]:
    """Returns (rule dict ready for Rule.model_validate, or None; message for the manager)."""
    if not has_key():
        return None, "No API key: use the form builder instead."
    resp = client().messages.create(
        model=model,
        max_tokens=2048,
        system=_system(rules),
        messages=[{"role": "user", "content": text}],
        output_config={"format": {"type": "json_schema", "schema": _schema(rules)}},
    )
    if resp.stop_reason != "end_turn":
        return None, f"Couldn't draft a rule (stop reason: {resp.stop_reason})."
    out = json.loads(next(b.text for b in resp.content if b.type == "text"))
    conds = []
    for c in out["conditions"]:
        value = next((v for v in (c["number"], c["boolean"], c["items"] or None, c["text"]) if v is not None), None)
        conds.append({"field": c["field"], "op": c["op"], "value": value})
    rule = {"id": out["id"], "kind": out["kind"], "description": out["description"], "when": {"all": conds}}
    if out["kind"] == "block":
        rule |= {"lane": out["lane"], "reason": out["reason"]}
    elif out["overrides"]:
        rule["overrides"] = out["overrides"]
    return rule, ("" if out["understood"] else out["question"]) or out["question"]
