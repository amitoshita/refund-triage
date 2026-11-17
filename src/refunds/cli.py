"""Thin CLI.

refunds run FILE [--no-llm] [--out out/decisions.csv]
refunds models
refunds eval-notes [--models m1 m2 ...]
refunds backtest
"""

import argparse
import csv
import sys
from pathlib import Path

from refunds.config import ROOT, load_config
from refunds.rules import load_ruleset

HISTORY = ROOT / "data" / "history.csv"
RULES = ROOT / "rules" / "rules.yaml"


def make_reader(no_llm: bool, model: str | None = None):
    from refunds import llm

    cfg = load_config()
    if no_llm:
        return None
    return llm.LLMNoteReader(model or cfg.llm.model, offline=not llm.has_key())


def cmd_run(args):
    from refunds.ingest import load_cases
    from refunds.pipeline import run_file

    cfg, rules = load_config(), load_ruleset(RULES)
    known = [c.request_id for c in load_cases(HISTORY)] if Path(args.file).resolve() != HISTORY.resolve() else []
    reader = make_reader(args.no_llm)
    results = run_file(args.file, rules, cfg, known_ids=known, reader=reader)
    if reader is not None:
        reader.save()

    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["request_id", "amount_usd", "outcome", "lane", "reasons", "note_flags", "rule_version"])
        for c, d in results:
            w.writerow([c.request_id, c.amount_usd, d.outcome, d.lane or "", " | ".join(r.text for r in d.reasons),
                        ", ".join(sorted(c.note_flags)), d.ruleset_version])  # fmt: skip

    auto = [(c, d) for c, d in results if d.outcome == "auto_approve"]
    mode = "keyword fallback" if reader is None else f"LLM {reader.model}" + (" (cache only)" if reader.offline else "")
    print(f"{len(results)} requests | note reader: {mode} | rules v{rules.version}")
    print(f"auto-approved: {len(auto)} (${sum(c.amount_usd for c, _ in auto):,.2f}) | to a person: {len(results) - len(auto)}")
    for c, d in results:
        tag = "AUTO " if d.outcome == "auto_approve" else f"{d.lane:<6}"
        print(f"  {tag} {c.request_id}  ${c.amount_usd or 0:>8,.2f}  {d.reasons[0].text if d.reasons else ''}")
    print(f"written: {out}")


def cmd_models(args):
    from refunds import llm

    if not llm.has_key():
        sys.exit("ANTHROPIC_API_KEY not set (see .env.example)")
    available = llm.list_models()
    cfg = load_config()
    for m in dict.fromkeys(cfg.llm.candidates + [cfg.llm.fallback_model]):
        info = available.get(m)
        print(f"{m:<22} {'AVAILABLE' if info else 'not available'}  {info or ''}")


def cmd_eval_notes(args):
    from refunds.evaluate import run_note_eval

    run_note_eval(args.models)


def cmd_backtest(args):
    from refunds.evaluate import run_backtest

    run_backtest(args.model)


def main(argv=None):
    p = argparse.ArgumentParser(prog="refunds")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="decide every request in a CSV")
    r.add_argument("file")
    r.add_argument("--no-llm", action="store_true", help="keyword fallback only")
    r.add_argument("--out", default=str(ROOT / "out" / "decisions.csv"))
    r.set_defaults(fn=cmd_run)
    sub.add_parser("models", help="check which configured models the API key can use").set_defaults(fn=cmd_models)
    e = sub.add_parser("eval-notes", help="score note readers on the labelled set")
    e.add_argument("--models", nargs="*")
    e.set_defaults(fn=cmd_eval_notes)
    b = sub.add_parser("backtest", help="replay history: LLM vs keyword fallback")
    b.add_argument("--model")
    b.set_defaults(fn=cmd_backtest)
    args = p.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
