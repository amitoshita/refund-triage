"""Ingest -> signals -> decide, for a whole file."""

from pathlib import Path
from typing import Iterable

from refunds.config import Config
from refunds.engine import Decision, decide
from refunds.ingest import Case, load_cases
from refunds.rules import RuleSet
from refunds.signals import NoteReader, apply_signals


def run_file(
    path: str | Path,
    rules: RuleSet,
    config: Config,
    known_ids: Iterable[str] = (),
    reader: NoteReader | None = None,
    drop_exact_duplicates: bool = False,
) -> list[tuple[Case, Decision]]:
    cases = load_cases(path, known_ids, drop_exact_duplicates)
    return [(c, decide(apply_signals(c, reader), rules, config.guardrails)) for c in cases]
