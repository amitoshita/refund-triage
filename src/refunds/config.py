"""System config (guardrails, model choice). Separate from the policy rule set on purpose:
the manager edits rules; guardrails sit above them and only an engineer changes them."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

ROOT = Path(__file__).resolve().parents[2]


class Guardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_auto_amount_usd: float = Field(500, gt=0)
    kill_switch: bool = False


class LLMConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = "claude-haiku-5-5"
    candidates: list[str] = Field(default_factory=lambda: ["claude-haiku-5-5", "claude-sonnet-5-5"])
    fallback_model: str = "claude-haiku-4-5"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guardrails: Guardrails = Field(default_factory=Guardrails)
    llm: LLMConfig = Field(default_factory=LLMConfig)


def load_config(path: str | Path = ROOT / "config.yaml") -> Config:
    p = Path(path)
    return Config.model_validate(yaml.safe_load(p.read_text()) if p.exists() else {})
