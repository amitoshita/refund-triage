from datetime import date

import pytest

from refunds.ingest import load_cases, normalise_row, parse_amount, parse_date
from tests.conftest import BASE_ROW, ROOT


@pytest.mark.parametrize(
    "raw, expected",
    [("42", 42.0), ("42 ", 42.0), ("$43", 43.0), ("USD 120.00", 120.0), ("55.00 USD", 55.0),
     ("$1,150.00", 1150.0), ("38.82", 38.82), ("", None), ("abc", None), ("-5", None), ("12.3.4", None)],
)  # fmt: skip
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("2026-06-02", date(2026, 6, 2)), ("2026-06-15T07:11:00Z", date(2026, 6, 15)),
     ("09/06/2026", date(2026, 6, 9)), ("03/09/2026", date(2026, 9, 3)), ("2026-13-01", None), ("soon", None)],
)  # fmt: skip
def test_parse_date_ddmm(raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [("late", "late_delivery"), ("damaged", "arrived_damaged"), ("changed mind", "changed_mind"),
     ("Never Arrived", "never_arrived"), ("wrong item", "wrong_item"), ("wrong_size", "wrong_size")],
)  # fmt: skip
def test_reason_synonyms(raw, expected):
    assert normalise_row({**BASE_ROW, "stated_reason": raw}).reason == expected


def test_unknown_reason_is_issue():
    c = normalise_row({**BASE_ROW, "stated_reason": "stolen"})
    assert c.reason is None and "unknown_reason" in c.data_issues


@pytest.mark.parametrize("raw, expected", [("yes", "yes"), ("Y", "yes"), ("true", "yes"), ("no", "no"),
                                           ("N", "no"), ("false", "no"), ("", "unknown"), ("maybe", "unknown")])  # fmt: skip
def test_fraud_flag_blank_is_unknown(raw, expected):
    assert normalise_row({**BASE_ROW, "fraud_flag": raw}).fraud_flag == expected


def test_category_case_insensitive():
    assert normalise_row({**BASE_ROW, "category": "Electronics"}).category == "electronics"


@pytest.mark.parametrize("col", ["tenure_months", "customer_id", "days_since_delivery", "amount_usd"])
def test_missing_values_are_issues(col):
    c = normalise_row({**BASE_ROW, col: ""})
    assert c.data_issues and any(col.split("_")[0] in d for d in c.issue_details)


def test_negative_days():
    c = normalise_row({**BASE_ROW, "days_since_delivery": "-2"})
    assert "negative_days" in c.data_issues and c.days_since_delivery is None


def test_channel_from_id():
    assert normalise_row({**BASE_ROW, "request_id": "RF-1001"}).channel == "web"
    assert normalise_row({**BASE_ROW, "request_id": "RF-2001"}).channel == "support"


def test_pending_duplicates_kept_and_flagged():
    cases = load_cases(ROOT / "data" / "pending.csv")
    dupes = [c for c in cases if c.request_id == "RF-2183"]
    assert len(cases) == 21 and len(dupes) == 2
    assert all(c.is_duplicate and "2 times" in c.duplicate_detail for c in dupes)


def test_known_ids_flag_duplicates():
    cases = load_cases(ROOT / "data" / "pending.csv", known_ids={"RF-1069"})
    assert next(c for c in cases if c.request_id == "RF-1069").is_duplicate


def test_history_exact_duplicates_dropped():
    assert len(load_cases(ROOT / "data" / "history.csv", drop_exact_duplicates=True)) == 248
    assert len(load_cases(ROOT / "data" / "history.csv")) == 251


def test_missing_required_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("request_id,amount_usd\nRF-1,10\n")
    with pytest.raises(ValueError, match="missing required columns"):
        load_cases(p)
