"""Dry run of a draft rule set against history and pending, before anything goes live.

Shows which cases change route, $ affected, how many newly auto-approved history
cases were bad outcomes, reviewer minutes saved, and examples. Also runs a labelled
*proxy* view for signals that don't exist as structured data yet (fraud-team
confirmation): history with that field filled from the after-the-fact outcome note.
"""

import copy
from dataclasses import dataclass, field

from refunds.config import Guardrails
from refunds.engine import Decision, decide
from refunds.evaluate import bad_if_approved
from refunds.fields import FIELDS, Source
from refunds.ingest import Case
from refunds.rules import RuleSet


@dataclass
class Change:
    request_id: str
    amount_usd: float | None
    before: str  # "auto" or lane name
    after: str
    after_reasons: list[str]
    bad: str | None = None  # history only: why approving would have been wrong
    review_minutes: float | None = None


@dataclass
class DatasetPreview:
    name: str
    total: int
    auto_before: int
    auto_after: int
    usd_auto_before: float
    usd_auto_after: float
    changes: list[Change] = field(default_factory=list)

    @property
    def to_auto(self) -> list[Change]:
        return [c for c in self.changes if c.after == "auto"]

    @property
    def to_human(self) -> list[Change]:
        return [c for c in self.changes if c.before == "auto"]

    @property
    def lane_moves(self) -> list[Change]:
        return [c for c in self.changes if "auto" not in (c.before, c.after)]

    @property
    def newly_auto_bad(self) -> list[Change]:
        return [c for c in self.to_auto if c.bad]

    @property
    def minutes_saved(self) -> float:
        return sum(c.review_minutes or 0 for c in self.to_auto)


@dataclass
class Preview:
    rule_diff: list[str]
    warnings: list[str]
    datasets: list[DatasetPreview]


def _route(d: Decision) -> str:
    return "auto" if d.outcome == "auto_approve" else str(d.lane)


def _minutes(c: Case) -> float | None:
    try:
        return float(c.raw.get("review_minutes") or "")
    except ValueError:
        return None


def diff_rules(current: RuleSet, draft: RuleSet) -> list[str]:
    cur, new = {r.id: r for r in current.rules}, {r.id: r for r in draft.rules}
    out = [f"+ added '{i}': {new[i].description}" for i in new.keys() - cur.keys()]
    out += [f"- removed '{i}': {cur[i].description}" for i in cur.keys() - new.keys()]
    for i in cur.keys() & new.keys():
        a, b = cur[i].model_dump(), new[i].model_dump()
        if a != b:
            changed = [k for k in a if a[k] != b[k]]
            out.append(f"~ changed '{i}' ({', '.join(changed)})")
    return sorted(out)


def warnings_for(current: RuleSet, draft: RuleSet) -> list[str]:
    out = []
    cur_ids = {r.id: r for r in current.rules}
    for r in draft.rules:
        if r.id in cur_ids and cur_ids[r.id] == r:
            continue
        for c in r.when.all_ + r.when.any_:
            src = FIELDS[c.field][1]
            if src is Source.DERIVED and c.field == "fraud_team_confirmed_stolen":
                out.append(
                    f"'{r.id}' depends on 'fraud team confirmed stolen', which is not a structured field: it is read "
                    "from the support agent's note with a strict phrase match. History has no such notes, so the "
                    "history preview is also shown with a labelled proxy (outcome notes)."
                )
            elif src is Source.LLM and r.kind == "eligible":
                out.append(f"'{r.id}' uses LLM-extracted '{c.field}' to approve; LLM output should only block.")
        if r.kind == "eligible" and r.overrides:
            out.append(f"'{r.id}' lets through cases normally blocked by: {', '.join(r.overrides)}.")
    return out


def preview_dataset(name: str, cases: list[Case], current: RuleSet, draft: RuleSet, g: Guardrails,
                    history: bool) -> DatasetPreview:  # fmt: skip
    """``cases`` must already have signals applied."""
    p = DatasetPreview(name, len(cases), 0, 0, 0.0, 0.0)
    for c in cases:
        before, after = decide(c, current, g), decide(c, draft, g)
        rb, ra = _route(before), _route(after)
        amt = c.amount_usd or 0.0
        p.auto_before += rb == "auto"
        p.auto_after += ra == "auto"
        p.usd_auto_before += amt if rb == "auto" else 0
        p.usd_auto_after += amt if ra == "auto" else 0
        if rb != ra:
            p.changes.append(Change(c.request_id, c.amount_usd, rb, ra, [r.text for r in after.reasons],
                                    bad_if_approved(c) if history else None,
                                    _minutes(c) if history else None))  # fmt: skip
    return p


def with_fraud_confirmation_proxy(cases: list[Case]) -> list[Case]:
    """PROXY, clearly labelled: pretend the fraud team had a structured 'confirmed stolen' field,
    filled from history's after-the-fact outcome note 'fraud team confirmed'."""
    out = []
    for c in cases:
        c2 = copy.copy(c)
        c2.fraud_team_confirmed_stolen = "fraud team confirmed" in c.raw.get("outcome_note", "").lower()
        out.append(c2)
    return out


def run_preview(current: RuleSet, draft: RuleSet, g: Guardrails, history: list[Case], pending: list[Case]) -> Preview:
    warnings = warnings_for(current, draft)
    datasets = [
        preview_dataset("History (decided requests)", history, current, draft, g, history=True),
        preview_dataset("Pending (waiting now)", pending, current, draft, g, history=False),
    ]
    uses_confirmation = any(
        c.field == "fraud_team_confirmed_stolen" for r in draft.rules if r.enabled for c in r.when.all_ + r.when.any_
    )
    if uses_confirmation:
        datasets.append(preview_dataset(
            "History, PROXY: as if the fraud team had filled a 'confirmed stolen' field (from outcome notes)",
            with_fraud_confirmation_proxy(history), current, draft, g, history=True))  # fmt: skip
    return Preview(diff_rules(current, draft), warnings, datasets)
