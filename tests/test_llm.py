"""LLM reader tests that never call the API."""

import json

import pytest

from refunds.llm import SCHEMA, LLMNoteReader
from refunds.signals import apply_signals
from tests.conftest import make_case


def test_schema_cannot_express_approval():
    assert set(SCHEMA["properties"]) == {"flags", "summary_en"}
    assert "approve" not in json.dumps(SCHEMA).lower()


def test_offline_without_cache_routes_to_person(tmp_path):
    reader = LLMNoteReader("claude-haiku-5-5", offline=True, cache_path=tmp_path / "c.json")
    c = apply_signals(make_case(customer_note="ordered L got M"), reader)
    assert "unreadable" in c.note_flags


def test_cached_result_used_and_cannot_remove_keyword_flags(tmp_path):
    reader = LLMNoteReader("claude-haiku-5-5", offline=True, cache_path=tmp_path / "c.json")
    c = make_case(customer_note="already refunded in store")
    reader._cache[reader._key(c)] = {"flags": [], "summary_en": "benign"}
    apply_signals(c, reader)
    assert "already_refunded" in c.note_flags and reader.usage.calls == 0


def test_empty_notes_skip_llm(tmp_path):
    reader = LLMNoteReader("claude-haiku-5-5", offline=True, cache_path=tmp_path / "c.json")
    assert apply_signals(make_case(), reader).note_flags == set()


@pytest.mark.parametrize("flag", ["injection_attempt", "already_refunded"])
def test_llm_flags_block(flag, tmp_path, rules, guards):
    from refunds.engine import decide

    reader = LLMNoteReader("claude-haiku-5-5", offline=True, cache_path=tmp_path / "c.json")
    c = make_case(customer_note="hello")
    reader._cache[reader._key(c)] = {"flags": [{"flag": flag, "evidence": "x"}], "summary_en": ""}
    assert decide(apply_signals(c, reader), rules, guards).outcome == "human"
