"""Rule schema: the policy as data.

A rule set is a list of two kinds of rule:

* ``block`` rules send a case to a human. Each one names the queue lane it lands
  in and the reason the reviewer sees.
* ``eligible`` rules describe what may be auto-approved. A case is auto-approved
  only if it matches at least one enabled eligible rule AND no enabled block rule
  fires (except block rules that the matching eligible rule explicitly overrides).

``locked`` block rules (bad data, duplicates, warning signs in notes) are safety
rails: they cannot be disabled or overridden from the policy editor.
"""

import re
import string
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from refunds.fields import FIELDS, OPERATORS, FieldType


class Lane(StrEnum):
    FRAUD = "fraud"  # fraud team
    CARRIER = "carrier"  # needs a carrier / delivery check
    PARTIAL = "partial"  # reviewer decides full vs partial
    POLICY = "policy"  # policy limits (amount, window, photo, repeat refunds)
    NOTES = "notes"  # warning signs found in free text
    DATA = "data"  # data needs fixing before anyone can decide


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: str
    value: Any = None

    @model_validator(mode="after")
    def _check(self) -> "Condition":
        if self.field not in FIELDS:
            raise ValueError(f"unknown field '{self.field}'")
        ftype, _, allowed, _ = FIELDS[self.field]
        if self.op not in OPERATORS:
            raise ValueError(f"unknown operator '{self.op}'")
        if ftype not in OPERATORS[self.op]:
            raise ValueError(f"operator '{self.op}' does not apply to {ftype} field '{self.field}'")

        v = self.value
        if self.op in {"is_empty", "not_empty", "is_missing"}:
            if v is not None:
                raise ValueError(f"operator '{self.op}' takes no value")
        elif ftype is FieldType.NUMBER:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"'{self.field}' needs a number, got {v!r}")
        elif ftype is FieldType.BOOL:
            if not isinstance(v, bool):
                raise ValueError(f"'{self.field}' needs true/false, got {v!r}")
        elif self.op in {"in", "not_in", "has_any"}:
            if not isinstance(v, list) or not v:
                raise ValueError(f"operator '{self.op}' needs a non-empty list")
            bad = [x for x in v if x not in allowed]
            if bad:
                raise ValueError(f"{bad} not valid for '{self.field}' (allowed: {allowed})")
        else:  # eq / ne on enum
            if v not in allowed:
                raise ValueError(f"{v!r} not valid for '{self.field}' (allowed: {allowed})")
        return self


class When(BaseModel):
    """All of ``all`` must hold, and at least one of ``any`` (if given)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    all_: list[Condition] = Field(default_factory=list, alias="all")
    any_: list[Condition] = Field(default_factory=list, alias="any")

    @model_validator(mode="after")
    def _non_empty(self) -> "When":
        if not self.all_ and not self.any_:
            raise ValueError("a rule needs at least one condition")
        return self


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: Literal["block", "eligible"]
    name: str | None = None  # short label for the manager, e.g. "Auto-approve limit"
    description: str  # plain English, shown to manager and reviewer
    enabled: bool = True
    when: When
    lane: Lane | None = None  # block only
    reason: str | None = None  # block only: reviewer-facing text; {field} placeholders, {limit} = the rule's first numeric threshold
    policy_ref: int | None = None  # policy note number this implements
    locked: bool = False  # safety rail: cannot be disabled or overridden
    overrides: list[str] = Field(default_factory=list)  # eligible only: block rule ids it lets through

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", v):
            raise ValueError("id must be lower_snake_case")
        return v

    @property
    def label(self) -> str:
        return self.name or self.id.replace("_", " ").capitalize()

    @model_validator(mode="after")
    def _kind_fields(self) -> "Rule":
        if self.kind == "block":
            if self.lane is None or not self.reason:
                raise ValueError(f"block rule '{self.id}' needs a lane and a reason")
            if self.overrides:
                raise ValueError(f"block rule '{self.id}' cannot override other rules")
            placeholders = {f for _, f, _, _ in string.Formatter().parse(self.reason) if f}
            unknown = placeholders - FIELDS.keys() - {"limit"}
            if unknown:
                raise ValueError(f"reason for '{self.id}' uses unknown placeholders {sorted(unknown)}")
        else:
            if self.lane is not None or self.reason is not None:
                raise ValueError(f"eligible rule '{self.id}' takes no lane/reason")
            if self.locked:
                raise ValueError("only block rules can be locked")
        if self.locked and not self.enabled:
            raise ValueError(f"locked rule '{self.id}' cannot be disabled")
        return self


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    created_at: datetime
    author: str
    change_note: str
    rules: list[Rule]

    @model_validator(mode="after")
    def _consistency(self) -> "RuleSet":
        ids = [r.id for r in self.rules]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate rule ids: {sorted(dupes)}")
        by_id = {r.id: r for r in self.rules}
        for r in self.rules:
            for target in r.overrides:
                t = by_id.get(target)
                if t is None or t.kind != "block":
                    raise ValueError(f"'{r.id}' overrides '{target}', which is not a block rule")
                if t.locked:
                    raise ValueError(f"'{r.id}' cannot override locked safety rule '{target}'")
        if not any(r.kind == "eligible" and r.enabled for r in self.rules):
            raise ValueError("no enabled eligible rule: nothing could ever be auto-approved")
        return self

    def get(self, rule_id: str) -> Rule:
        return next(r for r in self.rules if r.id == rule_id)


def load_ruleset(path: str | Path) -> RuleSet:
    return RuleSet.model_validate(yaml.safe_load(Path(path).read_text()))


def dump_ruleset(rs: RuleSet) -> str:
    data = rs.model_dump(mode="json", by_alias=True, exclude_defaults=True)
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
