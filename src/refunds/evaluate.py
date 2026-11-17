"""Note-reader eval and history backtest (LLM vs keyword fallback)."""

import re
from dataclasses import dataclass

import yaml

from refunds.config import ROOT, load_config
from refunds.engine import decide
from refunds.ingest import Case, load_cases
from refunds.llm import PRICES, LLMNoteReader, Usage
from refunds.rules import RuleSet, load_ruleset
from refunds.signals import apply_signals, customer_note_cleared

DATA = ROOT / "data"
LABELS = ROOT / "eval" / "note_labels.yaml"


# ---- history labels -----------------------------------------------------------------


def bad_if_approved(c: Case) -> str | None:
    """Why a full approval of this historical case would have been wrong (None = no known problem).
    History is not ground truth: this combines outcomes with the written policy."""
    out, dec = c.raw["outcome_note"].lower(), c.raw["decision"]
    notes = f"{c.customer_note} {c.support_note}".lower()
    if "chargeback" in out:
        return "chargeback"
    if dec == "partial":
        return "reviewer gave a partial refund"
    if dec == "rejected" and "overturned" not in out and "refunded on appeal" not in out:
        return "correctly rejected"
    if c.reason == "changed_mind" and (c.days_since_delivery or 0) > 14:
        return "outside 14-day window (policy #2)"
    if c.reason == "arrived_damaged" and (c.amount_usd or 0) > 50 and not c.has_photo_evidence:
        return "damage > $50 without photo (policy #3)"
    if c.fraud_flag == "yes" and "fraud team confirmed" not in out:
        return "fraud flag without confirmation (policy #5)"
    if re.search(r"signed|signature|\bpod\b", notes):
        return "signature on file (policy #4)"
    if (c.prior_refunds_12m or 0) >= 3:
        return "3+ prior refunds"
    return None


def load_cached(file: str) -> list[Case]:
    return load_cases(DATA / f"{file}.csv", drop_exact_duplicates=(file == "history"))


# ---- note eval -----------------------------------------------------------------------


@dataclass
class EvalResult:
    name: str
    caught: list[str]
    missed: list[str]
    right_flag: int
    false_flags: list[str]
    usage: Usage | None = None

    def line(self, n_pos: int, n_neg: int) -> str:
        cost = ""
        if self.usage is not None:
            c = self.usage.cost(self.name)
            cost = f" | {self.usage.calls} API calls, {self.usage.input_tokens:,} in / {self.usage.output_tokens:,} out tokens"
            cost += f", ${c:.4f}" if c is not None else ", price unknown"
        return (f"{self.name:<20} recall {len(self.caught)}/{n_pos} ({len(self.caught)/n_pos:.0%}) | "
                f"right flag {self.right_flag}/{n_pos} | false flags {len(self.false_flags)}/{n_neg}{cost}")  # fmt: skip


def _label_cases():
    labels = yaml.safe_load(LABELS.read_text())
    by_file = {f: {c.request_id: c for c in load_cached(f)} for f in ("history", "pending")}
    # RF-2183 appears twice in pending; labelled cases are unique ids so dict lookup is fine
    pos = [(by_file[x["file"]][x["id"]], set(x["flags"])) for x in labels["positives"]]
    neg = [by_file[x["file"]][x["id"]] for x in labels["negatives"]]
    return pos, neg


def score_reader(name: str, reader) -> EvalResult:
    pos, neg = _label_cases()
    caught, missed, right, false = [], [], 0, []
    for c, expected in pos:
        flags = apply_signals(c, reader).note_flags
        (caught if flags else missed).append(c.request_id)
        right += bool(flags & expected)
    for c in neg:
        flags = apply_signals(c, reader).note_flags
        if flags:
            false.append(f"{c.request_id}:{','.join(sorted(flags))}")
    return EvalResult(name, caught, missed, right, false, getattr(reader, "usage", None))


def run_note_eval(models: list[str] | None = None) -> list[EvalResult]:
    cfg = load_config()
    models = models or cfg.llm.candidates
    pos, neg = _label_cases()
    print(f"Labelled set: {len(pos)} notes with warning signs, {len(neg)} benign notes\n")
    results = [score_reader("keyword fallback", None)]
    for m in models:
        reader = LLMNoteReader(m)
        results.append(score_reader(m, reader))
        reader.save()
    for r in results:
        print(r.line(len(pos), len(neg)))
    fb = results[0]
    for r in results[1:]:
        print(f"\n{r.name}")
        print(f"  caught that fallback missed: {sorted(set(r.caught) - set(fb.caught)) or '-'}")
        print(f"  missed: {r.missed or '-'}")
        print(f"  false flags: {r.false_flags or '-'}")
    print(f"\nkeyword fallback missed: {fb.missed or '-'}")
    print(f"keyword fallback false flags: {fb.false_flags or '-'}")
    total = sum((r.usage.cost(r.name) or 0) for r in results[1:] if r.usage)
    print(f"\nAPI cost this run (known prices): ${total:.4f}")
    return results


# ---- backtest ------------------------------------------------------------------------


def coverage(cases: list[Case], rules: RuleSet, reader) -> dict:
    cfg = load_config()
    auto, bad = [], []
    for c in cases:
        d = decide(apply_signals(c, reader), rules, cfg.guardrails)
        if d.outcome == "auto_approve":
            auto.append(c)
            if why := bad_if_approved(c):
                bad.append((c.request_id, why))
    return {"n": len(auto), "usd": sum(c.amount_usd for c in auto), "bad": bad, "ids": {c.request_id for c in auto}}


def run_backtest(model: str | None = None) -> None:
    cfg = load_config()
    rules = load_ruleset(ROOT / "rules" / "rules.yaml")
    model = model or cfg.llm.model
    hist, pend = load_cached("history"), load_cached("pending")
    reader = LLMNoteReader(model)

    no_notes = rules.model_copy(deep=True)
    no_notes.rules = [r for r in no_notes.rules if r.id != "note_warning_signs"]
    print(f"History: {len(hist)} decided requests (exact duplicate rows removed). Rules v{rules.version}.\n")
    rows = [
        ("structured rules only (no note check)", coverage(hist, no_notes, None)),
        ("keyword fallback", coverage(hist, rules, None)),
        (f"LLM {model}", coverage(hist, rules, reader)),
    ]
    reader.save()
    for name, r in rows:
        bad = f" -> {r['bad']}" if r["bad"] else ""
        print(f"{name:<40} auto {r['n']:>3} ({r['n']/len(hist):.0%})  ${r['usd']:>8,.2f}  bad-if-approved {len(r['bad'])}{bad}")
    fb, lm = rows[1][1], rows[2][1]
    print(f"\n  auto under LLM but not fallback: {sorted(lm['ids'] - fb['ids'])}")
    print(f"  auto under fallback but not LLM: {sorted(fb['ids'] - lm['ids'])}")

    print("\nPending:")
    for name, r in [("keyword fallback", coverage(pend, rules, None)), (f"LLM {model}", coverage(pend, rules, reader))]:
        print(f"  {name:<20} auto {sorted(r['ids'])}  ${r['usd']:,.2f}")
    reader.save()

    digits = [c for c in hist + pend if c.customer_note and re.search(r"\d", c.customer_note)]
    only_digit = [c for c in digits if len(c.customer_note) <= 60 and c.customer_note.isascii()]
    print(f"\n'contains a digit' fallback rule: {len(digits)} customer notes contain a digit; "
          f"{len(only_digit)} would otherwise pass the fallback's length/ASCII check: "
          f"{[c.request_id for c in only_digit]}")  # fmt: skip
    unreadable = [c for c in hist + pend if c.customer_note and not customer_note_cleared(c.customer_note)]
    print(f"Fallback 'unreadable' total: {len(unreadable)} customer notes (long, non-English, or digits).")
    print(f"\nLLM usage this run: {reader.usage.calls} API calls, {reader.usage.cache_hits} cache hits, "
          f"cost {('$%.4f' % reader.usage.cost(model)) if model in PRICES else 'price unknown'}")  # fmt: skip


# ---- held-out set --------------------------------------------------------------------

HELDOUT = ROOT / "eval" / "heldout_notes.yaml"


def run_heldout(models: list[str]) -> None:
    from refunds.ingest import normalise_row

    base = {"request_id": "RF-9000", "requested_at": "2026-10-01", "customer_id": "CU-9", "tenure_months": "20",
            "prior_refunds_12m": "0", "amount_usd": "40", "category": "home", "payment_method": "card",
            "days_since_delivery": "5", "fraud_flag": "no"}  # fmt: skip
    items = yaml.safe_load(HELDOUT.read_text())["cases"]
    cases = [(x, normalise_row({**base, "request_id": f"RF-9{i:03d}", "stated_reason": x["reason"],
                                "customer_note": x.get("customer", ""), "support_note": x.get("support", "")}))
             for i, x in enumerate(items)]  # fmt: skip
    n_pos = sum(x["warning"] for x, _ in cases)
    n_neg = len(cases) - n_pos
    print(f"Held-out set: {n_pos} with warning signs, {n_neg} benign (labelled before running)\n")
    readers = [("keyword fallback", None)] + [(m, LLMNoteReader(m, cache_path=ROOT / "llm_cache" / "heldout.json")) for m in models]
    for name, reader in readers:
        caught, missed, right, false = [], [], 0, []
        for x, c in cases:
            flags = apply_signals(c, reader).note_flags
            if x["warning"]:
                (caught if flags else missed).append(x["id"])
                right += bool(flags & set(x["flags"]))
            elif flags:
                false.append(f"{x['id']}:{','.join(sorted(flags))}")
        usage = getattr(reader, "usage", None)
        cost = f" | ${usage.cost(name):.4f}" if usage and usage.cost(name) is not None else ""
        print(f"{name:<20} recall {len(caught)}/{n_pos} | right flag {right}/{n_pos} | false flags {len(false)}/{n_neg}{cost}")
        print(f"   missed: {missed or '-'}   false: {false or '-'}")
        if reader is not None:
            reader.save()
