"""Streamlit app: quick-change buttons on the policy manager."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def policy_page() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    at.sidebar.radio[0].set_value("Policy manager").run()
    return at


def click(at: AppTest, label: str) -> AppTest:
    next(b for b in at.button if b.label == label).click().run()
    return at


def test_example_button_twice_adds_rule_once():
    at = click(click(policy_page(), "Stolen-card cases go straight through"), "Stolen-card cases go straight through")
    ids = [r["id"] for r in at.session_state.draft["rules"]]
    assert ids.count("stolen_card_confirmed") == 1
    assert not any(i.startswith("stolen_card_confirmed_") for i in ids)
    assert any("Already in your changes" in i.value for i in at.info)


def test_over_300_button_twice_adds_rule_once():
    at = click(click(policy_page(), "Anything over $300 comes to us"), "Anything over $300 comes to us")
    ids = [r["id"] for r in at.session_state.draft["rules"]]
    assert ids.count("over_300_to_us") == 1
    assert not any(i.startswith("over_300_to_us_") for i in ids)
